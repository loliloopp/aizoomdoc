"""
Клиент для взаимодействия с LLM через OpenRouter API.
Поддержка мультимодальных запросов (текст + изображения).
"""

import base64
import logging
from pathlib import Path
from typing import List, Optional

import requests

from .config import config
from .models import SearchResult, ViewportCrop

logger = logging.getLogger(__name__)


# Системный промт для инженера-проектировщика
SYSTEM_PROMPT = """Ты — опытный инженер-проектировщик по разделу ОВ (Отопление и Вентиляция) и ВК (Водоснабжение и Канализация), работающий со строительной документацией.

Твоя задача — анализировать строительные чертежи, спецификации оборудования и пояснительные записки.

ПРИНЦИПЫ РАБОТЫ:
1. ТОЧНОСТЬ И КОНСЕРВАТИЗМ: Будь максимально точен. Избегай догадок и предположений.
2. ЯВНОЕ УКАЗАНИЕ НЕОПРЕДЕЛЁННОСТИ: Если информации недостаточно для ответа, ЯВНО укажи на это. Лучше признать отсутствие данных, чем дать неверный ответ.
3. ССЫЛКИ НА ИСТОЧНИКИ: Всегда указывай, откуда взята информация (номер листа, раздел спецификации, позиция на чертеже).
4. СТРУКТУРИРОВАННОСТЬ: Предоставляй информацию в структурированном виде (списки, таблицы где уместно).
5. ТЕРМИНОЛОГИЯ: Используй корректную профессиональную терминологию.

КОНТЕКСТ РАБОТЫ:
- Тебе предоставляются текстовые фрагменты из спецификаций и пояснительных записок.
- Также предоставляются изображения фрагментов чертежей с подсвеченными (красной рамкой) областями интереса.
- OCR-текст может содержать ошибки, поэтому приоритет отдавай визуальному анализу изображений.

ФОРМАТ ОТВЕТА:
- Начинай с краткого резюме.
- Затем предоставь детальную информацию с разбивкой по пунктам.
- Для каждого упоминания оборудования или элемента указывай источник.
- Если сравниваешь две стадии, явно структурируй ответ: "Стадия П", "Стадия Р", "Отличия".

ЗАПРЕЩЕНО:
- Придумывать информацию, которой нет в предоставленных материалах.
- Делать предположения о характеристиках оборудования без явного подтверждения в документах.
- Игнорировать визуальную информацию с чертежей в пользу только текста."""


