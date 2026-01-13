"""
Модуль для обработки различных типов файлов.
"""

import json
import logging
import base64
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

from .models import MarkdownBlock, ViewportCrop
from .markdown_parser import MarkdownParser
from .json_annotation_processor import JsonAnnotationProcessor
from .html_ocr_processor import HtmlOcrProcessor

logger = logging.getLogger(__name__)


@dataclass
class MdImageBlock:
    """Блок изображения из нового MD формата (_document.md)."""
    block_id: str
    page_number: int
    block_type: str = "image"
    content_summary: str = ""
    detailed_description: str = ""
    ocr_text: str = ""
    key_entities: List[str] = field(default_factory=list)
    sheet_name: str = ""  # Наименование листа (берется с уровня страницы)
    crop_url: str = ""


class FileProcessor:
    """Обработчик различных типов файлов для передачи в LLM."""
    
    @staticmethod
    def process_file(
        file_path: Path,
        db_chat_id: Optional[str] = None
    ) -> Tuple[str, List[MarkdownBlock], Optional[ViewportCrop]]:
        """
        Обрабатывает файл в зависимости от его типа.
        
        Args:
            file_path: Путь к файлу
            db_chat_id: ID чата для S3 загрузки
            
        Returns:
            Кортеж (текст, блоки, изображение)
            - текст: извлеченный текст для контекста
            - блоки: список MarkdownBlock (для .md файлов)
            - изображение: ViewportCrop для изображений (jpg, png)
        """
        suffix = file_path.suffix.lower()
        
        if suffix == '.md':
            return FileProcessor._process_markdown(file_path)
        elif suffix in ['.jpg', '.jpeg', '.png']:
            return FileProcessor._process_image(file_path, db_chat_id)
        elif suffix == '.html':
            return FileProcessor._process_html(file_path)
        elif suffix == '.json':
            return FileProcessor._process_json(file_path)
        else:
            # Неизвестный тип - пытаемся прочитать как текст
            return FileProcessor._process_text(file_path)
    
    @staticmethod
    def _process_markdown(file_path: Path) -> Tuple[str, List[MarkdownBlock], None]:
        """Обрабатывает .md файл через MarkdownParser."""
        parser = MarkdownParser(file_path)
        blocks = parser.parse()
        
        full_text = ""
        for block in blocks:
            full_text += block.text + "\n\n"
        
        # Если парсер не извлек текст (новый формат _document.md), читаем файл напрямую
        if not full_text.strip():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    full_text = f.read()
                logger.info(f"MD файл {file_path.name} прочитан напрямую ({len(full_text)} символов)")
            except Exception as e:
                logger.error(f"Ошибка чтения MD файла {file_path}: {e}")
        
        return full_text, blocks, None
    
    @staticmethod
    def _process_image(
        file_path: Path,
        db_chat_id: Optional[str]
    ) -> Tuple[str, List, Optional[ViewportCrop]]:
        """
        Обрабатывает изображение (jpg, png).
        Возвращает ViewportCrop для передачи в LLM как изображение.
        """
        try:
            # Создаем ViewportCrop для изображения
            # Для пользовательских изображений используем page_number=0 и пустые координаты
            viewport = ViewportCrop(
                page_number=0,  # Пользовательское изображение, не из PDF
                crop_coords=(0, 0, 0, 0),  # Нет координат кропа
                image_path=str(file_path),
                description=f"Загруженное изображение: {file_path.name}",
                target_blocks=[file_path.stem],  # используем имя файла как ID
                s3_url=None  # будет заполнено при загрузке в S3
            )
            
            text = f"[Изображение: {file_path.name}]\n"
            return text, [], viewport
            
        except Exception as e:
            logger.error(f"Ошибка обработки изображения {file_path}: {e}")
            return f"[Ошибка загрузки изображения: {file_path.name}]\n", [], None
    
    @staticmethod
    def _process_html(file_path: Path) -> Tuple[str, List, None]:
        """Парсит HTML файл."""
        try:
            # Проверяем, является ли это HTML OCR файлом
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Признаки HTML OCR файла: class="block block-type-*"
            if 'class="block block-type-' in content:
                logger.info(f"Обнаружен HTML OCR файл: {file_path.name}")
                llm_text, document = HtmlOcrProcessor.process(file_path)
                return llm_text, [], None
            
            # Иначе - обычный HTML, парсим BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Удаляем script и style теги
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Извлекаем текст
            text = soup.get_text(separator='\n', strip=True)
            
            # Форматируем для читаемости
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            formatted_text = '\n'.join(lines)
            
            result = f"[HTML файл: {file_path.name}]\n\n{formatted_text}\n\n"
            return result, [], None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга HTML {file_path}: {e}")
            # Fallback - читаем как текст
            return FileProcessor._process_text(file_path)
    
    @staticmethod
    def _process_json(file_path: Path) -> Tuple[str, List, None]:
        """Читает и форматирует JSON файл."""
        try:
            # Проверяем, является ли это JSON аннотацией чертежей
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Если есть структура с pages и blocks - это аннотация
            if 'pages' in data and isinstance(data.get('pages'), list):
                logger.info(f"Обнаружен JSON файл аннотации чертежей: {file_path.name}")
                llm_text, annotation = JsonAnnotationProcessor.process(file_path)
                return llm_text, [], None
            
            # Иначе - обычный JSON
            formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
            result = f"[JSON файл: {file_path.name}]\n\n```json\n{formatted_json}\n```\n\n"
            return result, [], None
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON {file_path}: {e}")
            # Fallback - читаем как текст
            return FileProcessor._process_text(file_path)
        except Exception as e:
            logger.error(f"Ошибка чтения JSON {file_path}: {e}")
            return f"[Ошибка загрузки JSON: {file_path.name}]\n", [], None
    
    @staticmethod
    def _process_text(file_path: Path) -> Tuple[str, List, None]:
        """Читает файл как обычный текст."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            result = f"[Текстовый файл: {file_path.name}]\n\n{content}\n\n"
            return result, [], None
            
        except Exception as e:
            logger.error(f"Ошибка чтения текстового файла {file_path}: {e}")
            return f"[Ошибка загрузки файла: {file_path.name}]\n", [], None

    @staticmethod
    def parse_md_image_blocks(file_path: Path) -> List[MdImageBlock]:
        """
        Парсит изображения из нового MD формата (_document.md).
        
        Формат:
        ## СТРАНИЦА X
        **Наименование листа:** ...
        
        ### BLOCK [IMAGE]: ID
        **[ИЗОБРАЖЕНИЕ]** | Тип: ...
        **Краткое описание:** ...
        **Описание:** ...
        **Текст на чертеже:** ...
        **Сущности:** ...
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Ошибка чтения MD файла {file_path}: {e}")
            return []
        
        image_blocks: List[MdImageBlock] = []
        
        # Регулярки
        page_pattern = re.compile(r'^## СТРАНИЦА (\d+)', re.MULTILINE)
        sheet_name_pattern = re.compile(r'\*\*Наименование листа:\*\*\s*(.+?)$', re.MULTILINE)
        block_image_pattern = re.compile(r'^### BLOCK \[IMAGE\]: ([A-Z0-9\-]+)', re.MULTILINE)
        
        # Парсим по страницам
        pages = list(page_pattern.finditer(content))
        
        for i, page_match in enumerate(pages):
            page_num = int(page_match.group(1))
            page_start = page_match.end()
            page_end = pages[i + 1].start() if i + 1 < len(pages) else len(content)
            page_content = content[page_start:page_end]
            
            # Ищем Наименование листа для этой страницы
            sheet_match = sheet_name_pattern.search(page_content)
            sheet_name = sheet_match.group(1).strip() if sheet_match else ""
            
            # Ищем блоки изображений на странице
            image_matches = list(block_image_pattern.finditer(page_content))
            
            for j, img_match in enumerate(image_matches):
                block_id = img_match.group(1)
                block_start = img_match.end()
                # Конец блока - начало следующего блока или следующая страница
                block_end = image_matches[j + 1].start() if j + 1 < len(image_matches) else len(page_content)
                block_content = page_content[block_start:block_end]
                
                # Извлекаем поля
                content_summary = ""
                detailed_description = ""
                ocr_text = ""
                key_entities = []
                
                # Краткое описание
                summary_match = re.search(r'\*\*Краткое описание:\*\*\s*(.+?)(?:\n\n|\n\*\*|$)', block_content, re.DOTALL)
                if summary_match:
                    content_summary = summary_match.group(1).strip()
                
                # Описание
                desc_match = re.search(r'\*\*Описание:\*\*\s*(.+?)(?:\n\n|\n\*\*|$)', block_content, re.DOTALL)
                if desc_match:
                    detailed_description = desc_match.group(1).strip()
                
                # Текст на чертеже
                ocr_match = re.search(r'\*\*Текст на чертеже:\*\*\s*(.+?)(?:\n\n|\n\*\*|$)', block_content, re.DOTALL)
                if ocr_match:
                    ocr_text = ocr_match.group(1).strip()
                
                # Сущности
                entities_match = re.search(r'\*\*Сущности:\*\*\s*(.+?)(?:\n\n|\n\*\*|$)', block_content, re.DOTALL)
                if entities_match:
                    entities_str = entities_match.group(1).strip()
                    key_entities = [e.strip() for e in entities_str.split(',') if e.strip()]
                
                image_blocks.append(MdImageBlock(
                    block_id=block_id,
                    page_number=page_num,
                    content_summary=content_summary,
                    detailed_description=detailed_description,
                    ocr_text=ocr_text,
                    key_entities=key_entities,
                    sheet_name=sheet_name
                ))
        
        logger.info(f"Извлечено {len(image_blocks)} изображений из MD файла {file_path.name}")
        return image_blocks

