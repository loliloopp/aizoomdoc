"""
Клиент для взаимодействия с LLM (OpenRouter) в режиме диалога.
"""

import base64
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests

from .config import config
from .models import ViewportCrop, ZoomRequest, ImageSelection

logger = logging.getLogger(__name__)

# Промт для этапа 1: Выбор картинок
SELECTION_PROMPT = """Ты — ассистент по анализу технической документации.
Твоя задача — найти в тексте ИЗОБРАЖЕНИЯ, необходимые для ответа на запрос пользователя.

ВАЖНО ПРО СТРУКТУРУ ДОКУМЕНТА:
1. Документ содержит блоки описания изображений, которые выглядят так:
   ```
   *Изображение:*
   { ... JSON метаданные ... }
   ![Изображение](https://... .pdf)  <-- ЭТА ССЫЛКА ПРАВИЛЬНАЯ (находится ПОСЛЕ метаданных)
   ```
2. Иногда перед блоком *Изображение:* может быть ошибочная ссылка. ИГНОРИРУЙ ЕЕ.
3. Бери только ту ссылку, которая идет СРАЗУ ПОСЛЕ блока метаданных (JSON).

ИНСТРУКЦИЯ:
1. Прочитай запрос пользователя.
2. Найди в тексте блоки с `*Изображение:*`, которые релевантны запросу.
   - Используй `ocr_text` и `content_summary` внутри JSON для поиска.
3. Извлечь URL изображения, который находится ПОД JSON блоком.
4. Верни JSON:
```json
{
  "reasoning": "Нужен план 1 этажа для проверки коллекторов (найден в блоке *Изображение:* с content_summary 'План 1 этажа')",
  "needs_images": true,
  "image_urls": ["https://... .pdf"]
}
```
Если картинок нет или они не нужны - верни `needs_images: false`.
"""

def load_selection_prompt(data_root: Optional[Path] = None) -> str:
    """
    Загружает промт для выбора картинок из файла.
    Если файл не найден, возвращает промт по умолчанию.
    """
    default_prompt = SELECTION_PROMPT
    
    if data_root is None:
        data_root = Path.cwd() / "data"
    
    prompt_file = Path(data_root) / "selection_prompt.txt"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logger.info(f"Загружен пользовательский промт выбора из {prompt_file}")
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения файла промта выбора: {e}. Используется промт по умолчанию.")
    
    return default_prompt

def load_analysis_prompt(data_root: Optional[Path] = None) -> str:
    """
    Загружает системный промт для анализа из файла.
    Если файл не найден, возвращает промт по умолчанию.
    """
    default_prompt = """Ты — эксперт-инженер. Твоя задача — анализировать документацию.

ИНСТРУКЦИЯ ПО РАБОТЕ С ИЗОБРАЖЕНИЯМИ:
1. Тебе передают текстовые описания и ИЗОБРАЖЕНИЯ (превью).
2. Каждое изображение имеет ID (Image ID) и информацию об оригинальном размере.
3. То, что ты видишь — это уменьшенная версия (обычно до 2000px).
4. Если тебе нужно рассмотреть детали, используй инструмент ZOOM.

ФОРМАТ ЗАПРОСА ZOOM (JSON):
```json
{
  "tool": "zoom",
  "image_id": "uuid-строка-из-описания",
  "coords_px": [1000, 2000, 1500, 2500],
  "reason": "Хочу прочитать мелкий текст в центре"
}
```

ОТВЕТ:
Если информации достаточно, отвечай обычным текстом. Ссылайся на источники."""
    
    # Пытаемся найти файл с промтом
    if data_root is None:
        data_root = Path.cwd() / "data"
    
    prompt_file = Path(data_root) / "llm_system_prompt.txt"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logger.info(f"Загружен пользовательский промт из {prompt_file}")
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения файла промта: {e}. Используется промт по умолчанию.")
    
    return default_prompt

