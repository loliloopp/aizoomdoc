"""
Обработка изображений: ресайз, кроп, загрузка PDF с S3 и подготовка для LLM.
"""

import logging
import io
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import cv2
import numpy as np
import requests
import fitz  # PyMuPDF

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
        max_side: int = 2000,
        image_id: Optional[str] = None,
    ) -> Optional[ViewportCrop]:
        """
        1. Скачивает PDF по ссылке.
        2. Рендерит первую страницу в полном разрешении.
        3. Сохраняет оригинал в кэш.
        4. Создает превью (max_side) для отправки в LLM.
        5. Возвращает ViewportCrop с путем к превью и метаданными.
        """
        try:
            # Стабильный ID (если задан) позволяет:
            # - не тащить длинные URL в промты
            # - переиспользовать уже скачанные изображения в длинном диалоге
            img_id = image_id or str(uuid.uuid5(uuid.NAMESPACE_URL, url))
            cache_path = self.temp_dir / f"{img_id}_full.png"

            # Если уже есть кэш на диске — не скачиваем заново.
            if cache_path.exists():
                img_bgr = cv2.imread(str(cache_path))
                if img_bgr is not None:
                    h, w = img_bgr.shape[:2]
                    self._image_cache[img_id] = cache_path
                    self._image_sizes[img_id] = (w, h)

                    if max(h, w) > max_side:
                        scale = max(h, w) / max_side
                        new_w, new_h = int(w / scale), int(h / scale)
                        preview_path = self.temp_dir / f"{img_id}_preview_{scale:.1f}.png"
                        
                        if not preview_path.exists():
                            img_preview = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
                            cv2.imwrite(str(preview_path), img_preview)
                        
                        desc = f"⚠️ SCALED PREVIEW (factor {scale:.1f}x): Original {w}x{h}px → Scaled to {new_w}x{new_h}px. Use ZOOM to verify details."
                        img_path = preview_path
                    else:
                        desc = f"✓ CACHED FULL RESOLUTION IMAGE: {w}x{h}px"
                        img_path = cache_path

                    return ViewportCrop(
                        page_number=0,
                        crop_coords=(0, 0, w, h),
                        image_path=str(img_path),
                        description=desc,
                        target_blocks=[img_id],
                    )

            logger.info(f"Скачивание PDF: {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            pdf_data = response.content
            
            # Открываем PDF
            with fitz.open(stream=pdf_data, filetype="pdf") as doc:
                if doc.page_count == 0:
                    logger.warning("PDF пустой")
                    return None
                    
                page = doc[0] # Берем первую страницу кропа
                
                # Рендерим в высоком качестве (zoom=2 для четкости, если вектор)
                # Но если там растр, то лучше брать нативное разрешение.
                # Для универсальности берем dpi=150-200
                pix = page.get_pixmap(dpi=200) 
                
                # Конвертируем в numpy (OpenCV format)
                # Pixmap.samples - это байты RGB
                img_array = np.frombuffer(pix.samples, dtype=np.uint8)
                img_array = img_array.reshape(pix.height, pix.width, pix.n)
                
                # PyMuPDF дает RGB, OpenCV ждет BGR
                if pix.n >= 3:
                    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                else:
                    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
                
                h, w = img_bgr.shape[:2]
                
                # img_id уже вычислен выше (для возможности дискового кэша)
                
                # Сохраняем ОРИГИНАЛ в кэш
                # cache_path уже вычислен выше
                if not cache_path.exists():
                    cv2.imwrite(str(cache_path), img_bgr)
                self._image_cache[img_id] = cache_path
                self._image_sizes[img_id] = (w, h)
                
                # Создаем ПРЕВЬЮ только если изображение больше max_side
                if max(h, w) > max_side:
                    # Изображение большое - создаем уменьшенный preview
                    scale = max(h, w) / max_side
                    new_w, new_h = int(w / scale), int(h / scale)
                    img_preview = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    desc = f"⚠️ SCALED PREVIEW (factor {scale:.1f}x): Original {w}x{h}px → Scaled to {new_w}x{new_h}px. Use ZOOM to verify details."
                    
                    # Сохраняем preview в PNG с коэффициентом в названии
                    preview_path = self.temp_dir / f"{img_id}_preview_{scale:.1f}.png"
                    if not preview_path.exists():
                        cv2.imwrite(str(preview_path), img_preview)
                else:
                    # Изображение маленькое - используем оригинал напрямую, preview не создаем
                    preview_path = cache_path  # Используем full.png
                    desc = f"✓ FULL RESOLUTION IMAGE: {w}x{h}px (no scaling applied)"
                
                return ViewportCrop(
                    page_number=0, # Неактуально для внешних ссылок
                    crop_coords=(0, 0, w, h),
                    image_path=str(preview_path),
                    description=desc,
                    target_blocks=[img_id] # Используем поле target_blocks для хранения ID
                )
                
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
            x1 = int(nx1 * w_full)
            y1 = int(ny1 * h_full)
            x2 = int(nx2 * w_full)
            y2 = int(ny2 * h_full)
        else:
            return None
            
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_full, x2), min(h_full, y2)
        
        if x2 <= x1 or y2 <= y1:
            return None
            
        crop = img[y1:y2, x1:x2]
        
        # Ресайз кропа если огромный
        h_c, w_c = crop.shape[:2]
        was_scaled = False
        scale_val = 1.0
        if max(h_c, w_c) > 2000:
            scale_val = max(h_c, w_c) / 2000
            crop = cv2.resize(crop, (int(w_c/scale_val), int(h_c/scale_val)))
            was_scaled = True
            
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), crop)
            
        desc = f"Zoom {x1},{y1}-{x2},{y2}"
        if was_scaled:
            h_new, w_new = crop.shape[:2]
            desc = f"⚠️ ZOOM PREVIEW (factor {scale_val:.1f}x): Crop {w_c}x{h_c}px → Scaled to {w_new}x{h_new}px. If details are not clear, request ZOOM again inside this area."

        return ViewportCrop(
            page_number=request.page_number,
            crop_coords=(x1, y1, x2, y2),
            image_path=str(output_path),
            description=desc,
            is_zoom_request=True
        )
