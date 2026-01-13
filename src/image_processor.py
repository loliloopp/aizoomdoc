"""
Обработка изображений: ресайз, кроп, загрузка PDF с S3 и подготовка для LLM.
"""

import logging
import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import cv2
import numpy as np
import requests
import fitz  # PyMuPDF
from urllib.parse import urlparse

from .config import config
from .models import Page, ViewportCrop, ZoomRequest

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Обработчик изображений (локальных и удаленных PDF)."""
    
    def __init__(self, images_root: Path):
        self.images_root = images_root
        self.temp_dir = Path(tempfile.gettempdir()) / "aizoomdoc_cache"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Кэш оригиналов изображений (пути к временным файлам)
        # Key: image_id (или url hash), Value: Path to full resolution image
        self._image_cache: Dict[str, Path] = {} 
        # Размеры оригиналов {image_id: (width, height)}
        self._image_sizes: Dict[str, Tuple[int, int]] = {}

    def get_page_image_path(self, page_number: int) -> Path:
        """Получает путь к локальному изображению страницы."""
        filename = f"page_{page_number:03d}_full.jpg"
        return self.images_root / filename

    def load_local_page(self, page_number: int) -> Optional[np.ndarray]:
        """Загружает оригинал локальной страницы."""
        path = self.get_page_image_path(page_number)
        if not path.exists():
            return None
        return cv2.imread(str(path))

    def download_and_process_pdf(
        self,
        url: str,
        max_side: int = None,
        image_id: Optional[str] = None,
    ) -> List[ViewportCrop]:
        """
        1. Скачивает PDF по ссылке.
        2. Рендерит первую страницу в полном разрешении.
        3. Сохраняет оригинал в кэш.
        4. Создает превью (max_side из config.PREVIEW_MAX_SIDE).
        5. Если превью слишком мелкое (scale > config.AUTO_QUADRANTS_THRESHOLD), автоматически делает 4 зума.
        6. Возвращает список ViewportCrop.
        """
        # Используем настройки из config
        if max_side is None:
            max_side = config.PREVIEW_MAX_SIDE
        try:
            img_id = image_id or str(uuid.uuid5(uuid.NAMESPACE_URL, url))
            cache_path = self.temp_dir / f"{img_id}_full.png"
            img_bgr = None

            # 1. Пытаемся взять из кэша
            if cache_path.exists():
                img_bgr = cv2.imread(str(cache_path))
                if img_bgr is None:
                    logger.warning(f"Файл в кэше поврежден: {cache_path}")
            
            # 2. Если нет в кэше — скачиваем или читаем локально
            if img_bgr is None:
                # Проверяем, локальный ли это путь
                is_local = os.path.exists(url) or (len(url) > 2 and url[1] == ':')  # Windows путь
                # Определяем тип по расширению (и для локальных, и для http)
                try:
                    parsed = urlparse(url)
                    ext_source = parsed.path if parsed.scheme in ("http", "https") else url
                except Exception:
                    ext_source = url
                suffix = Path(ext_source).suffix.lower()
                is_image_file = suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")
                
                if is_local:
                    if is_image_file:
                        logger.info(f"Чтение локального изображения: {url}")
                        img_bgr = cv2.imread(str(url))
                        if img_bgr is None:
                            logger.error(f"Не удалось прочитать локальное изображение: {url}")
                            return []
                    else:
                        logger.info(f"Чтение локального PDF: {url}")
                        with fitz.open(url) as doc:
                            if doc.page_count == 0:
                                return []
                            page = doc[0]
                            pix = page.get_pixmap(dpi=200) 
                            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR) if pix.n >= 3 else cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
                else:
                    if is_image_file:
                        logger.info(f"Скачивание изображения: {url}")
                        response = requests.get(url, timeout=30)
                        response.raise_for_status()
                        data = np.frombuffer(response.content, dtype=np.uint8)
                        img_bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
                        if img_bgr is None:
                            logger.error(f"Не удалось декодировать изображение по URL: {url}")
                            return []
                    else:
                        logger.info(f"Скачивание PDF: {url}")
                        response = requests.get(url, timeout=30)
                        response.raise_for_status()
                        
                        with fitz.open(stream=response.content, filetype="pdf") as doc:
                            if doc.page_count == 0:
                                return []
                            page = doc[0]
                            pix = page.get_pixmap(dpi=200) 
                            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR) if pix.n >= 3 else cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
                
                # Сохраняем оригинал
                cv2.imwrite(str(cache_path), img_bgr)

            h, w = img_bgr.shape[:2]
            self._image_cache[img_id] = cache_path
            self._image_sizes[img_id] = (w, h)

            results = []

            # 3. Создаем базовое ПРЕВЬЮ
            scale = 1.0
            if max(h, w) > max_side:
                scale = max(h, w) / max_side
                new_w, new_h = int(w / scale), int(h / scale)
                preview_path = self.temp_dir / f"{img_id}_preview_{scale:.1f}x.png"
                if not preview_path.exists():
                    img_preview = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(str(preview_path), img_preview)
                
                desc = f"🖼️ OVERVIEW [ID: {img_id}]. ⚠️ SCALED PREVIEW ({scale:.1f}x): Original {w}x{h}px. Use Quadrant Zooms (TL, TR, BL, BR) for details."
                img_path = preview_path
            else:
                desc = f"✓ FULL RESOLUTION IMAGE [ID: {img_id}]: {w}x{h}px"
                img_path = cache_path

            results.append(ViewportCrop(
                page_number=0,
                crop_coords=(0, 0, w, h),
                image_path=str(img_path),
                description=desc,
                target_blocks=[img_id],
            ))

            # 4. АВТОМАТИЧЕСКИЕ ЗУМЫ (если factor > порога из config)
            if scale > config.AUTO_QUADRANTS_THRESHOLD:
                logger.info(f"Auto-quadrants: scale={scale:.2f} > threshold={config.AUTO_QUADRANTS_THRESHOLD}")
                # [y1, x1, y2, x2] в нормализованных координатах
                quadrants = [
                    ([0.0, 0.0, 0.55, 0.55], "1_TL", "Top-Left"),
                    ([0.0, 0.45, 0.55, 1.0], "2_TR", "Top-Right"),
                    ([0.45, 0.0, 1.0, 0.55], "3_BL", "Bottom-Left"),
                    ([0.45, 0.45, 1.0, 1.0], "4_BR", "Bottom-Right"),
                ]
                
                # Исправляем координаты (в вашем запросе было: 1-TL, 2-TR, 3-BL, 4-BR)
                # Координаты в ZoomRequest: [x1, y1, x2, y2]
                quadrants = [
                    ([0.0, 0.0, 0.55, 0.55], "1_TL", "Top-Left Quadrant (High Res)"),
                    ([0.45, 0.0, 1.0, 0.55], "2_TR", "Top-Right Quadrant (High Res)"),
                    ([0.0, 0.45, 0.55, 1.0], "3_BL", "Bottom-Left Quadrant (High Res)"),
                    ([0.45, 0.45, 1.0, 1.0], "4_BR", "Bottom-Right Quadrant (High Res)"),
                ]

                for coords, suffix, label in quadrants:
                    nx1, ny1, nx2, ny2 = coords
                    x1, y1 = int(nx1 * w), int(ny1 * h)
                    x2, y2 = int(nx2 * w), int(ny2 * h)
                    
                    crop = img_bgr[y1:y2, x1:x2]
                    
                    # Ресайз кропа если он все еще огромный (больше ZOOM_PREVIEW_MAX_SIDE)
                    ch, cw = crop.shape[:2]
                    crop_scale = 1.0
                    zoom_max = config.ZOOM_PREVIEW_MAX_SIDE
                    if max(ch, cw) > zoom_max:
                        crop_scale = max(ch, cw) / zoom_max
                        crop = cv2.resize(crop, (int(cw/crop_scale), int(ch/crop_scale)), interpolation=cv2.INTER_AREA)

                    q_filename = f"{img_id}_autozoom_{suffix}.png"
                    q_path = self.temp_dir / q_filename
                    cv2.imwrite(str(q_path), crop)
                    
                    q_desc = f"🔍 QUADRANT {label} [ID: {img_id}]. Original crop {cw}x{ch}px."
                    if crop_scale > 1.0:
                        q_desc += f" ⚠️ Still scaled {crop_scale:.1f}x. Request deeper ZOOM if needed."

                    results.append(ViewportCrop(
                        page_number=0,
                        crop_coords=(x1, y1, x2, y2),
                        image_path=str(q_path),
                        description=q_desc,
                        target_blocks=[img_id],
                        is_zoom_request=True
                    ))

            return results

        except Exception as e:
            logger.error(f"Ошибка обработки PDF {url}: {e}")
            return []
                
        except Exception as e:
            logger.error(f"Ошибка обработки PDF {url}: {e}")
            return None

    def process_zoom_request(self, request: ZoomRequest, output_path: Optional[Path] = None) -> Optional[ViewportCrop]:
        """
        Вырезает зум из кэшированного оригинала (по ID).
        """
        # ID картинки передается через поле 'page_number' в ZoomRequest? 
        # Нет, page_number - это int. Нам нужно передать ID картинки.
        # В ZoomRequest нам нужно добавить поле `image_id` (строка).
        
        # Если image_id нет в запросе (старый формат), пробуем найти по page_number (если это локальная страница)
        # Но для внешней ссылки LLM должна вернуть image_id, который мы ей сообщим.
        
        # ВРЕМЕННОЕ РЕШЕНИЕ:
        # Мы будем говорить LLM: "Image ID: <uuid>". И просить вернуть этот ID в ZoomRequest.
        
        img_id = getattr(request, "image_id", None)
        
        img = None
        if img_id and img_id in self._image_cache:
            # Загружаем из кэша
            path = self._image_cache[img_id]
            img = cv2.imread(str(path))
        elif img_id and getattr(request, "source_path", None):
            # Если кэш не прогрет, пробуем загрузить исходник напрямую из source_path (локальный файл)
            try:
                sp = str(getattr(request, "source_path"))
                if sp and os.path.exists(sp):
                    img = cv2.imread(sp)
                    if img is not None:
                        # Кладем в кэш под image_id, чтобы дальше все работало по ID
                        cache_path = self.temp_dir / f"{img_id}_full.png"
                        cv2.imwrite(str(cache_path), img)
                        h, w = img.shape[:2]
                        self._image_cache[img_id] = cache_path
                        self._image_sizes[img_id] = (w, h)
            except Exception as e:
                logger.warning(f"Не удалось загрузить source_path для zoom: {e}")
        elif isinstance(request.page_number, int):
             # Локальная страница
             img = self.load_local_page(request.page_number)
             
        if img is None:
            logger.error(f"Не найдено изображение для зума: ID={img_id}, Page={request.page_number}")
            return None
            
        h_full, w_full = img.shape[:2]
        
        # Координаты
        if request.coords_px:
            x1, y1, x2, y2 = request.coords_px
        elif request.coords_norm:
            nx1, ny1, nx2, ny2 = request.coords_norm
            
            # Правило расширения ROI у краёв (15%):
            # Если координата ближе 15% к краю — расширяем до 0.0 или 1.0
            EDGE_THRESHOLD = 0.15
            if nx1 < EDGE_THRESHOLD:
                nx1 = 0.0
            if ny1 < EDGE_THRESHOLD:
                ny1 = 0.0
            if nx2 > (1.0 - EDGE_THRESHOLD):
                nx2 = 1.0
            if ny2 > (1.0 - EDGE_THRESHOLD):
                ny2 = 1.0
            
            x1 = int(nx1 * w_full)
            y1 = int(ny1 * h_full)
            x2 = int(nx2 * w_full)
            y2 = int(ny2 * h_full)
            
            logger.info(f"Zoom ROI: norm=[{nx1:.2f},{ny1:.2f},{nx2:.2f},{ny2:.2f}] → px=[{x1},{y1},{x2},{y2}]")
        else:
            return None
            
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_full, x2), min(h_full, y2)
        
        if x2 <= x1 or y2 <= y1:
            return None
            
        crop = img[y1:y2, x1:x2]
        
        # Ресайз кропа если огромный (больше ZOOM_PREVIEW_MAX_SIDE)
        h_c, w_c = crop.shape[:2]
        was_scaled = False
        scale_val = 1.0
        zoom_max = config.ZOOM_PREVIEW_MAX_SIDE
        if max(h_c, w_c) > zoom_max:
            scale_val = max(h_c, w_c) / zoom_max
            crop = cv2.resize(crop, (int(w_c/scale_val), int(h_c/scale_val)))
            was_scaled = True
            logger.info(f"Zoom scaled: {w_c}x{h_c} → {int(w_c/scale_val)}x{int(h_c/scale_val)} (factor {scale_val:.2f})")
            
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), crop)
            
        desc = f"Zoom {x1},{y1}-{x2},{y2}"
        if was_scaled:
            h_new, w_new = crop.shape[:2]
            repeat_hint = ""
            if config.FORCE_REPEAT_ZOOM_IF_SCALED:
                repeat_hint = " **MUST request deeper ZOOM for accurate analysis.**"
            desc = f"⚠️ ZOOM PREVIEW (factor {scale_val:.1f}x): Crop {w_c}x{h_c}px → Scaled to {w_new}x{h_new}px.{repeat_hint}"

        return ViewportCrop(
            page_number=request.page_number,
            crop_coords=(x1, y1, x2, y2),
            image_path=str(output_path),
            description=desc,
            target_blocks=[img_id] if img_id else [],
            is_zoom_request=True
        )
