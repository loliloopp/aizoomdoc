"""
Парсинг result.md с извлечением текстовых блоков и якорей BLOCK_ID.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional

from .models import MarkdownBlock

logger = logging.getLogger(__name__)


class MarkdownParser:
    """Парсер Markdown-файлов с поддержкой HTML-комментариев BLOCK_ID."""
    
    # Регулярные выражения для парсинга
    BLOCK_ID_START_RE = re.compile(r"<!--\s*BLOCK_ID:\s*([a-f0-9\-]+)\s*-->")
    BLOCK_ID_END_RE = re.compile(r"<!--\s*END_BLOCK\s*-->")
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
    
    def __init__(self, markdown_path: Path):
        """
        Инициализирует парсер.
        
        Args:
            markdown_path: Путь к файлу result.md
        """
        self.markdown_path = markdown_path
        self.content: str = ""
        self.blocks: List[MarkdownBlock] = []
        self._load()
        self._parse()
    
    def _load(self) -> None:
        """Загружает содержимое Markdown-файла."""
        if not self.markdown_path.exists():
            raise FileNotFoundError(
                f"Markdown-файл не найден: {self.markdown_path}"
            )
        
        logger.info(f"Загрузка Markdown из {self.markdown_path}")
        
        with open(self.markdown_path, "r", encoding="utf-8") as f:
            self.content = f.read()
    
    def _parse(self) -> None:
        """Парсит Markdown, извлекая блоки и их связи с BLOCK_ID."""
        lines = self.content.split("\n")
        
        current_section_context: List[str] = []
        current_block_lines: List[str] = []
        current_block_id: Optional[str] = None
        in_block = False
        
        for line in lines:
            # Проверяем заголовки для отслеживания контекста секций
            heading_match = self.HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Обновляем контекст заголовков
                current_section_context = current_section_context[:level-1] + [title]
                
                # Если мы не внутри BLOCK_ID, добавляем заголовок как обычный текст
                if not in_block and current_block_lines:
                    self._add_block(current_block_lines, None, current_section_context[:])
                    current_block_lines = []
            
            # Проверяем начало BLOCK_ID
            block_start_match = self.BLOCK_ID_START_RE.match(line)
            if block_start_match:
                # Сохраняем накопленный обычный текст
                if current_block_lines:
                    self._add_block(current_block_lines, None, current_section_context[:])
                    current_block_lines = []
                
                # Начинаем новый блок с ID
                current_block_id = block_start_match.group(1)
                in_block = True
                continue
            
            # Проверяем конец BLOCK_ID
            block_end_match = self.BLOCK_ID_END_RE.match(line)
            if block_end_match:
                # Сохраняем блок с ID
                if current_block_lines:
                    self._add_block(
                        current_block_lines,
                        current_block_id,
                        current_section_context[:]
                    )
                    current_block_lines = []
                
                current_block_id = None
                in_block = False
                continue
            
            # Накапливаем строки
            if line.strip():  # Игнорируем пустые строки
                current_block_lines.append(line)
            elif current_block_lines:
                # Пустая строка завершает блок (если не внутри BLOCK_ID)
                if not in_block:
                    self._add_block(current_block_lines, None, current_section_context[:])
                    current_block_lines = []
                else:
                    current_block_lines.append(line)  # Сохраняем пустые строки внутри блока
        
        # Сохраняем последний накопленный блок
        if current_block_lines:
            self._add_block(current_block_lines, current_block_id, current_section_context[:])
        
        logger.info(f"Извлечено {len(self.blocks)} текстовых блоков из Markdown")
    
    def _add_block(
        self,
        lines: List[str],
        block_id: Optional[str],
        section_context: List[str]
    ) -> None:
        """Добавляет блок в список."""
        text = "\n".join(lines).strip()
        if not text:
            return
        
        block = MarkdownBlock(
            text=text,
            block_id=block_id,
            section_context=section_context
        )
        self.blocks.append(block)
    
    def get_all_blocks(self) -> List[MarkdownBlock]:
        """Возвращает все блоки."""
        return self.blocks
    
    def get_blocks_by_keyword(
        self,
        keyword: str,
        case_sensitive: bool = False
    ) -> List[MarkdownBlock]:
        """
        Находит блоки, содержащие указанное ключевое слово.
        
        Args:
            keyword: Ключевое слово для поиска
            case_sensitive: Учитывать регистр
        
        Returns:
            Список блоков, содержащих ключевое слово
        """
        if not case_sensitive:
            keyword = keyword.lower()
        
        results = []
        for block in self.blocks:
            text = block.text if case_sensitive else block.text.lower()
            context = " ".join(block.section_context)
            if not case_sensitive:
                context = context.lower()
            
            if keyword in text or keyword in context:
                results.append(block)
        
        logger.debug(f"Найдено {len(results)} блоков с ключевым словом '{keyword}'")
        return results
    
    def get_blocks_in_section(self, section_keyword: str) -> List[MarkdownBlock]:
        """
        Находит все блоки в секциях, содержащих указанное ключевое слово.
        
        Args:
            section_keyword: Ключевое слово для поиска в заголовках секций
        
        Returns:
            Список блоков из релевантных секций
        """
        keyword_lower = section_keyword.lower()
        results = []
        
        for block in self.blocks:
            for section in block.section_context:
                if keyword_lower in section.lower():
                    results.append(block)
                    break
        
        logger.debug(
            f"Найдено {len(results)} блоков в секциях с '{section_keyword}'"
        )
        return results
    
    def get_block_by_id(self, block_id: str) -> Optional[MarkdownBlock]:
        """
        Находит блок по его BLOCK_ID.
        
        Args:
            block_id: ID блока
        
        Returns:
            Блок или None если не найден
        """
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