class LLMClient:
    """Клиент для работы с LLM через OpenRouter API."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Инициализирует клиент.
        
        Args:
            api_key: API ключ OpenRouter (если None, берётся из config)
            base_url: Базовый URL API (если None, берётся из config)
            model: Имя модели (если None, берётся из config)
        """
        self.api_key = api_key or config.OPENROUTER_API_KEY
        self.base_url = base_url or config.OPENROUTER_BASE_URL
        self.model = model or config.DEFAULT_MODEL
        
        if not self.api_key:
            raise ValueError("OpenRouter API key не задан")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        logger.info(f"LLMClient инициализирован с моделью: {self.model}")
    
    def encode_image_to_base64(self, image_path: Path) -> str:
        """
        Кодирует изображение в base64.
        
        Args:
            image_path: Путь к изображению
        
        Returns:
            Base64-строка изображения
        """
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        return base64.b64encode(image_bytes).decode("utf-8")
    
    def build_multimodal_prompt(
        self,
        user_query: str,
        search_result: SearchResult,
        stage_label: str = ""
    ) -> List[dict]:
        """
        Строит мультимодальный промт из текстовых блоков и изображений.
        
        Args:
            user_query: Запрос пользователя
            search_result: Результаты поиска
            stage_label: Метка стадии (например, "Стадия П")
        
        Returns:
            Список частей сообщения (text и image_url)
        """
        content = []
        
        # Начинаем с пользовательского запроса
        intro = f"ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n{user_query}\n\n"
        if stage_label:
            intro += f"=== {stage_label.upper()} ===\n\n"
        
        # Добавляем текстовый контекст
        if search_result.text_blocks:
            intro += "ТЕКСТОВЫЙ КОНТЕКСТ (из спецификаций и пояснительных записок):\n\n"
            
            for idx, block in enumerate(search_result.text_blocks, 1):
                intro += f"--- Текстовый блок #{idx} ---\n"
                if block.section_context:
                    intro += f"Раздел: {' > '.join(block.section_context)}\n"
                if block.block_id:
                    intro += f"Block ID: {block.block_id}\n"
                intro += f"\n{block.text}\n\n"
        
        # Добавляем описания изображений
        if search_result.viewport_crops:
            intro += f"ВИЗУАЛЬНЫЙ КОНТЕКСТ ({len(search_result.viewport_crops)} изображений фрагментов чертежей):\n"
            intro += "Красные рамки на изображениях выделяют области интереса.\n\n"
            
            for idx, viewport in enumerate(search_result.viewport_crops, 1):
                intro += f"Изображение #{idx}: {viewport.description}\n"
        
        intro += "\n---\n\nОтветь на запрос пользователя на основе предоставленного контекста.\n"
        
        content.append({
            "type": "text",
            "text": intro
        })
        
        # Добавляем изображения
        for viewport in search_result.viewport_crops:
            if viewport.image_path:
                image_path = Path(viewport.image_path)
                if image_path.exists():
                    # Кодируем в base64
                    base64_image = self.encode_image_to_base64(image_path)
                    
                    # Определяем MIME-тип
                    mime_type = "image/jpeg"
                    if image_path.suffix.lower() in [".png"]:
                        mime_type = "image/png"
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    })
                else:
                    logger.warning(f"Изображение не найдено: {image_path}")
        
        return content
    
    def query(
        self,
        user_query: str,
        search_result: SearchResult,
        stage_label: str = "",
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4000
    ) -> str:
        """
        Отправляет запрос к LLM.
        
        Args:
            user_query: Запрос пользователя
            search_result: Результаты поиска
            stage_label: Метка стадии
            system_prompt: Кастомный системный промт (если None, используется SYSTEM_PROMPT)
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов в ответе
        
        Returns:
            Ответ от LLM
        
        Raises:
            Exception: При ошибках API
        """
        system_prompt = system_prompt or SYSTEM_PROMPT
        
        # Строим мультимодальный промт
        content = self.build_multimodal_prompt(user_query, search_result, stage_label)
        
        # Формируем запрос
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        logger.info(f"Отправка запроса к LLM (модель: {self.model})")
        logger.debug(f"Текстовых блоков: {len(search_result.text_blocks)}")
        logger.debug(f"Изображений: {len(search_result.viewport_crops)}")
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            
            result = response.json()
            answer = result["choices"][0]["message"]["content"]
            
            logger.info("Ответ от LLM получен успешно")
            return answer
            
        except requests.exceptions.Timeout:
            logger.error("Таймаут при запросе к LLM")
            raise Exception("Таймаут при обращении к LLM API")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP ошибка: {e}")
            logger.error(f"Ответ сервера: {response.text}")
            raise Exception(f"Ошибка API: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
            raise
    
    def query_comparison(
        self,
        user_query: str,
        stage_p_result: SearchResult,
        stage_r_result: SearchResult,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 6000
    ) -> str:
        """
        Отправляет запрос для сравнения двух стадий.
        
        Args:
            user_query: Запрос пользователя
            stage_p_result: Результаты для стадии П
            stage_r_result: Результаты для стадии Р
            system_prompt: Кастомный системный промт
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов
        
        Returns:
            Ответ от LLM
        """
        system_prompt = system_prompt or SYSTEM_PROMPT
        
        # Строим промты для обеих стадий
        content_p = self.build_multimodal_prompt(user_query, stage_p_result, "Стадия П")
        content_r = self.build_multimodal_prompt(user_query, stage_r_result, "Стадия Р")
        
        # Объединяем контент
        combined_content = []
        combined_content.append({
            "type": "text",
            "text": f"ЗАДАЧА: Сравни две стадии проектирования (П и Р) по следующему запросу:\n{user_query}\n\n"
        })
        combined_content.extend(content_p)
        combined_content.append({
            "type": "text",
            "text": "\n\n========================================\n\n"
        })
        combined_content.extend(content_r)
        combined_content.append({
            "type": "text",
            "text": "\n\n---\n\nПроведи детальное сравнение стадии П и стадии Р. "
                    "Укажи все отличия в оборудовании, параметрах, расположении и т.д."
        })
        
        # Формируем запрос
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": combined_content
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        logger.info("Отправка запроса сравнения к LLM")
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=180
            )
            response.raise_for_status()
            
            result = response.json()
            answer = result["choices"][0]["message"]["content"]
            
            logger.info("Ответ от LLM получен успешно")
            return answer
            
        except Exception as e:
            logger.error(f"Ошибка при запросе сравнения: {e}")
            raise

