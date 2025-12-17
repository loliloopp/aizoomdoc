"""
Поисковый движок для нахождения релевантной информации в документах.
Версия 1: простой поиск на основе ключевых слов и правил.
"""

import logging
from pathlib import Path
from typing import List, Optional, Set

from .annotation_loader import AnnotationLoader
from .config import config
from .image_processor import ImageProcessor
from .markdown_parser import MarkdownParser
from .models import (
    AnnotationData,
    Block,
    ComparisonContext,
    MarkdownBlock,
    Page,
    SearchResult,
    ViewportCrop,
)

logger = logging.getLogger(__name__)


class SearchEngine:
    """Поисковый движок для строительной документации."""
    
    # Ключевые слова для различных категорий поиска
    VENTILATION_KEYWORDS = [
        "вентиляция", "вентилятор", "аов", "приточ", "вытяж",
        "воздух", "установка", "приточная", "вытяжная", "овк",
        "ов", "отопление и вентиляция", "климат"
    ]
    
    SPECIFICATION_SECTION_KEYWORDS = [
        "спецификация", "ведомость", "экспликация", "перечень",
        "таблица", "оборудование"
    ]
    
    def __init__(
        self,
        data_root: Path,
        output_dir: Optional[Path] = None
    ):
        """
        Инициализирует поисковый движок.
        
        Args:
            data_root: Корневая папка с данными (result.md, annotation.json, images)
            output_dir: Директория для сохранения viewport-кропов
        """
        self.data_root = data_root
        self.output_dir = output_dir or (data_root / "viewports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Загружаем данные
        markdown_path, annotation_path = config.get_document_paths(data_root)
        
        self.markdown_parser = MarkdownParser(markdown_path)
        self.annotation_data = AnnotationLoader.load(annotation_path)
        self.image_processor = ImageProcessor(data_root)
        
        logger.info(f"SearchEngine инициализирован для {data_root}")
    
    def find_ventilation_equipment(
        self,
        query: str
    ) -> SearchResult:
        """
        Находит всё вентиляционное оборудование в документах.
        
        Args:
            query: Пользовательский запрос
        
        Returns:
            SearchResult с текстовыми блоками и viewport-кропами
        """
        logger.info(f"Поиск вентиляционного оборудования: {query}")
        
        result = SearchResult()
        
        # 1. Поиск в секциях спецификаций
        spec_blocks = self._find_specification_sections(self.VENTILATION_KEYWORDS)
        result.text_blocks.extend(spec_blocks)
        
        # 2. Поиск по ключевым словам в тексте
        for keyword in self.VENTILATION_KEYWORDS:
            blocks = self.markdown_parser.get_blocks_by_keyword(keyword)
            for block in blocks:
                if block not in result.text_blocks:
                    result.text_blocks.append(block)
        
        # 3. Извлекаем номера страниц и block_id из найденных текстовых блоков
        block_ids = set()
        pages_dict = {}
        
        for md_block in result.text_blocks:
            if md_block.block_id:
                block_ids.add(md_block.block_id)
        
        # 4. Получаем соответствующие блоки из аннотаций
        for block_id in block_ids:
            page_block = self.annotation_data.get_block_by_id(block_id)
            if page_block:
                page, block = page_block
                if page.page_number not in pages_dict:
                    pages_dict[page.page_number] = []
                pages_dict[page.page_number].append(block)
        
        # 5. Создаём viewport-кропы
        for page_num, blocks in pages_dict.items():
            page = self.annotation_data.get_page(page_num)
            if page:
                # Фильтруем блоки: маленькие -> изображения, большие -> только текст
                image_blocks = [
                    b for b in blocks 
                    if b.is_small_annotation(page.width, page.height)
                ]
                
                if image_blocks:
                    viewports = self.image_processor.create_viewports_for_blocks(
                        page=page,
                        blocks=image_blocks,
                        output_dir=self.output_dir,
                        cluster=True
                    )
                    result.viewport_crops.extend(viewports)
                    result.relevant_pages.append(page_num)
        
        # Убираем дубликаты страниц
        result.relevant_pages = sorted(list(set(result.relevant_pages)))
        
        logger.info(
            f"Найдено: текстовых блоков={len(result.text_blocks)}, "
            f"viewport-кропов={len(result.viewport_crops)}, "
            f"страниц={len(result.relevant_pages)}"
        )
        
        return result
    
    def prepare_comparison(
        self,
        other_engine: 'SearchEngine',
        query: str
    ) -> ComparisonContext:
        """
        Подготавливает контекст для сравнения двух стадий проектирования.
        
        Args:
            other_engine: SearchEngine для второй стадии
            query: Пользовательский запрос
        
        Returns:
            ComparisonContext с результатами для обеих стадий
        """
        logger.info(f"Подготовка сравнения двух стадий: {query}")
        
        # Ищем в обеих стадиях
        stage_p_results = self.find_ventilation_equipment(query)
        stage_r_results = other_engine.find_ventilation_equipment(query)
        
        context = ComparisonContext(
            stage_p_results=stage_p_results,
            stage_r_results=stage_r_results,
            comparison_query=query
        )
        
        return context
    
    def _find_specification_sections(
        self,
        keywords: List[str]
    ) -> List[MarkdownBlock]:
        """
        Находит разделы спецификаций, содержащие указанные ключевые слова.
        
        Args:
            keywords: Список ключевых слов для поиска
        
        Returns:
            Список MarkdownBlock из релевантных секций
        """
        results = []
        
        # Ищем блоки в секциях со словами "спецификация", "ведомость" и т.п.
        for section_kw in self.SPECIFICATION_SECTION_KEYWORDS:
            section_blocks = self.markdown_parser.get_blocks_in_section(section_kw)
            
            # Фильтруем блоки, которые также содержат целевые ключевые слова
            for block in section_blocks:
                text_lower = block.text.lower()
                if any(kw in text_lower for kw in keywords):
                    if block not in results:
                        results.append(block)
        
        return results
    
    def search_by_keywords(
        self,
        keywords: List[str],
        include_images: bool = True
    ) -> SearchResult:
        """
        Универсальный поиск по ключевым словам.
        
        Args:
            keywords: Список ключевых слов
            include_images: Включать ли viewport-кропы изображений
        
        Returns:
            SearchResult
        """
        logger.info(f"Поиск по ключевым словам: {keywords}")
        
        result = SearchResult()
        
        # Поиск в Markdown
        for keyword in keywords:
            blocks = self.markdown_parser.get_blocks_by_keyword(keyword)
            for block in blocks:
                if block not in result.text_blocks:
                    result.text_blocks.append(block)
        
        if not include_images:
            return result
        
        # Создаём viewport-кропы для блоков с геометрией
        block_ids = set()
        for md_block in result.text_blocks:
            if md_block.block_id:
                block_ids.add(md_block.block_id)
        
        pages_dict = {}
        for block_id in block_ids:
            page_block = self.annotation_data.get_block_by_id(block_id)
            if page_block:
                page, block = page_block
                if page.page_number not in pages_dict:
                    pages_dict[page.page_number] = []
                pages_dict[page.page_number].append(block)
        
        for page_num, blocks in pages_dict.items():
            page = self.annotation_data.get_page(page_num)
            if page:
                # Создаём viewport только для маленьких блоков (надписи)
                image_blocks = [
                    b for b in blocks 
                    if b.is_small_annotation(page.width, page.height)
                ]
                
                if image_blocks:
                    viewports = self.image_processor.create_viewports_for_blocks(
                        page=page,
                        blocks=image_blocks,
                        output_dir=self.output_dir,
                        cluster=True
                    )
                    result.viewport_crops.extend(viewports)
                    result.relevant_pages.append(page_num)
        
        result.relevant_pages = sorted(list(set(result.relevant_pages)))
        
        return result

