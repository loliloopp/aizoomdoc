"""
Модуль для парсинга result.md и извлечения информации.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional

from .models import MarkdownBlock, ExternalLink

logger = logging.getLogger(__name__)

# Паттерн для связанных блоков: →ID (Unicode стрелка U+2192)
LINKED_BLOCK_PATTERN = re.compile(r'^\u2192([A-Z0-9\-]+)$')


class MarkdownParser:
    """Парсер Markdown файлов с результатами OCR."""
    
    def __init__(self, file_path):
        """
        Args:
            file_path: str или Path - путь к .md файлу
        """
        self.file_path = Path(file_path) if isinstance(file_path, str) else file_path
        self._blocks_cache: Optional[List[MarkdownBlock]] = None
        
    def parse(self) -> List[MarkdownBlock]:
        """
        Парсит файл и возвращает список блоков.
        Кэширует результат.
        """
        if self._blocks_cache is not None:
            return self._blocks_cache
            
        if not self.file_path.exists():
            logger.error(f"Файл не найден: {self.file_path}")
            return []
            
        with open(self.file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        blocks: List[MarkdownBlock] = []
        current_section_stack: List[str] = []
        
        header_pattern = re.compile(r"^(#+)\s+(.+)$")
        # Паттерн для страницы: ## СТРАНИЦА X
        page_pattern = re.compile(r"^##\s+СТРАНИЦА\s+(\d+)", re.IGNORECASE)
        # Старый формат: <!-- BLOCK_ID: xxx -->
        block_id_start = re.compile(r"<!--\s*BLOCK_ID:\s*([a-f0-9-]+)\s*-->")
        block_id_end = re.compile(r"<!--\s*END_BLOCK\s*-->")
        # Новый формат: ### BLOCK [TEXT]: ID или ### BLOCK [IMAGE]: ID
        new_block_pattern = re.compile(r"^###\s+BLOCK\s+\[(TEXT|IMAGE)\]:\s*([A-Z0-9\-]+)")
        link_pattern = re.compile(r"(!?)\[([^\]]*)\]\((https?://[^)]+)\)") 
        
        lines = content.split("\n")
        current_text = []
        current_block_id = None
        current_block_type = None  # 'TEXT' или 'IMAGE'
        current_linked_ids = []  # Связанные блоки (→ID)
        current_page = None  # Текущая страница
        
        for line in lines:
            line_stripped = line.strip()
            
            # Проверяем новый формат блоков: ### BLOCK [TEXT/IMAGE]: ID
            new_block_match = new_block_pattern.match(line_stripped)
            if new_block_match:
                # Сохраняем предыдущий блок
                if current_text:
                    self._add_block(blocks, current_text, current_block_id, current_section_stack, link_pattern, current_block_type, current_linked_ids, current_page)
                    current_text = []
                    current_linked_ids = []
                
                current_block_type = new_block_match.group(1)  # TEXT или IMAGE
                current_block_id = new_block_match.group(2)
                continue
            
            # Проверяем связанный блок: →ID
            linked_match = LINKED_BLOCK_PATTERN.match(line_stripped)
            if linked_match:
                linked_id = linked_match.group(1)
                if linked_id not in current_linked_ids:
                    current_linked_ids.append(linked_id)
                continue  # Не добавляем в текст блока
            
            # Проверяем заголовок страницы: ## СТРАНИЦА X
            page_match = page_pattern.match(line_stripped)
            if page_match:
                # Сохраняем предыдущий блок перед сменой страницы
                if current_text:
                    self._add_block(blocks, current_text, current_block_id, current_section_stack, link_pattern, current_block_type, current_linked_ids, current_page)
                    current_text = []
                    current_block_id = None
                    current_block_type = None
                    current_linked_ids = []
                
                current_page = int(page_match.group(1))
                continue
            
            header_match = header_pattern.match(line_stripped)
            if header_match:
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                
                # Если это заголовок уровня 2 или выше - сохраняем блок
                if level <= 2:
                    if current_text:
                        self._add_block(blocks, current_text, current_block_id, current_section_stack, link_pattern, current_block_type, current_linked_ids, current_page)
                        current_text = []
                        current_block_id = None
                        current_block_type = None
                        current_linked_ids = []
                
                if len(current_section_stack) >= level:
                    current_section_stack = current_section_stack[:level-1]
                while len(current_section_stack) < level - 1:
                     current_section_stack.append("...")
                current_section_stack.append(title)
                continue
                
            id_match = block_id_start.match(line_stripped)
            if id_match:
                if current_text:
                    self._add_block(blocks, current_text, current_block_id, current_section_stack, link_pattern, current_block_type, current_linked_ids, current_page)
                    current_text = []
                    current_linked_ids = []
                current_block_id = id_match.group(1)
                current_block_type = None
                continue
                
            if block_id_end.match(line_stripped):
                if current_text:
                    self._add_block(blocks, current_text, current_block_id, current_section_stack, link_pattern, current_block_type, current_linked_ids, current_page)
                    current_text = []
                    current_block_id = None
                    current_block_type = None
                    current_linked_ids = []
                continue
            
            if line_stripped:
                current_text.append(line_stripped)
        
        if current_text:
            self._add_block(blocks, current_text, current_block_id, current_section_stack, link_pattern, current_block_type, current_linked_ids, current_page)
            
        self._blocks_cache = blocks
        return blocks

    def _add_block(self, blocks, text_lines, block_id, sections, link_pattern, block_type=None, linked_ids=None, page=None):
        full_text = "\n".join(text_lines)
        links = []
        
        # Специальная логика для блоков с "*Изображение:*"
        # Если блок содержит "*Изображение:*", ищем только ссылки ПОСЛЕ этого маркера
        if "*Изображение:*" in full_text:
            # Найдем позицию маркера
            marker_pos = full_text.find("*Изображение:*")
            if marker_pos != -1:
                # Берем только текст после маркера
                text_after_marker = full_text[marker_pos:]
                # Ищем ссылки только после маркера
                for match in link_pattern.finditer(text_after_marker):
                    is_image = match.group(1) == "!"
                    alt_text = match.group(2)
                    url = match.group(3)
                    links.append(ExternalLink(
                        url=url,
                        description=f"{'Image: ' if is_image else 'Link: '}{alt_text}",
                        block_id=block_id
                    ))
                # Если не нашли ссылки после маркера, не добавляем никаких ссылок
            else:
                # Если маркер не найден (не должно быть), ищем все ссылки как обычно
                for match in link_pattern.finditer(full_text):
                    is_image = match.group(1) == "!"
                    alt_text = match.group(2)
                    url = match.group(3)
                    links.append(ExternalLink(
                        url=url,
                        description=f"{'Image: ' if is_image else 'Link: '}{alt_text}",
                        block_id=block_id
                    ))
        else:
            # Обычные блоки - ищем все ссылки
            for match in link_pattern.finditer(full_text):
                is_image = match.group(1) == "!"
                alt_text = match.group(2)
                url = match.group(3)
                links.append(ExternalLink(
                    url=url,
                    description=f"{'Image: ' if is_image else 'Link: '}{alt_text}",
                    block_id=block_id
                ))
        
        blocks.append(MarkdownBlock(
            text=full_text,
            block_id=block_id,
            section_context=list(sections),
            page_hint=page,
            external_links=links,
            linked_block_ids=linked_ids or []
        ))

    def get_blocks_by_keyword(self, keyword: str) -> List[MarkdownBlock]:
        """Ищет блоки, содержащие ключевое слово (case-insensitive)."""
        blocks = self.parse()
        keyword_lower = keyword.lower()
        return [b for b in blocks if keyword_lower in b.text.lower()]

    def get_blocks_in_section(self, section_keyword: str) -> List[MarkdownBlock]:
        """Ищет блоки, находящиеся в секции с заданным ключевым словом."""
        blocks = self.parse()
        section_keyword_lower = section_keyword.lower()
        results = []
        for block in blocks:
            # Проверяем любой уровень заголовков
            if any(section_keyword_lower in section.lower() for section in block.section_context):
                results.append(block)
        return results
