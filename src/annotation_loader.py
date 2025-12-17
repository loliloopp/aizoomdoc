"""
Загрузка и парсинг annotation.json.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .models import (
    AnnotationData,
    Block,
    BlockSource,
    BlockType,
    Page,
)

logger = logging.getLogger(__name__)


class AnnotationLoader:
    """Загрузчик и парсер annotation.json."""
    
    @staticmethod
    def load(annotation_path: Path) -> AnnotationData:
        """
        Загружает и парсит annotation.json.
        
        Args:
            annotation_path: Путь к файлу annotation.json
        
        Returns:
            Объект AnnotationData
        
        Raises:
            FileNotFoundError: Если файл не найден
            ValueError: Если JSON невалиден
        """
        if not annotation_path.exists():
            raise FileNotFoundError(f"Файл аннотаций не найден: {annotation_path}")
        
        logger.info(f"Загрузка аннотаций из {annotation_path}")
        
        try:
            with open(annotation_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка парсинга JSON: {e}")
        
        return AnnotationLoader._parse_annotation_data(data)
    
    @staticmethod
    def _parse_annotation_data(data: dict) -> AnnotationData:
        """Парсит словарь в структуры данных."""
        pdf_path = data.get("pdf_path", "")
        pages_data = data.get("pages", [])
        
        pages = []
        for page_data in pages_data:
            page = AnnotationLoader._parse_page(page_data)
            pages.append(page)
        
        logger.info(f"Загружено {len(pages)} страниц из аннотаций")
        return AnnotationData(pdf_path=pdf_path, pages=pages)
    
    @staticmethod
    def _parse_page(page_data: dict) -> Page:
        """Парсит данные страницы."""
        page_number = page_data.get("page_number", 0)
        width = page_data.get("width", 0)
        height = page_data.get("height", 0)
        blocks_data = page_data.get("blocks", [])
        
        blocks = []
        for block_data in blocks_data:
            block = AnnotationLoader._parse_block(block_data)
            blocks.append(block)
        
        logger.debug(
            f"Страница {page_number}: размер {width}x{height}, "
            f"блоков: {len(blocks)}"
        )
        
        return Page(
            page_number=page_number,
            width=width,
            height=height,
            blocks=blocks
        )
    
    @staticmethod
    def _parse_block(block_data: dict) -> Block:
        """Парсит данные блока."""
        # Парсинг типа блока
        block_type_str = block_data.get("block_type", "other")
        try:
            block_type = BlockType(block_type_str)
        except ValueError:
            logger.warning(f"Неизвестный тип блока: {block_type_str}, использую OTHER")
            block_type = BlockType.OTHER
        
        # Парсинг источника
        source_str = block_data.get("source", "auto")
        try:
            source = BlockSource(source_str)
        except ValueError:
            logger.warning(f"Неизвестный источник блока: {source_str}, использую AUTO")
            source = BlockSource.AUTO
        
        return Block(
            id=block_data.get("id", ""),
            page_index=block_data.get("page_index", 0),
            coords_px=block_data.get("coords_px", [0, 0, 0, 0]),
            coords_norm=block_data.get("coords_norm", [0.0, 0.0, 0.0, 0.0]),
            block_type=block_type,
            source=source,
            shape_type=block_data.get("shape_type", "rectangle"),
            image_file=block_data.get("image_file"),
            ocr_text=block_data.get("ocr_text"),
        )
    
    @staticmethod
    def find_blocks_by_text(
        annotation: AnnotationData,
        search_text: str,
        case_sensitive: bool = False
    ) -> list[tuple[Page, Block]]:
        """
        Находит все блоки, содержащие указанный текст в ocr_text.
        
        Args:
            annotation: Данные аннотаций
            search_text: Текст для поиска
            case_sensitive: Учитывать регистр
        
        Returns:
            Список кортежей (Page, Block)
        """
        results = []
        
        if not case_sensitive:
            search_text = search_text.lower()
        
        for page in annotation.pages:
            for block in page.blocks:
                if block.ocr_text:
                    text = block.ocr_text if case_sensitive else block.ocr_text.lower()
                    if search_text in text:
                        results.append((page, block))
        
        logger.debug(
            f"Найдено {len(results)} блоков с текстом '{search_text}'"
        )
        return results

