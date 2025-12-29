"""
Модуль для обработки JSON файлов с аннотациями строительной документации.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ImageBlock:
    """Блок изображения из JSON аннотации."""
    block_id: str
    page_number: int
    block_type: str
    crop_url: Optional[str] = None
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    zone_name: Optional[str] = None
    content_summary: Optional[str] = None
    detailed_description: Optional[str] = None
    ocr_text: Optional[str] = None
    key_entities: List[str] = field(default_factory=list)
    stamp_data: Optional[Dict] = None
    linked_block_id: Optional[str] = None
    coords_px: List[int] = field(default_factory=list)


@dataclass
class JsonAnnotation:
    """Результат парсинга JSON аннотации."""
    pdf_path: str
    image_blocks: List[ImageBlock]
    text_blocks: List[Dict]
    groups: Dict[str, List[ImageBlock]]  # group_name -> блоки


class JsonAnnotationProcessor:
    """Процессор JSON файлов с аннотациями чертежей."""
    
    @staticmethod
    def process(json_path: Path) -> Tuple[str, JsonAnnotation]:
        """
        Обрабатывает JSON файл с аннотациями.
        
        Args:
            json_path: Путь к JSON файлу
            
        Returns:
            Кортеж (текст для LLM, структурированная аннотация)
        """
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            pdf_path = data.get('pdf_path', 'document.pdf')
            image_blocks = []
            text_blocks = []
            groups = {}
            
            # Парсим все блоки
            for page in data.get('pages', []):
                page_num = page.get('page_number', 0)
                
                for block in page.get('blocks', []):
                    block_type = block.get('block_type', 'unknown')
                    block_id = block.get('id', 'unknown')
                    
                    if block_type == 'image':
                        img_block = JsonAnnotationProcessor._parse_image_block(block, page_num)
                        image_blocks.append(img_block)
                        
                        # Группировка
                        if img_block.group_name:
                            if img_block.group_name not in groups:
                                groups[img_block.group_name] = []
                            groups[img_block.group_name].append(img_block)
                    
                    elif block_type == 'text':
                        text_blocks.append({
                            'id': block_id,
                            'page': page_num,
                            'text': block.get('ocr_text', ''),
                            'stamp_data': block.get('stamp_data')
                        })
            
            annotation = JsonAnnotation(
                pdf_path=pdf_path,
                image_blocks=image_blocks,
                text_blocks=text_blocks,
                groups=groups
            )
            
            # Формируем текст для LLM
            llm_text = JsonAnnotationProcessor._format_for_llm(annotation)
            
            return llm_text, annotation
            
        except Exception as e:
            logger.error(f"Ошибка обработки JSON аннотации {json_path}: {e}")
            return f"[Ошибка загрузки JSON: {json_path.name}]\n", None
    
    @staticmethod
    def _parse_image_block(block: Dict, page_num: int) -> ImageBlock:
        """Парсит блок изображения."""
        ocr_json = block.get('ocr_json', {})
        location = ocr_json.get('location', {}) if isinstance(ocr_json, dict) else {}
        
        # Иногда ocr_text содержит JSON строку
        ocr_text_raw = block.get('ocr_text', '')
        if isinstance(ocr_text_raw, str) and ocr_text_raw.strip().startswith('{'):
            try:
                ocr_parsed = json.loads(ocr_text_raw)
                if 'location' in ocr_parsed:
                    location = ocr_parsed.get('location', {})
                    ocr_json = ocr_parsed
            except:
                pass
        
        return ImageBlock(
            block_id=block.get('id', 'unknown'),
            page_number=page_num,
            block_type=block.get('block_type', 'image'),
            crop_url=block.get('crop_url'),
            group_id=block.get('group_id'),
            group_name=block.get('group_name'),
            zone_name=location.get('zone_name'),
            content_summary=ocr_json.get('content_summary'),
            detailed_description=ocr_json.get('detailed_description'),
            ocr_text=ocr_json.get('ocr_text') or ocr_json.get('clean_ocr_text'),
            key_entities=ocr_json.get('key_entities', []),
            stamp_data=block.get('stamp_data'),
            linked_block_id=block.get('linked_block_id'),
            coords_px=block.get('coords_px', [])
        )
    
    @staticmethod
    def _format_for_llm(annotation: JsonAnnotation) -> str:
        """Форматирует аннотацию в текст для LLM."""
        lines = []
        lines.append(f"[JSON АННОТАЦИЯ ЧЕРТЕЖЕЙ: {annotation.pdf_path}]\n")
        
        # Статистика
        lines.append(f"Всего изображений: {len(annotation.image_blocks)}")
        lines.append(f"Групп изображений: {len(annotation.groups)}")
        lines.append(f"Текстовых блоков: {len(annotation.text_blocks)}\n")
        
        # Группы изображений
        if annotation.groups:
            lines.append("## ГРУППЫ ИЗОБРАЖЕНИЙ\n")
            for group_name, blocks in annotation.groups.items():
                lines.append(f"### Группа: {group_name} ({len(blocks)} изображений)")
                for block in blocks:
                    stamp = block.stamp_data or {}
                    sheet = stamp.get('sheet_number', '?')
                    doc_code = stamp.get('document_code', '')
                    
                    lines.append(f"  - ID: {block.block_id} | Стр: {block.page_number} | Лист: {sheet} {doc_code}")
                    lines.append(f"    Тип: {block.zone_name or 'Не определён'}")
                    if block.content_summary:
                        lines.append(f"    Описание: {block.content_summary[:150]}...")
                    if block.key_entities:
                        entities = ', '.join(block.key_entities[:10])
                        lines.append(f"    Ключевые сущности: {entities}")
                    if block.crop_url:
                        lines.append(f"    URL: {block.crop_url}")
                lines.append("")
        
        # Каталог всех изображений по типам
        lines.append("## КАТАЛОГ ИЗОБРАЖЕНИЙ ПО ТИПАМ\n")
        by_zone = {}
        for block in annotation.image_blocks:
            zone = block.zone_name or "Не определено"
            if zone not in by_zone:
                by_zone[zone] = []
            by_zone[zone].append(block)
        
        for zone_name, blocks in sorted(by_zone.items()):
            lines.append(f"### {zone_name} ({len(blocks)})")
            for block in blocks[:20]:  # Первые 20
                stamp = block.stamp_data or {}
                sheet = stamp.get('sheet_number', '?')
                summary = block.content_summary or "Без описания"
                lines.append(f"  - [{block.block_id}] Лист {sheet}: {summary[:100]}")
            if len(blocks) > 20:
                lines.append(f"  ... и ещё {len(blocks) - 20} изображений")
            lines.append("")
        
        # Текстовые блоки (краткая сводка)
        if annotation.text_blocks:
            lines.append(f"## ТЕКСТОВЫЕ БЛОКИ\n")
            lines.append(f"Всего текстовых блоков: {len(annotation.text_blocks)}")
            lines.append("(Полный текст доступен в HTML файле)\n")
        
        # Инструкция для LLM
        lines.append("## ИНСТРУКЦИЯ")
        lines.append("Для запроса изображений используй crop_url указанных блоков.")
        lines.append("Для поиска связанных элементов используй group_name.")
        lines.append("Для идентификации листа используй stamp_data (номер листа, шифр).\n")
        
        return "\n".join(lines)
    
    @staticmethod
    def find_blocks_by_query(
        annotation: JsonAnnotation,
        query: str,
        zone_filter: Optional[str] = None,
        group_filter: Optional[str] = None
    ) -> List[ImageBlock]:
        """
        Ищет блоки по запросу.
        
        Args:
            annotation: Аннотация
            query: Поисковый запрос
            zone_filter: Фильтр по типу зоны
            group_filter: Фильтр по группе
            
        Returns:
            Список релевантных блоков
        """
        query_lower = query.lower()
        results = []
        
        for block in annotation.image_blocks:
            # Фильтры
            if zone_filter and block.zone_name != zone_filter:
                continue
            if group_filter and block.group_name != group_filter:
                continue
            
            # Поиск в тексте
            score = 0
            if block.content_summary and query_lower in block.content_summary.lower():
                score += 10
            if block.ocr_text and query_lower in block.ocr_text.lower():
                score += 5
            if block.key_entities:
                for entity in block.key_entities:
                    if query_lower in entity.lower():
                        score += 20
            
            if score > 0:
                results.append((score, block))
        
        # Сортировка по релевантности
        results.sort(key=lambda x: x[0], reverse=True)
        return [block for score, block in results]

