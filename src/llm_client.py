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


def _estimate_tokens_for_text(text: str) -> int:
    """
    Грубая оценка токенов по размеру текста.

    Важно: это НЕ точный токенайзер конкретной модели. Используется только для прогноза.
    """
    if not text:
        return 0
    # Эвристика: ~4 байта UTF‑8 на 1 токен (приблизительно).
    return max(1, int(len(text.encode("utf-8")) / 4))


def estimate_prompt_tokens(messages: List[Dict[str, Any]], image_token_cost: int = 1200) -> Dict[str, int]:
    """
    Грубая оценка prompt-токенов для messages в OpenAI-compatible chat формате.

    - Текст считаем по эвристике.
    - Картинки считаем как фиксированную стоимость (очень грубо), т.к. base64/URL не отражают реальную стоимость vision-токенов.
    """
    text_tokens = 0
    image_count = 0

    for msg in messages:
        content = msg.get("content", "")
        # OpenRouter принимает и строку, и multimodal list.
        if isinstance(content, str):
            text_tokens += _estimate_tokens_for_text(content)
            continue

        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text_tokens += _estimate_tokens_for_text(part.get("text", ""))
                elif part.get("type") == "image_url":
                    image_count += 1

    image_tokens = image_count * max(0, int(image_token_cost))
    return {
        "text_tokens_est": text_tokens,
        "image_count": image_count,
        "image_tokens_est": image_tokens,
        "prompt_tokens_est": text_tokens + image_tokens,
    }

# Промт для этапа 1: Выбор картинок
SELECTION_PROMPT = """Ты — ассистент по анализу технической документации.
Твоя задача — найти в тексте ИЗОБРАЖЕНИЯ, необходимые для ответа на запрос пользователя.

ВАЖНО ПРО СТРУКТУРУ ДОКУМЕНТА:
1. Документ содержит блоки описания изображений в формате JSON.
2. Каждый блок содержит:
   - `doc_metadata`: метаданные (имя файла, номер страницы).
   - `image`: объект с полем `uri` — ПРЯМАЯ ССЫЛКА на изображение.
   - `analysis`: объект с результатами анализа, содержащий вложенный объект `analysis`:
     - `content_summary`: краткое описание.
     - `detailed_description`: подробное описание.
     - `clean_ocr_text`: распознанный текст (OCR).
     - `key_entities`: ключевые сущности.

ИНСТРУКЦИЯ:
1. Прочитай запрос пользователя.
2. Найди в тексте блоки JSON, которые релевантны запросу.
   - Используй `content_summary`, `detailed_description`, `clean_ocr_text` и `doc_metadata.page` для поиска.
3. Извлеки URL изображения из поля `image.uri` внутри найденного JSON блока.
4. Верни JSON:
```json
{
  "reasoning": "Нужен план 1 этажа (найден блок на стр. 9 с описанием 'Ситуационный план')",
  "needs_images": true,
  "image_urls": ["https://..."]
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

ПОРЯДОК РАБОТЫ (ОБЯЗАТЕЛЬНО ПЕРЕД ОТВЕТОМ):
1. Сначала тщательно изучи текстовую информацию и таблицы (включая спецификации и OCR‑текст).
2. Затем внимательно изучи изображения и, при необходимости, запроси ZOOM и изучи зумы.
3. Сопоставь данные из текста/таблиц и изображений/зумов и только после этого формулируй выводы и ответ.

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

        # Контроль контекста / usage
        self._context_length_cache: Dict[str, int] = {}
        self.last_usage: Optional[Dict[str, int]] = None
        self.last_usage_selection: Optional[Dict[str, int]] = None
        self.last_prompt_estimate: Optional[Dict[str, int]] = None
        self.last_prompt_estimate_selection: Optional[Dict[str, int]] = None

    def get_model_context_length(self) -> Optional[int]:
        """
        Пытается получить длину контекста выбранной модели через OpenRouter /models.
        Кэширует результат.
        """
        if self.model in self._context_length_cache:
            return self._context_length_cache[self.model]

        try:
            resp = requests.get(
                f"{self.base_url}/models",
                headers=self.headers,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data") or data.get("models") or []
            for m in models:
                if isinstance(m, dict) and m.get("id") == self.model:
                    ctx = m.get("context_length") or m.get("context_length_tokens") or m.get("context") or None
                    if isinstance(ctx, int) and ctx > 0:
                        self._context_length_cache[self.model] = ctx
                        return ctx
        except Exception as e:
            logger.warning(f"Не удалось получить context_length модели {self.model}: {e}")

        return None

    def build_context_report(self, messages: List[Dict[str, Any]], max_tokens: int) -> Dict[str, Any]:
        """
        Возвращает прогноз по текущему запросу:
        - оценка prompt токенов
        - лимит контекста (если удалось получить)
        - сколько осталось / риск переполнения
        """
        est = estimate_prompt_tokens(messages)
        ctx = self.get_model_context_length()

        report: Dict[str, Any] = {
            "model": self.model,
            "context_length": ctx,
            **est,
            "max_tokens": max_tokens,
            "will_overflow": None,
            "remaining_after_prompt": None,
            "remaining_after_max_completion": None,
        }

        if isinstance(ctx, int) and ctx > 0:
            report["remaining_after_prompt"] = ctx - est["prompt_tokens_est"]
            report["remaining_after_max_completion"] = ctx - (est["prompt_tokens_est"] + max_tokens)
            report["will_overflow"] = (est["prompt_tokens_est"] + max_tokens) > ctx

        return report

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

        # Прогноз (очень грубо)
        self.last_prompt_estimate_selection = self.build_context_report(messages, max_tokens=800)
        
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
                        "max_tokens": 800,
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
                self.last_usage_selection = response_data.get("usage") if isinstance(response_data, dict) else None
                
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

                # Прогноз (очень грубо)
                self.last_prompt_estimate = self.build_context_report(self.history, max_tokens=payload["max_tokens"])
                
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
                self.last_usage = response_data.get("usage") if isinstance(response_data, dict) else None
                
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

    def parse_zoom_request(self, response_text: str) -> List[ZoomRequest]:
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
        elif response_text.startswith("{") or response_text.startswith("["):
             try:
                data = json.loads(response_text)
             except: pass
            
        # Превращаем в список, если это один объект
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            return []
            
        zoom_requests = []
        for item in data_list:
            if isinstance(item, dict) and item.get("tool") == "zoom":
                zoom_requests.append(ZoomRequest(
                    page_number=item.get("page_number", 0),
                    image_id=item.get("image_id"),
                    coords_norm=item.get("coords_norm"),
                    coords_px=item.get("coords_px"),
                    reason=item.get("reason", "")
                ))
        return zoom_requests
