"""
Модуль для обработки HTML файлов с результатами OCR строительной документации.
"""

import re
import json
import logging
import html as html_module
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class HtmlBlock:
    """Блок из HTML OCR файла."""
    block_id: str
    block_number: int  # Номер блока на странице
    page_number: int
    block_type: str  # text, image, table
    content: str  # HTML содержимое или текст
    
    # Для изображений
    crop_url: Optional[str] = None
    zone_name: Optional[str] = None
    content_summary: Optional[str] = None
    detailed_description: Optional[str] = None
    ocr_text: Optional[str] = None
    key_entities: List[str] = field(default_factory=list)


@dataclass
class HtmlOcrDocument:
    """Результат парсинга HTML OCR файла."""
    pdf_path: str
    generated_date: str
    blocks: List[HtmlBlock]
    text_blocks: List[HtmlBlock]
    image_blocks: List[HtmlBlock]
    blocks_by_page: Dict[int, List[HtmlBlock]]  # page → blocks


class HtmlOcrProcessor:
    """Процессор HTML файлов с результатами OCR."""
    
    # Регулярка для парсинга заголовка блока (старый формат с ID)
    # "Блок #1 (стр. 2) | Тип: text | ID: 7LPV-EU9..."
    HEADER_PATTERN_OLD = re.compile(
        r'Блок\s+#(\d+)\s+\(стр\.\s+(\d+)\)\s+\|\s+Тип:\s+(\w+)\s+\|\s+ID:\s+([\w-]+)'
    )
    
    # Регулярка для парсинга заголовка блока (новый формат без ID)
    # "Блок #1 (стр. 1) | Тип: text"
    HEADER_PATTERN_NEW = re.compile(
        r'Блок\s+#(\d+)\s+\(стр\.\s+(\d+)\)\s+\|\s+Тип:\s+(\w+)'
    )
    
    # Регулярка для извлечения полного ID блока
    # "BLOCK: 7LPV-EU9J-WJQ"
    BLOCK_ID_PATTERN = re.compile(r'BLOCK:\s+([\w-]+)')
    
    @staticmethod
    def process(html_path: Path) -> Tuple[str, HtmlOcrDocument]:
        """
        Обрабатывает HTML OCR файл.
        
        Args:
            html_path: Путь к HTML файлу
            
        Returns:
            Кортеж (текст для LLM, структурированный документ)
        """
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Извлекаем метаданные документа
            title_elem = soup.find('h1')
            pdf_path = title_elem.get_text(strip=True) if title_elem else "document.pdf"
            
            gen_date_elem = soup.find('p')
            generated_date = ""
            if gen_date_elem:
                date_text = gen_date_elem.get_text(strip=True)
                if 'Сгенерировано:' in date_text:
                    generated_date = date_text.replace('Сгенерировано:', '').strip()
            
            # Парсим все блоки
            blocks = []
            block_divs = soup.find_all('div', class_='block')
            
            for block_div in block_divs:
                parsed_block = HtmlOcrProcessor._parse_block(block_div)
                if parsed_block:
                    blocks.append(parsed_block)
            
            # Группируем блоки
            text_blocks = [b for b in blocks if b.block_type == 'text']
            image_blocks = [b for b in blocks if b.block_type == 'image']
            
            blocks_by_page = {}
            for block in blocks:
                page = block.page_number
                if page not in blocks_by_page:
                    blocks_by_page[page] = []
                blocks_by_page[page].append(block)
            
            document = HtmlOcrDocument(
                pdf_path=pdf_path,
                generated_date=generated_date,
                blocks=blocks,
                text_blocks=text_blocks,
                image_blocks=image_blocks,
                blocks_by_page=blocks_by_page
            )
            
            # Формируем текст для LLM
            llm_text = HtmlOcrProcessor._format_for_llm(document)
            
            return llm_text, document
            
        except Exception as e:
            logger.error(f"Ошибка обработки HTML OCR {html_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"[Ошибка загрузки HTML: {html_path.name}]\n", None
    
    @staticmethod
    def _parse_block(block_div) -> Optional[HtmlBlock]:
        """Парсит один блок из HTML."""
        try:
            # Извлекаем заголовок блока
            header_div = block_div.find('div', class_='block-header')
            if not header_div:
                return None
            
            header_text = header_div.get_text(strip=True)
            
            # Пробуем старый формат (с ID в заголовке)
            match = HtmlOcrProcessor.HEADER_PATTERN_OLD.search(header_text)
            block_id_from_header = None
            if match:
                block_number = int(match.group(1))
                page_number = int(match.group(2))
                block_type = match.group(3)
                block_id_from_header = match.group(4)
            else:
                # Пробуем новый формат (без ID в заголовке)
                match = HtmlOcrProcessor.HEADER_PATTERN_NEW.search(header_text)
                if not match:
                    logger.warning(f"Не удалось распарсить заголовок блока: {header_text}")
                    return None
                block_number = int(match.group(1))
                page_number = int(match.group(2))
                block_type = match.group(3)
            
            # Извлекаем содержимое блока
            content_div = block_div.find('div', class_='block-content')
            if not content_div:
                return None
            
            # Ищем ID блока в контенте (BLOCK: xxx)
            block_id_full = block_id_from_header
            block_id_p = content_div.find('p')
            if block_id_p:
                id_match = HtmlOcrProcessor.BLOCK_ID_PATTERN.search(block_id_p.get_text())
                if id_match:
                    block_id_full = id_match.group(1)
            
            # Если ID не найден ни в заголовке, ни в контенте — генерируем
            if not block_id_full:
                block_id_full = f"block_{page_number}_{block_number}"
            
            # Обработка в зависимости от типа
            if block_type == 'image':
                return HtmlOcrProcessor._parse_image_block(
                    content_div, block_id_full, block_number, page_number
                )
            else:  # text, table
                return HtmlOcrProcessor._parse_text_block(
                    content_div, block_id_full, block_number, page_number, block_type
                )
        
        except Exception as e:
            logger.error(f"Ошибка парсинга блока: {e}")
            return None
    
    @staticmethod
    def _parse_image_block(
        content_div,
        block_id: str,
        block_number: int,
        page_number: int
    ) -> Optional[HtmlBlock]:
        """Парсит блок изображения."""
        try:
            # Извлекаем JSON с анализом изображения
            pre_elem = content_div.find('pre')
            if not pre_elem:
                # Новый формат без JSON - только ссылка на изображение
                logger.info(f"Блок изображения {block_id} без JSON, извлекаем только crop_url")
                
                crop_url = None
                # Пробуем найти ссылку с текстом "Открыть... изображени..."
                link_elem = content_div.find('a', string=re.compile(r'Открыть.*изображени', re.IGNORECASE))
                if link_elem and link_elem.get('href'):
                    crop_url = link_elem['href']
                
                # Fallback: ищем любую ссылку на PDF или изображение
                if not crop_url:
                    for a_tag in content_div.find_all('a', href=True):
                        href = a_tag['href']
                        if href.endswith('.pdf') or any(href.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            crop_url = href
                            break
                
                # Извлекаем базовое описание из текста (если есть)
                text_content = content_div.get_text(strip=True)
                
                return HtmlBlock(
                    block_id=block_id,
                    block_number=block_number,
                    page_number=page_number,
                    block_type='image',
                    content=text_content,
                    crop_url=crop_url,
                    content_summary=f"Изображение на странице {page_number}"
                )
            
            # Декодируем HTML entities
            json_text = html_module.unescape(pre_elem.get_text())
            
            # Очистка от Markdown блоков кода
            json_text = re.sub(r'^```[a-zA-Z]*\s*', '', json_text, flags=re.MULTILINE)
            json_text = re.sub(r'^```\s*', '', json_text, flags=re.MULTILINE)
            json_text = json_text.strip()
            
            data = None
            
            # Парсим JSON
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError:
                # Попытка распарсить несколько JSON-объектов подряд (например, "Extra data")
                try:
                    results = []
                    decoder = json.JSONDecoder()
                    pos = 0
                    while pos < len(json_text):
                        # Пропускаем пробелы
                        while pos < len(json_text) and json_text[pos].isspace():
                            pos += 1
                        if pos >= len(json_text):
                            break
                        
                        try:
                            obj, idx = decoder.raw_decode(json_text, pos)
                            results.append(obj)
                            pos = idx
                        except json.JSONDecodeError:
                            # Если не удалось декодировать с текущей позиции, пробуем найти следующую скобку {
                            next_brace = json_text.find('{', pos + 1)
                            if next_brace != -1:
                                pos = next_brace
                            else:
                                break
                    
                    if results:
                        # Если нашли несколько объектов, пытаемся их объединить
                        if len(results) == 1:
                            data = results[0]
                        else:
                            # Объединяем analysis из нескольких объектов
                            merged_analysis = {
                                "content_summary": [],
                                "detailed_description": [],
                                "clean_ocr_text": [],
                                "key_entities": [],
                                "location": {}
                            }
                            
                            has_analysis = False
                            for res in results:
                                an = res.get('analysis', res if 'content_summary' in res else None)
                                if an:
                                    has_analysis = True
                                    if an.get("content_summary"):
                                        merged_analysis["content_summary"].append(an.get("content_summary"))
                                    if an.get("detailed_description"):
                                        merged_analysis["detailed_description"].append(an.get("detailed_description"))
                                    
                                    ocr = an.get("clean_ocr_text") or an.get("ocr_text")
                                    if ocr:
                                        merged_analysis["clean_ocr_text"].append(ocr)
                                        
                                    if an.get("key_entities"):
                                        merged_analysis["key_entities"].extend(an.get("key_entities", []))
                                    
                                    if an.get("location"):
                                        merged_analysis["location"].update(an.get("location"))
                            
                            if has_analysis:
                                data = {
                                    "analysis": {
                                        "content_summary": " ".join(merged_analysis["content_summary"]),
                                        "detailed_description": " ".join(merged_analysis["detailed_description"]),
                                        "clean_ocr_text": " ".join(merged_analysis["clean_ocr_text"]),
                                        "key_entities": list(set(merged_analysis["key_entities"])), # unique
                                        "location": merged_analysis["location"]
                                    }
                                }
                            else:
                                # Если структуры analysis нет, берем первый успешный объект
                                data = results[0]

                except Exception as merge_err:
                     logger.warning(f"Ошибка восстановления JSON (merge) в блоке {block_id}: {merge_err}")
            
            if data is None:
                # Если все попытки провалились
                logger.warning(f"Не удалось распарсить JSON в блоке {block_id}")
                
                # Возвращаем блок без JSON данных, но с crop_url если есть
                crop_url = None
                # Пробуем найти ссылку с текстом "Открыть... изображени..."
                link_elem = content_div.find('a', string=re.compile(r'Открыть.*изображени', re.IGNORECASE))
                if link_elem and link_elem.get('href'):
                    crop_url = link_elem['href']
                
                # Fallback: ищем любую ссылку на PDF или изображение
                if not crop_url:
                    for a_tag in content_div.find_all('a', href=True):
                        href = a_tag['href']
                        if href.endswith('.pdf') or any(href.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            crop_url = href
                            break
                
                return HtmlBlock(
                    block_id=block_id,
                    block_number=block_number,
                    page_number=page_number,
                    block_type='image',
                    content=json_text,
                    crop_url=crop_url
                )
            
            # Обрабатываем структуру (может быть с оберткой "analysis" или без)
            if 'analysis' in data:
                analysis = data['analysis']
            else:
                analysis = data
            
            location = analysis.get('location', {})
            
            # Извлекаем crop_url
            crop_url = None
            # Пробуем найти ссылку с текстом "Открыть... изображени..."
            link_elem = content_div.find('a', string=re.compile(r'Открыть.*изображени', re.IGNORECASE))
            if link_elem and link_elem.get('href'):
                crop_url = link_elem['href']
            
            # Fallback: ищем любую ссылку на PDF или изображение
            if not crop_url:
                for a_tag in content_div.find_all('a', href=True):
                    href = a_tag['href']
                    if href.endswith('.pdf') or any(href.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                        crop_url = href
                        break
            
            return HtmlBlock(
                block_id=block_id,
                block_number=block_number,
                page_number=page_number,
                block_type='image',
                content=json_text,
                crop_url=crop_url,
                zone_name=location.get('zone_name'),
                content_summary=analysis.get('content_summary'),
                detailed_description=analysis.get('detailed_description'),
                ocr_text=analysis.get('ocr_text') or analysis.get('clean_ocr_text'),
                key_entities=analysis.get('key_entities', [])
            )
        
        except Exception as e:
            logger.error(f"Ошибка парсинга блока изображения {block_id}: {e}")
            return None
    
    @staticmethod
    def _parse_text_block(
        content_div,
        block_id: str,
        block_number: int,
        page_number: int,
        block_type: str
    ) -> Optional[HtmlBlock]:
        """Парсит текстовый блок."""
        try:
            # Клонируем содержимое
            content_copy = content_div.__copy__()
            
            # Удаляем первый <p>BLOCK: ...</p>
            first_p = content_copy.find('p')
            if first_p and HtmlOcrProcessor.BLOCK_ID_PATTERN.search(first_p.get_text()):
                first_p.decompose()
            
            # Извлекаем текст с сохранением структуры
            text_content = content_copy.get_text(separator='\n', strip=True)
            
            return HtmlBlock(
                block_id=block_id,
                block_number=block_number,
                page_number=page_number,
                block_type=block_type,
                content=text_content
            )
        
        except Exception as e:
            logger.error(f"Ошибка парсинга текстового блока {block_id}: {e}")
            return None
    
    @staticmethod
    def _format_for_llm(document: HtmlOcrDocument) -> str:
        """Форматирует HTML документ в текст для LLM."""
        lines = []
        lines.append(f"[HTML OCR ДОКУМЕНТАЦИЯ: {document.pdf_path}]\n")
        
        if document.generated_date:
            lines.append(f"Дата генерации: {document.generated_date}\n")
        
        # Статистика
        lines.append(f"Всего блоков: {len(document.blocks)}")
        lines.append(f"  - Текстовых: {len(document.text_blocks)}")
        lines.append(f"  - Изображений: {len(document.image_blocks)}")
        lines.append(f"Страниц: {len(document.blocks_by_page)}\n")
        
        # Каталог изображений
        if document.image_blocks:
            lines.append("## КАТАЛОГ ИЗОБРАЖЕНИЙ\n")
            
            # Группируем по типу зоны
            by_zone = {}
            for block in document.image_blocks:
                zone = block.zone_name or "Не определено"
                if zone not in by_zone:
                    by_zone[zone] = []
                by_zone[zone].append(block)
            
            for zone_name, blocks in sorted(by_zone.items()):
                lines.append(f"### {zone_name} ({len(blocks)})")
                for block in blocks[:15]:  # Первые 15
                    summary = block.content_summary or "Без описания"
                    lines.append(
                        f"  - [{block.block_id}] Стр.{block.page_number}: {summary[:80]}..."
                    )
                    if block.crop_url:
                        lines.append(f"    URL: {block.crop_url}")
                if len(blocks) > 15:
                    lines.append(f"  ... и ещё {len(blocks) - 15} изображений")
                lines.append("")
        
        # Содержание по страницам (краткое)
        lines.append("## СОДЕРЖАНИЕ ПО СТРАНИЦАМ\n")
        for page_num in sorted(document.blocks_by_page.keys())[:10]:  # Первые 10 страниц
            blocks = document.blocks_by_page[page_num]
            text_count = sum(1 for b in blocks if b.block_type == 'text')
            image_count = sum(1 for b in blocks if b.block_type == 'image')
            
            lines.append(f"Страница {page_num}: {text_count} текст., {image_count} изобр.")
            
            # Показываем заголовки
            for block in blocks:
                if block.block_type == 'text' and block.content:
                    first_line = block.content.split('\n')[0][:60]
                    if first_line:
                        lines.append(f"  - {first_line}...")
                elif block.block_type == 'image' and block.content_summary:
                    lines.append(f"  - 🖼️ {block.content_summary[:60]}...")
        
        if len(document.blocks_by_page) > 10:
            lines.append(f"... и ещё {len(document.blocks_by_page) - 10} страниц\n")
        
        # Инструкция
        lines.append("\n## ИНСТРУКЦИЯ")
        lines.append("- Для полнотекстового поиска используй text блоки")
        lines.append("- Для запроса изображений используй crop_url из image блоков")
        lines.append("- ID блока связывает HTML и JSON файлы")
        lines.append("- Используй zone_name для фильтрации изображений по типу\n")
        
        return "\n".join(lines)
    
    @staticmethod
    def search_text(document: HtmlOcrDocument, query: str) -> List[HtmlBlock]:
        """
        Полнотекстовый поиск в HTML документе.
        
        Args:
            document: HTML документ
            query: Поисковый запрос
            
        Returns:
            Список блоков с найденным текстом
        """
        query_lower = query.lower()
        results = []
        
        for block in document.text_blocks:
            if query_lower in block.content.lower():
                results.append(block)
        
        # Поиск в изображениях (ocr_text, key_entities)
        for block in document.image_blocks:
            if block.ocr_text and query_lower in block.ocr_text.lower():
                results.append(block)
            elif block.content_summary and query_lower in block.content_summary.lower():
                results.append(block)
            elif block.key_entities:
                for entity in block.key_entities:
                    if query_lower in entity.lower():
                        results.append(block)
                        break
        
        return results

