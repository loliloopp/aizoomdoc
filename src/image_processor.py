"""
Обработка изображений: динамический контекстный кроп (viewport strategy)
с опциональной визуальной подсветкой блоков.
"""

import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .config import config
from .models import Block, Page, ViewportCrop

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Обработчик изображений с поддержкой динамического viewport-кропа."""
    
    def __init__(self, images_root: Path):
        """
        Инициализирует процессор изображений.
        
        Args:
            images_root: Корневая папка с изображениями страниц
        """
        self.images_root = images_root
    
    def get_page_image_path(self, page_number: int) -> Path:
        """
        Получает путь к полноразмерному изображению страницы.
        
        Args:
            page_number: Номер страницы
        
        Returns:
            Путь к изображению (предполагается формат page_XXX_full.jpg)
        """
        # Формат имени файла: page_003_full.jpg
        filename = f"page_{page_number:03d}_full.jpg"
        return self.images_root / filename
    
    def load_page_image(self, page_number: int) -> Optional[np.ndarray]:
        """
        Загружает полноразмерное изображение страницы.
        
        Args:
            page_number: Номер страницы
        
        Returns:
            Изображение как numpy array (BGR) или None если не найдено
        """
        image_path = self.get_page_image_path(page_number)
        
        if not image_path.exists():
            logger.warning(f"Изображение страницы не найдено: {image_path}")
            return None
        
        logger.debug(f"Загрузка изображения страницы {page_number} из {image_path}")
        image = cv2.imread(str(image_path))
        
        if image is None:
            logger.error(f"Не удалось загрузить изображение: {image_path}")
            return None
        
        return image
    
    def create_viewport_crop(
        self,
        page: Page,
        blocks: List[Block],
        viewport_size: int = None,
        padding: int = None,
        highlight: bool = True,
        output_path: Optional[Path] = None
    ) -> Optional[ViewportCrop]:
        """
        Создаёт viewport-кроп вокруг одного или нескольких блоков.
        
        Args:
            page: Страница, содержащая блоки
            blocks: Список блоков для включения в viewport
            viewport_size: Размер viewport (если None, используется из config)
            padding: Паддинг вокруг блоков (если None, используется из config)
            highlight: Рисовать ли подсветку вокруг целевых блоков
            output_path: Путь для сохранения кропа (если None, не сохраняется)
        
        Returns:
            ViewportCrop объект или None при ошибке
        """
        if not blocks:
            logger.warning("Список блоков пуст, невозможно создать viewport")
            return None
        
        viewport_size = viewport_size or config.VIEWPORT_SIZE
        padding = padding or config.VIEWPORT_PADDING
        
        # Загружаем изображение страницы
        image = self.load_page_image(page.page_number)
        if image is None:
            return None
        
        page_height, page_width = image.shape[:2]
        
        # Вычисляем bounding box для всех блоков
        min_x = min(block.x1 for block in blocks)
        min_y = min(block.y1 for block in blocks)
        max_x = max(block.x2 for block in blocks)
        max_y = max(block.y2 for block in blocks)
        
        # Вычисляем центр всех блоков
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        # Определяем размер viewport с учётом паддинга
        blocks_width = max_x - min_x
        blocks_height = max_y - min_y
        
        # Viewport должен быть достаточно большим для блоков + паддинг
        required_width = blocks_width + 2 * padding
        required_height = blocks_height + 2 * padding
        
        # Используем максимум из требуемого размера и viewport_size
        viewport_width = max(viewport_size, int(required_width))
        viewport_height = max(viewport_size, int(required_height))
        
        # Вычисляем координаты viewport
        x1 = int(center_x - viewport_width / 2)
        y1 = int(center_y - viewport_height / 2)
        x2 = x1 + viewport_width
        y2 = y1 + viewport_height
        
        # Обрезаем по границам страницы
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(page_width, x2)
        y2 = min(page_height, y2)
        
        # Извлекаем кроп
        crop = image[y1:y2, x1:x2].copy()
        
        # Рисуем подсветку целевых блоков
        if highlight:
            for block in blocks:
                # Координаты блока относительно кропа
                rel_x1 = block.x1 - x1
                rel_y1 = block.y1 - y1
                rel_x2 = block.x2 - x1
                rel_y2 = block.y2 - y1
                
                # Рисуем прямоугольник
                cv2.rectangle(
                    crop,
                    (rel_x1, rel_y1),
                    (rel_x2, rel_y2),
                    config.HIGHLIGHT_COLOR_RGB[::-1],  # BGR для OpenCV
                    config.HIGHLIGHT_THICKNESS
                )
        
        # Сохраняем если указан путь
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), crop)
            logger.debug(f"Viewport сохранён: {output_path}")
        
        # Создаём описание
        block_ids = [block.id for block in blocks]
        description = (
            f"Страница {page.page_number}, viewport вокруг блоков: "
            f"{', '.join(block_ids[:3])}"
        )
        if len(block_ids) > 3:
            description += f" и ещё {len(block_ids) - 3}"
        
        viewport = ViewportCrop(
            page_number=page.page_number,
            crop_coords=(x1, y1, x2, y2),
            target_blocks=block_ids,
            image_path=str(output_path) if output_path else None,
            description=description
        )
        
        logger.info(
            f"Создан viewport для страницы {page.page_number}: "
            f"coords={viewport.crop_coords}, блоков={len(blocks)}"
        )
        
        return viewport
    
    def cluster_blocks(
        self,
        blocks: List[Block],
        distance_threshold: int = None
    ) -> List[List[Block]]:
        """
        Группирует близкие блоки в кластеры для создания общих viewport.
        
        Args:
            blocks: Список блоков для кластеризации
            distance_threshold: Порог расстояния в пикселях
        
        Returns:
            Список кластеров (каждый кластер - список блоков)
        """
        if not blocks:
            return []
        
        distance_threshold = distance_threshold or config.CLUSTERING_DISTANCE_THRESHOLD
        
        # Простая жадная кластеризация
        clusters: List[List[Block]] = []
        used = set()
        
        for i, block in enumerate(blocks):
            if i in used:
                continue
            
            cluster = [block]
            used.add(i)
            
            # Ищем близкие блоки
            for j, other_block in enumerate(blocks):
                if j in used:
                    continue
                
                # Вычисляем расстояние между центрами
                dist = math.sqrt(
                    (block.center_x - other_block.center_x) ** 2 +
                    (block.center_y - other_block.center_y) ** 2
                )
                
                if dist <= distance_threshold:
                    cluster.append(other_block)
                    used.add(j)
            
            clusters.append(cluster)
        
        logger.debug(
            f"Кластеризация: {len(blocks)} блоков -> {len(clusters)} кластеров"
        )
        
        return clusters
    
    def create_viewports_for_blocks(
        self,
        page: Page,
        blocks: List[Block],
        output_dir: Optional[Path] = None,
        cluster: bool = True
    ) -> List[ViewportCrop]:
        """
        Создаёт viewport-кропы для списка блоков с опциональной кластеризацией.
        
        Args:
            page: Страница
            blocks: Список блоков
            output_dir: Директория для сохранения кропов
            cluster: Группировать ли близкие блоки
        
        Returns:
            Список ViewportCrop объектов
        """
        if not blocks:
            return []
        
        viewports = []
        
        if cluster:
            # Группируем близкие блоки
            clusters = self.cluster_blocks(blocks)
        else:
            # Каждый блок - отдельный viewport
            clusters = [[block] for block in blocks]
        
        for idx, block_cluster in enumerate(clusters):
            output_path = None
            if output_dir:
                filename = f"viewport_page{page.page_number:03d}_{idx:02d}.jpg"
                output_path = output_dir / filename
            
            viewport = self.create_viewport_crop(
                page=page,
                blocks=block_cluster,
                output_path=output_path
            )
            
            if viewport:
                viewports.append(viewport)
        
        return viewports

