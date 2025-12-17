"""
Модели данных для работы с аннотациями, блоками и результатами поиска.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum


class BlockType(Enum):
    """Типы блоков в документе."""
    TEXT = "text"
    TABLE = "table"
    OTHER = "other"


class BlockSource(Enum):
    """Источник создания блока."""
    USER = "user"
    AUTO = "auto"


@dataclass
class Block:
    """Блок из annotation.json с геометрическими координатами."""
    id: str
    page_index: int
    coords_px: List[int]  # [x1, y1, x2, y2]
    coords_norm: List[float]  # Нормализованные координаты
    block_type: BlockType
    source: BlockSource
    shape_type: str
    image_file: Optional[str] = None
    ocr_text: Optional[str] = None
    
    @property
    def x1(self) -> int:
        return self.coords_px[0]
    
    @property
    def y1(self) -> int:
        return self.coords_px[1]
    
    @property
    def x2(self) -> int:
        return self.coords_px[2]
    
    @property
    def y2(self) -> int:
        return self.coords_px[3]
    
    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2
    
    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2
    
    @property
    def width(self) -> int:
        return self.x2 - self.x1
    
    @property
    def height(self) -> int:
        return self.y2 - self.y1
    
    def is_small_annotation(self, page_width: int, page_height: int, threshold: float = 0.2) -> bool:
        """
        Определяет, является ли блок небольшой надписью на чертеже.
        
        Args:
            page_width: Ширина страницы в пикселях
            page_height: Высота страницы в пикселях
            threshold: Порог относительного размера (по умолчанию 20%)
        
        Returns:
            True если блок считается надписью на чертеже (приоритет ИЗОБРАЖЕНИЮ)
        """
        rel_width = self.width / page_width
        rel_height = self.height / page_height
        return rel_width < threshold and rel_height < threshold


@dataclass
class Page:
    """Страница документа с блоками."""
    page_number: int
    width: int
    height: int
    blocks: List[Block] = field(default_factory=list)
    
    def get_block_by_id(self, block_id: str) -> Optional[Block]:
        """Получить блок по ID."""
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None


@dataclass
class AnnotationData:
    """Данные из annotation.json."""
    pdf_path: str
    pages: List[Page]
    
    def get_page(self, page_number: int) -> Optional[Page]:
        """Получить страницу по номеру."""
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None
    
    def get_block_by_id(self, block_id: str) -> Optional[Tuple[Page, Block]]:
        """
        Найти блок по ID во всех страницах.
        
        Returns:
            Кортеж (Page, Block) или None если не найден
        """
        for page in self.pages:
            block = page.get_block_by_id(block_id)
            if block:
                return (page, block)
        return None


@dataclass
class MarkdownBlock:
    """Блок текста из result.md с опциональной привязкой к геометрии."""
    text: str
    block_id: Optional[str] = None
    section_context: List[str] = field(default_factory=list)  # Иерархия заголовков
    page_hint: Optional[int] = None  # Подсказка о номере страницы если доступна
    
    def has_geometry_link(self) -> bool:
        """Проверяет наличие связи с геометрией через block_id."""
        return self.block_id is not None


@dataclass
class ViewportCrop:
    """
    Viewport-кроп изображения с контекстным окном вокруг блока(ов).
    """
    page_number: int
    crop_coords: Tuple[int, int, int, int]  # (x1, y1, x2, y2) в координатах страницы
    target_blocks: List[str]  # IDs блоков, которые находятся в этом viewport
    image_path: Optional[str] = None  # Путь к сохранённому кропу
    description: str = ""  # Человекочитаемое описание для промта


@dataclass
class SearchResult:
    """Результат поиска релевантной информации."""
    text_blocks: List[MarkdownBlock] = field(default_factory=list)
    viewport_crops: List[ViewportCrop] = field(default_factory=list)
    relevant_pages: List[int] = field(default_factory=list)
    
    def is_empty(self) -> bool:
        """Проверяет, пуст ли результат поиска."""
        return len(self.text_blocks) == 0 and len(self.viewport_crops) == 0


@dataclass
class ComparisonContext:
    """Контекст для сравнения двух стадий проектирования."""
    stage_p_results: SearchResult
    stage_r_results: SearchResult
    comparison_query: str

