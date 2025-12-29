"""
Модуль для обработки различных типов файлов.
"""

import json
import logging
import base64
from pathlib import Path
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

from .models import MarkdownBlock, ViewportCrop
from .markdown_parser import MarkdownParser
from .json_annotation_processor import JsonAnnotationProcessor

logger = logging.getLogger(__name__)


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
        """Парсит HTML и извлекает текст."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
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

