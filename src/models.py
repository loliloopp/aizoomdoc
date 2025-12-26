"""
Модели данных.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any, Dict
from enum import Enum

class BlockType(Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    OTHER = "other"

class BlockSource(Enum):
    USER = "user"
    AUTO = "auto"

@dataclass
class Block:
    id: str
    page_index: int
    coords_px: List[int]
    coords_norm: List[float]
    block_type: BlockType
    source: BlockSource
    shape_type: str
    image_file: Optional[str] = None
    ocr_text: Optional[str] = None
    
    @property
    def x1(self) -> int: return self.coords_px[0]
    @property
    def y1(self) -> int: return self.coords_px[1]
    @property
    def x2(self) -> int: return self.coords_px[2]
    @property
    def y2(self) -> int: return self.coords_px[3]
    @property
    def width(self) -> int: return self.x2 - self.x1
    @property
    def height(self) -> int: return self.y2 - self.y1
    @property
    def center_x(self) -> float: return (self.x1 + self.x2) / 2
    @property
    def center_y(self) -> float: return (self.y1 + self.y2) / 2
    
    def is_small_annotation(self, page_width: int, page_height: int, threshold: float = 0.2) -> bool:
        rel_width = self.width / page_width
        rel_height = self.height / page_height
        return rel_width < threshold and rel_height < threshold

@dataclass
class Page:
    page_number: int
    width: int
    height: int
    blocks: List[Block] = field(default_factory=list)
    image_path: Optional[str] = None
    
    def get_block_by_id(self, block_id: str) -> Optional[Block]:
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
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None
    
    def get_block_by_id(self, block_id: str) -> Optional[Tuple[Page, Block]]:
        for page in self.pages:
            block = page.get_block_by_id(block_id)
            if block:
                return (page, block)
        return None

@dataclass
class ExternalLink:
    url: str
    description: str
    block_id: Optional[str] = None

@dataclass
class ZoomRequest:
    """Запрос от LLM на увеличение."""
    page_number: int # Или 0 если внешний
    image_id: Optional[str] = None # ID внешней картинки (если есть)
    coords_norm: Optional[List[float]] = None
    coords_px: Optional[List[int]] = None
    reason: str = ""


@dataclass
class ImageRequest:
    """Запрос от LLM на подгрузку изображений по их коротким ID."""
    image_ids: List[str] = field(default_factory=list)
    reason: str = ""

@dataclass
class DocumentRequest:
    """Запрос от LLM на подгрузку дополнительной документации."""
    documents: List[str] = field(default_factory=list)
    reason: str = ""

@dataclass
class MarkdownBlock:
    text: str
    block_id: Optional[str] = None
    section_context: List[str] = field(default_factory=list)
    page_hint: Optional[int] = None
    external_links: List[ExternalLink] = field(default_factory=list)

@dataclass
class ViewportCrop:
    page_number: int
    crop_coords: Tuple[int, int, int, int]
    image_path: Optional[str]
    description: str
    target_blocks: List[str] = field(default_factory=list) # Здесь храним ID изображения для внешних ссылок
    is_zoom_request: bool = False

@dataclass
class SearchResult:
    text_blocks: List[MarkdownBlock] = field(default_factory=list)
    relevant_pages: List[Page] = field(default_factory=list)
    initial_images: List[ViewportCrop] = field(default_factory=list)
    viewport_crops: List[ViewportCrop] = field(default_factory=list)
    
    def is_empty(self) -> bool:
        return not self.text_blocks and not self.relevant_pages

@dataclass
class ImageSelection:
    """Выбор картинок от LLM."""
    reasoning: str # Почему выбраны эти картинки
    image_urls: List[str]
    needs_images: bool # Нужны ли вообще картинки

@dataclass
class ComparisonContext:
    stage_p_results: SearchResult
    stage_r_results: SearchResult
    comparison_query: str