class LLMClient:
    def __init__(self, model: Optional[str] = None, data_root: Optional[Path] = None):
        self.api_key = config.OPENROUTER_API_KEY
        self.base_url = config.OPENROUTER_BASE_URL
        self.model = model or config.DEFAULT_MODEL
        self.data_root = data_root or Path.cwd() / "data"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/aizoomdoc",
            "X-Title": "AIZoomDoc"
        }
        self.history: List[Dict[str, Any]] = [] 
        # Системный промт добавляется позже, в зависимости от режима

    def encode_image(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def select_relevant_images(self, text_context: str, query: str) -> ImageSelection:
        """Спрашивает LLM, какие картинки нужны."""
        print(f"[SELECT_IMAGES] Начинаю выбор картинок для запроса: {query[:50]}")
        print(f"[SELECT_IMAGES] Размер контекста: {len(text_context)} символов")
        
        # Загружаем промт из файла (или используем дефолтный)
        selection_prompt = load_selection_prompt(self.data_root)
        
        # Передаем весь документ целиком, не обрезаем!
        messages = [
            {"role": "system", "content": selection_prompt},
            {"role": "user", "content": f"ЗАПРОС: {query}\n\nДОКУМЕНТ:\n{text_context}"}
        ]
        
        # Попытки повтора для выбора картинок
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[SELECT_IMAGES] Попытка {attempt+1}/{max_retries}")
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json={
                        "model": self.model, 
                        "messages": messages, 
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=120
                )
                
                if resp.status_code == 429:
                    print(f"[SELECT_IMAGES] ⚠️ 429 Too Many Requests. Жду 5 сек...")
                    import time
                    time.sleep(5)
                    continue
                
                resp.raise_for_status()
                response_data = resp.json()
                
                if not response_data.get("choices"):
                    continue
                
                content = response_data["choices"][0].get("message", {}).get("content", "")
                
                if not content:
                    continue
                
                # Попытка парсинга
                try:
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()
                    
                    data = json.loads(content)
                    return ImageSelection(
                        reasoning=data.get("reasoning", ""),
                        needs_images=data.get("needs_images", False),
                        image_urls=data.get("image_urls", [])
                    )
                except json.JSONDecodeError:
                    print(f"[SELECT_IMAGES] ⚠️ Ошибка JSON парсинга. Пробую еще раз...")
                    continue
                    
            except Exception as e:
                print(f"[SELECT_IMAGES] Ошибка при попытке {attempt+1}: {e}")
                if attempt == max_retries - 1:
                    return ImageSelection(reasoning=f"Ошибка API: {str(e)}", needs_images=False, image_urls=[])
        
        return ImageSelection(reasoning="Не удалось получить корректный ответ", needs_images=False, image_urls=[])

    def init_analysis_chat(self):
        """Инициализирует диалог с загруженным системным промтом."""
        analysis_prompt = load_analysis_prompt(self.data_root)
        self.history = [{"role": "system", "content": analysis_prompt}]

    def add_user_message(self, text: str, images: Optional[List[ViewportCrop]] = None):
        content = [{"type": "text", "text": text}]
        
        if images:
            for img in images:
                if img.image_path and Path(img.image_path).exists():
                    try:
                        b64 = self.encode_image(img.image_path)
                        img_id = img.target_blocks[0] if img.target_blocks else "unknown"
                        
                        desc = f"IMAGE [ID: {img_id}]. {img.description}"
                        content.append({"type": "text", "text": desc})
                        
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                        })
                    except Exception as e:
                        logger.error(f"Ошибка img: {e}")

        self.history.append({"role": "user", "content": content})

    def add_assistant_message(self, text: str):
        self.history.append({"role": "assistant", "content": text})

    def get_response(self) -> str:
        print(f"[GET_RESPONSE] Отправляю запрос к модели {self.model}")
        
        # Попытки повтора (Retries)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": self.model,
                    "messages": self.history,
                    "temperature": 0.2,
                    "max_tokens": 4000  # Увеличим лимит токенов
                }
                
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=120
                )
                
                if resp.status_code == 429:
                    print(f"[GET_RESPONSE] ⚠️ Ошибка 429 (Too Many Requests). Жду 5 секунд...")
                    import time
                    time.sleep(5)
                    continue
                
                resp.raise_for_status()
                response_data = resp.json()
                
                if not response_data.get("choices"):
                    print(f"[GET_RESPONSE] ⚠️ Попытка {attempt+1}: Нет choices в ответе")
                    continue
                
                answer = response_data["choices"][0]["message"].get("content", "")
                
                if not answer:
                    print(f"[GET_RESPONSE] ⚠️ Попытка {attempt+1}: Пустой content")
                    # Если пустой ответ - пробуем еще раз
                    continue
                
                print(f"[GET_RESPONSE] ✓ Получен ответ длиной {len(answer)} символов")
                self.add_assistant_message(answer)
                return answer
                
            except Exception as e:
                print(f"[GET_RESPONSE] Ошибка при попытке {attempt+1}: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"LLM Error after retries: {e}")
                    raise
        
        raise ValueError("Не удалось получить ответ от модели после 3 попыток")

    def parse_zoom_request(self, response_text: str) -> Optional[ZoomRequest]:
        response_text = response_text.strip()
        data = None
        
        # Попытка найти JSON внутри текста, даже если он не в начале
        json_start = response_text.find("```json")
        if json_start != -1:
            try:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
                data = json.loads(json_str)
            except: pass
        elif "```" in response_text: # Иногда модель забывает 'json'
             try:
                json_str = response_text.split("```")[1].split("```")[0].strip()
                data = json.loads(json_str)
             except: pass
        elif response_text.startswith("{"):
             try:
                data = json.loads(response_text)
             except: pass
            
        # Если найден tool: zoom, возвращаем ZoomRequest
        if data and isinstance(data, dict) and data.get("tool") == "zoom":
            return ZoomRequest(
                page_number=data.get("page_number", 0),
                image_id=data.get("image_id"),
                coords_norm=data.get("coords_norm"),
                coords_px=data.get("coords_px"),
                reason=data.get("reason", "")
            )
        return None
