"""
Клиент для взаимодействия с LLM (OpenRouter) в режиме диалога.
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import requests
import warnings

try:
    from google import genai as genai_new
    from google.genai import types as genai_types
except ImportError:
    genai_new = None
    genai_types = None

# Конвертация для обратной совместимости имен
genai = genai_new

from .config import config
from .models import ViewportCrop, ZoomRequest, ImageRequest, ImageSelection, DocumentRequest, FlashExtractedContext
from .schemas import PRO_ANSWER_SCHEMA

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
   - `raw_pdfplumber_text`: основной текст со страницы.
   - `analysis`: объект с результатами анализа, содержащий вложенный объект `analysis`:
     - `content_summary`: краткое описание.
     - `detailed_description`: подробное описание.
     - `clean_ocr_text`: распознанный текст (OCR).
     - `key_entities`: ключевые сущности.

ИНСТРУКЦИЯ:
1. Прочитай запрос пользователя.
2. Найди в тексте блоки JSON, которые релевантны запросу.
   - Используй `analysis.analysis.content_summary`, `analysis.analysis.detailed_description`, `analysis.analysis.clean_ocr_text` и `doc_metadata.page` для поиска.
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

## ФОРМАТ ОТВЕТА (JSON):

Твой ответ ВСЕГДА должен быть в формате JSON со следующими полями:

- `answer_markdown` (string, обязательно): Полный ответ на вопрос в формате Markdown.
- `summary` (string): Краткое резюме ответа (1-2 предложения).
- `counts` (array): Подсчёты объектов (если применимо), каждый: {object_type, count, locations[]}.
- `citations` (array): Ссылки на источники, каждый: {image_id, coords_norm[4], note}.
- `confidence` (string): Уверенность в ответе ("high", "medium", "low").
- `needs_more_evidence` (boolean): true если нужны дополнительные данные для более полного ответа.
- `followup_images` (array[string]): Список ID изображений для запроса (если needs_more_evidence=true).
- `followup_zooms` (array): Список запросов zoom (если needs_more_evidence=true), каждый: {image_id, coords_norm[4], reason}.

**ВАЖНО:**
- Основной ответ для пользователя пиши в поле `answer_markdown` в формате Markdown.
- Если можешь ответить с имеющимися данными, установи `needs_more_evidence=false` и оставь `followup_*` пустыми.
- Если нужны дополнительные изображения или zoom, установи `needs_more_evidence=true` и заполни `followup_images` или `followup_zooms`.
- Координаты в `coords_norm` должны быть нормализованными [0.0-1.0]: [x1, y1, x2, y2].
- `image_id` берётся из каталога изображений или из строк вида `IMAGE [ID: ...]`.

**ИНСТРУКЦИЯ ПО РАБОТЕ С ИЗОБРАЖЕНИЯМИ:**
1. Тебе передают текстовые описания и ИЗОБРАЖЕНИЯ (превью).
2. Каждое изображение имеет ID (Image ID) и информацию об оригинальном размере.
3. То, что ты видишь — это уменьшенная версия (обычно до 2000px).
4. Если тебе нужно рассмотреть детали, запроси zoom через `followup_zooms`."""
    
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

def load_zoom_prompt(data_root: Optional[Path] = None) -> str:
    """
    Загружает промт для режима ZOOM из файла.
    Если файл не найден, возвращает промт по умолчанию.
    """
    default_prompt = """Ты находишься в режиме анализа ZOOM-фрагмента (увеличенная часть изображения).
Твоя задача:
1. Внимательно изучить детали на этом фрагменте (текст, цифры, обозначения).
2. Сопоставить увиденное с предыдущим контекстом.
3. Ответить на вопрос пользователя.
"""
    
    if data_root is None:
        data_root = Path.cwd() / "data"
    
    prompt_file = Path(data_root) / "zoom_prompt.txt"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logger.info(f"Загружен пользовательский промт ZOOM из {prompt_file}")
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения файла промта ZOOM: {e}. Используется промт по умолчанию.")
    
    return default_prompt


def load_flash_extractor_prompt(data_root: Optional[Path] = None) -> str:
    """
    Загружает промт для Flash-экстрактора из файла.
    Если файл не найден, возвращает промт по умолчанию.
    """
    default_prompt = """Ты — экстрактор контекста. НЕ ОТВЕЧАЙ на вопрос пользователя.
Твоя задача — извлечь ВСЕ релевантные данные из документа для последующего анализа.

## ФОРМАТ ОТВЕТА (JSON):

Твой ответ должен быть в формате JSON со следующими полями:

- `status` (string, обязательно): "collecting" если нужно больше данных, "ready" когда контекст собран
- `reasoning` (string): Краткое объяснение хода мыслей
- `tool_calls` (array): Запросы инструментов для сбора дополнительных данных
  - Каждый элемент: {"tool": "request_images" | "zoom", "image_ids": [...], "image_id": "...", "coords_norm": [x1,y1,x2,y2], "reason": "..."}
- `relevant_blocks` (array): ID релевантных текстовых блоков (когда status="ready")
- `relevant_images` (array[string]): ID релевантных изображений (когда status="ready")

**Порядок работы:**
1. Изучи каталог изображений и запроси нужные через `request_images`
2. Если нужны детали, запроси `zoom` с нормализованными координатами [x1, y1, x2, y2]
3. Когда все данные собраны, верни `status="ready"` с `relevant_blocks` и `relevant_images`

**Важно:** Координаты в `coords_norm` должны быть в диапазоне [0.0, 1.0] относительно размеров изображения."""
    
    if data_root is None:
        data_root = Path.cwd() / "data"
    
    prompt_file = Path(data_root) / "flash_extractor_prompt.txt"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logger.info(f"Загружен промт Flash-экстрактора из {prompt_file}")
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения файла промта Flash-экстрактора: {e}. Используется промт по умолчанию.")
    
    return default_prompt

def extract_json_objects(text: str) -> List[Any]:
    """
    Пытается извлечь все JSON-объекты из текста,
    даже если они смешаны с обычным текстом и не находятся в блоках кода.
    """
    results = []
    decoder = json.JSONDecoder()
    pos = 0
    length = len(text)
    
    while pos < length:
        # Ищем начало JSON ('{' или '[')
        search_pos = pos
        # Находим первый попавшийся символ { или [
        # (упрощенно, ищем просто { так как нас интересуют объекты tools)
        idx_brace = text.find('{', search_pos)
        
        if idx_brace == -1:
            break
            
        # Пробуем распарсить
        try:
            obj, end_idx = decoder.raw_decode(text[idx_brace:])
            results.append(obj)
            pos = idx_brace + end_idx
        except json.JSONDecodeError:
            # Если не вышло, сдвигаемся на 1 символ
            pos = idx_brace + 1
            
    return results

class LLMClient:
    def __init__(self, model: Optional[str] = None, data_root: Optional[Path] = None, log_callback: Optional[callable] = None):
        # OpenRouter отключён (legacy) — все вызовы через Google Gemini SDK
        # self.api_key = config.OPENROUTER_API_KEY  # legacy
        # self.base_url = config.OPENROUTER_BASE_URL  # legacy
        self.model = model or config.DEFAULT_MODEL
        self.data_root = data_root or Path.cwd() / "data"
        self.log_callback = log_callback
        # OpenRouter headers (legacy, не используется)
        # self.headers = {
        #     "Authorization": f"Bearer {self.api_key}",
        #     "Content-Type": "application/json",
        #     "HTTP-Referer": "https://github.com/aizoomdoc",
        #     "X-Title": "AIZoomDoc"
        # }
        self.history: List[Dict[str, Any]] = [] 
        # Системный промт добавляется позже, в зависимости от режима

        # Инициализация Google SDK (обязательный)
        self.google_client = None
        if config.GOOGLE_API_KEY:
            if genai_new:
                try:
                    self.google_client = genai_new.Client(api_key=config.GOOGLE_API_KEY)
                    logger.info("Инициализирован Google GenAI SDK")
                except Exception as e:
                    logger.error(f"Ошибка инициализации Google GenAI SDK: {e}")
                    raise RuntimeError(f"Не удалось инициализировать Google GenAI SDK: {e}")
            else:
                raise RuntimeError("SDK google-genai не установлен. Установите: pip install google-genai")
        else:
            raise RuntimeError("GOOGLE_API_KEY не задан. Установите его в .env файле.")

        # Контроль контекста / кэширования
        self.current_cache = None
        self.thought_signatures: Dict[int, str] = {} # индекс в истории -> подпись
        self._context_length_cache: Dict[str, int] = {}
        self.last_usage: Optional[Dict[str, int]] = None
        self.last_usage_selection: Optional[Dict[str, int]] = None
        self.last_prompt_estimate: Optional[Dict[str, int]] = None
        self.last_prompt_estimate_selection: Optional[Dict[str, int]] = None

    def _is_google_direct(self) -> bool:
        """Проверяет, является ли модель прямой моделью Google (все модели теперь direct)."""
        return self.model in ["gemini-3-flash-preview", "gemini-3-pro-preview", "flash+pro"]

    def upload_to_google_files(self, file_path: str, display_name: str = None) -> Optional[str]:
        """
        Загружает файл в Google Files API.
        Возвращает URI файла для использования в запросах к Gemini.
        
        Args:
            file_path: Путь к локальному файлу
            display_name: Отображаемое имя файла (опционально)
            
        Returns:
            URI файла в Google Files API или None при ошибке
        """
        if not self.google_client:
            logger.error("Google GenAI SDK не инициализирован")
            return None
        
        try:
            path = Path(file_path)
            if not path.exists():
                logger.error(f"Файл не найден: {file_path}")
                return None
            
            # Определяем MIME тип
            suffix = path.suffix.lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.pdf': 'application/pdf',
            }
            mime_type = mime_types.get(suffix, 'application/octet-stream')
            
            # Загружаем файл через Google Files API
            # Google Files API принимает открытый файл, а не путь
            with open(path, 'rb') as f:
                uploaded_file = self.google_client.files.upload(
                    file=f,
                    config={
                        "display_name": display_name or path.name,
                        "mime_type": mime_type
                    }
                )
            
            # Возвращаем URI файла
            file_uri = uploaded_file.uri if hasattr(uploaded_file, 'uri') else str(uploaded_file.name)
            logger.info(f"Загружен в Google Files: {path.name} → {file_uri}")
            return file_uri
            
        except Exception as e:
            logger.error(f"Ошибка загрузки в Google Files API: {e}")
            return None

    def _call_google_direct(self, messages: List[Dict[str, Any]], temperature: float = 0.2, max_tokens: int = config.MAX_TOKENS, response_json: bool = False) -> str:
        """Вызов Google API напрямую через новый SDK."""
        if not self.google_client:
            raise RuntimeError("Google GenAI SDK не инициализирован")
            
        text, _ = self._call_google_new_sdk(messages, temperature=temperature, max_tokens=max_tokens)
        return text

    def get_model_context_length(self) -> Optional[int]:
        """
        Пытается получить длину контекста выбранной модели.
        """
        if self._is_google_direct():
            return 1000000 # 1M для Gemini 1.5
            
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
        Возвращает прогноз по текущему запросу.
        """
        est = estimate_prompt_tokens(messages)
        ctx = self.get_model_context_length()

        # Если есть кэш, токены в сообщениях (если они там были) не считаются дважды,
        # но мы упрощаем: если кэш есть, мы предполагаем что большие данные уже там.
        prompt_est = est["prompt_tokens_est"]
        
        report: Dict[str, Any] = {
            "model": self.model,
            "context_length": ctx,
            **est,
            "max_tokens": max_tokens,
            "will_overflow": None,
            "remaining_after_prompt": None,
            "remaining_after_max_completion": None,
            "cached": self.current_cache is not None
        }

        if isinstance(ctx, int) and ctx > 0:
            report["remaining_after_prompt"] = ctx - prompt_est
            report["remaining_after_max_completion"] = ctx - (prompt_est + max_tokens)
            report["will_overflow"] = (prompt_est + max_tokens) > ctx

        return report

    def encode_image(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def set_document_context(self, text_context: str):
        """
        Создает контекстный кэш для документа, если используется новый SDK.
        ВРЕМЕННО ОТКЛЮЧЕНО для прямых Google моделей (Gemini 3) из-за конфликта с tools.
        """
        if not self.google_client or not genai_new or not genai_types:
            return

        if "gemini" not in self.model.lower():
            return
        
        # Временно отключаем кэш для прямых Google моделей (Gemini 3)
        if self._is_google_direct():
            logger.info("Кэширование отключено для прямых Google моделей")
            self.current_cache = None
            return

        try:
            logger.info(f"Создание контекстного кэша для документа ({len(text_context)} симв.)")
            base_model = self.model.split("/")[-1]
            
            # В новом SDK caches.create принимает model и config
            self.current_cache = self.google_client.caches.create(
                model=base_model,
                config={
                    "contents": [genai_types.Content(role="user", parts=[genai_types.Part(text=text_context)])],
                    "ttl": "3600s",
                }
            )
            logger.info(f"Кэш создан: {self.current_cache.name}")
        except Exception as e:
            logger.error(f"Ошибка создания кэша: {e}")
            self.current_cache = None

    def select_relevant_images(self, text_context: str, query: str) -> ImageSelection:
        """Спрашивает LLM, какие картинки нужны."""
        print(f"[SELECT_IMAGES] Начинаю выбор картинок для запроса: {query[:50]}")
        
        # Если кэша еще нет, пробуем создать его сейчас
        if not self.current_cache:
            self.set_document_context(text_context)

        # Загружаем промт из файла (или используем дефолтный)
        selection_prompt = load_selection_prompt(self.data_root)
        
        # Если есть кэш, отправляем только запрос. Если нет - весь документ.
        user_content = f"ЗАПРОС: {query}"
        if not self.current_cache:
            user_content += f"\n\nДОКУМЕНТ:\n{text_context}"
        
        messages = [
            {"role": "system", "content": selection_prompt},
            {"role": "user", "content": user_content}
        ]

        # Если модель - Gemini и у нас есть новый SDK, используем его
        if self.google_client and "gemini" in self.model.lower():
            try:
                base_model = self.model.split("/")[-1]
                config_args = {
                    "temperature": 0.1,
                    "max_output_tokens": 800,
                    "response_mime_type": "application/json",
                    "system_instruction": selection_prompt
                }
                if self.current_cache:
                    config_args["cached_content"] = self.current_cache.name

                resp = self.google_client.models.generate_content(
                    model=base_model,
                    contents=[genai_types.Content(role="user", parts=[genai_types.Part(text=user_content)])],
                    config=genai_types.GenerateContentConfig(**config_args)
                )
                
                data = json.loads(resp.text)
                return ImageSelection(
                    reasoning=data.get("reasoning", ""),
                    needs_images=data.get("needs_images", False),
                    image_urls=data.get("image_urls", [])
                )
            except Exception as e:
                logger.warning(f"Ошибка нового SDK при выборе картинок: {e}")

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
                    print(f"[SELECT_IMAGES] WARNING: 429 Too Many Requests. Жду 5 сек...")
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
                    original_content = content # Сохраняем оригинал для логирования
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
                except json.JSONDecodeError as e:
                    print(f"[SELECT_IMAGES] WARNING: Ошибка JSON парсинга: {e}")
                    print(f"[SELECT_IMAGES] RAW CONTENT:\n{original_content}")
                    print(f"[SELECT_IMAGES] CLEANED CONTENT:\n{content}")
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
                # Определяем ID изображения
                img_id = img.target_blocks[0] if img.target_blocks else "unknown"
                desc = f"IMAGE [ID: {img_id}]. {img.description}"
                content.append({"type": "text", "text": desc})

                # Пытаемся использовать S3 URL если он есть
                if img.s3_url:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img.s3_url}
                    })
                elif img.image_path and Path(img.image_path).exists():
                    try:
                        b64 = self.encode_image(img.image_path)
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                        })
                    except Exception as e:
                        logger.error(f"Ошибка кодирования картинки {img_id}: {e}")
                else:
                    logger.warning(f"Изображение {img_id} не имеет ни S3 URL, ни локального пути")

        self.history.append({"role": "user", "content": content})

    def add_assistant_message(self, text: str, thought_signature: Optional[str] = None):
        idx = len(self.history)
        self.history.append({"role": "assistant", "content": text})
        if thought_signature:
            self.thought_signatures[idx] = thought_signature

    def _call_google_new_sdk(self, messages: List[Dict[str, Any]], 
                            temperature: float = 0.2, max_tokens: int = config.MAX_TOKENS,
                            response_json: bool = True, response_schema: dict = None) -> Tuple[str, Optional[str]]:
        """
        Вызов Google API через новый SDK с поддержкой кэша и подписей.
        
        Args:
            messages: История сообщений
            temperature: Температура генерации
            max_tokens: Макс токенов
            response_json: Требовать JSON ответ (по умолчанию True для единообразия)
            response_schema: JSON Schema для валидации
        """
        if not self.google_client or not genai_new:
            raise RuntimeError("Google GenAI SDK не инициализирован")

        base_model = self.model.split("/")[-1]
        
        # Конвертируем историю в формат нового SDK
        contents = []
        system_instruction = None
        
        for i, msg in enumerate(messages):
            if msg["role"] == "system":
                system_instruction = msg["content"]
                continue
                
            role = "user" if msg["role"] == "user" else "model"
            parts = []
            content = msg["content"]
            
            if isinstance(content, str):
                parts.append(genai_types.Part(text=content))
            elif isinstance(content, list):
                for p in content:
                    if p["type"] == "text":
                        parts.append(genai_types.Part(text=p["text"]))
                    elif p["type"] == "image_url":
                        url = p["image_url"]["url"]
                        if url.startswith("data:image"):
                            b64_data = url.split(",")[1]
                            image_data = base64.b64decode(b64_data)
                            parts.append(genai_types.Part(inline_data={"mime_type": "image/jpeg", "data": image_data}))
                        elif url.startswith("files/") or url.startswith("gs://") or "generativelanguage.googleapis.com/v1beta/files/" in url:
                            # Google Files API URI: передаем как file_data (без попытки скачать по HTTP)
                            parts.append(genai_types.Part(file_data={"mime_type": "image/png", "file_uri": url}))
                        else:
                            # Прямые URL (например S3) - GenAI SDK может не поддерживать напрямую через Part
                            # В таком случае лучше загрузить и передать как bytes или использовать Google Cloud Storage если есть.
                            # Но для простоты попробуем скачать если это не base64.
                            try:
                                r = requests.get(url, timeout=10)
                                if r.status_code == 200:
                                    parts.append(genai_types.Part(inline_data={"mime_type": "image/jpeg", "data": r.content}))
                            except Exception as e:
                                logger.warning(f"Не удалось скачать картинку для GenAI SDK: {e}")
            
            content_obj = genai_types.Content(role=role, parts=parts)
            # Передаем thought_signature если она была сохранена для этого сообщения
            if role == "model" and i in self.thought_signatures:
                content_obj.thought_signature = self.thought_signatures[i]
                
            contents.append(content_obj)

        config_args = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "top_p": config.LLM_TOP_P,
        }
        
        # Добавляем media_resolution для обработки изображений
        media_res_map = {
            "low": "MEDIA_RESOLUTION_LOW",
            "medium": "MEDIA_RESOLUTION_MEDIUM",
            "high": "MEDIA_RESOLUTION_HIGH",
            "ultra_high": "MEDIA_RESOLUTION_ULTRA_HIGH",
        }
        media_res = media_res_map.get(config.MEDIA_RESOLUTION.lower(), "MEDIA_RESOLUTION_HIGH")
        config_args["media_resolution"] = media_res
        
        # Нельзя использовать system_instruction вместе с cached_content
        if self.current_cache:
            config_args["cached_content"] = self.current_cache.name
        elif system_instruction:
            config_args["system_instruction"] = system_instruction
        
        # Включаем Deep Think (thinking) по настройкам конфига
        if config.THINKING_ENABLED:
            thinking_config = {"include_thoughts": True}
            if config.THINKING_BUDGET > 0:
                thinking_config["thinking_budget"] = config.THINKING_BUDGET
            config_args["thinking_config"] = thinking_config
        
        # Строгий JSON режим (по умолчанию включен)
        if response_json:
            config_args["response_mime_type"] = "application/json"
            if response_schema:
                config_args["response_schema"] = response_schema

        response = self.google_client.models.generate_content(
            model=base_model,
            contents=contents,
            config=genai_types.GenerateContentConfig(**config_args)
        )
        
        # Извлекаем текст из ответа
        text = None
        signature = None
        
        # Пробуем разные способы получить текст
        if hasattr(response, 'text') and response.text:
            text = response.text
        elif response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                parts = candidate.content.parts
                if parts:
                    text_parts = []
                    for part in parts:
                        if hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                    text = "".join(text_parts)
            if hasattr(candidate, "thought_signature"):
                signature = candidate.thought_signature
        
        if not text:
            logger.error(f"Пустой ответ от Google API. Response: {response}")
            raise ValueError("Получен пустой ответ от Google API")
            
        return text, signature

    def get_response(self) -> str:
        """
        Получает ответ от модели через Google Gemini SDK.
        Возвращает JSON-строку с ответом в формате PRO_ANSWER_SCHEMA.
        """
        print(f"[GET_RESPONSE] Отправляю запрос к модели {self.model}")
        
        # Все модели теперь работают через Google SDK (OpenRouter отключён)
        if not self.google_client:
            raise RuntimeError("Google GenAI SDK не инициализирован. Проверьте GOOGLE_API_KEY.")
        
        # Используем PRO_ANSWER_SCHEMA для всех моделей
        text, signature = self._call_google_new_sdk(
            self.history,
            response_json=True,
            response_schema=PRO_ANSWER_SCHEMA
        )
        print(f"[GET_RESPONSE] OK (GenAI SDK): Получен ответ длиной {len(text)} символов")
        self.add_assistant_message(text, thought_signature=signature)
        return text

    def update_memory_summary(self, prev_summary: str, user_message: str, assistant_message: str) -> str:
        """
        Обновляет краткую "память" диалога для длинных чатов.
        Делает отдельный запрос к модели и НЕ влияет на self.history.
        """
        system_prompt = (
            "Ты — модуль памяти диалога.\n"
            "Твоя задача: обновить краткую память (summary) по переписке.\n"
            "Правила:\n"
            "- Пиши по-русски.\n"
            "- Максимум 1200-1800 символов.\n"
            "- Только факты/решения/проверенные гипотезы/не закрытые вопросы/важные ссылки на листы/узлы.\n"
            "- Без воды, без повторов.\n"
            "- Если предыдущая память пустая — создай новую.\n"
        )
        user_payload = (
            f"ПРЕДЫДУЩАЯ ПАМЯТЬ:\n{(prev_summary or '').strip()}\n\n"
            f"НОВЫЙ ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{(user_message or '').strip()}\n\n"
            f"НОВЫЙ ОТВЕТ АССИСТЕНТА:\n{(assistant_message or '').strip()}\n\n"
            "Верни ТОЛЬКО обновлённую память (plain text)."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.1,
            "max_tokens": 600,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=60,
            )
            if resp.status_code == 429:
                return (prev_summary or "").strip()
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or not data.get("choices"):
                return (prev_summary or "").strip()
            content = data["choices"][0].get("message", {}).get("content", "")
            if not isinstance(content, str) or not content.strip():
                return (prev_summary or "").strip()
            return content.strip()
        except Exception:
            return (prev_summary or "").strip()

    def parse_zoom_request(self, response_text: str) -> List[ZoomRequest]:
        """
        Парсит запросы zoom из ответа модели.
        Поддерживает как прямой формат {"tool": "zoom", ...},
        так и вложенный {"tool_calls": [{"tool": "zoom", ...}]}.
        """
        response_text = response_text.strip()
        
        # Извлекаем все JSON-объекты
        all_objects = extract_json_objects(response_text)
        
        # Разворачиваем tool_calls если есть
        data_list = []
        for item in all_objects:
            if not isinstance(item, dict):
                continue
            # Если есть tool_calls — добавляем их содержимое
            if "tool_calls" in item and isinstance(item["tool_calls"], list):
                for tc in item["tool_calls"]:
                    if isinstance(tc, dict):
                        data_list.append(tc)
            # Также проверяем сам объект (на случай прямого формата)
            if item.get("tool"):
                data_list.append(item)

        zoom_requests = []
        for item in data_list:
            if item.get("tool") == "zoom":
                coords_norm = item.get("coords_norm")
                coords_px = item.get("coords_px")
                
                # Проверяем, является ли coords_norm массивом массивов (множественные зумы)
                if coords_norm and isinstance(coords_norm, list) and len(coords_norm) > 0:
                    # Если первый элемент - список, значит это массив зумов
                    if isinstance(coords_norm[0], list):
                        # Создаем отдельный ZoomRequest для каждого набора координат
                        for coord_set in coords_norm:
                            if isinstance(coord_set, list) and len(coord_set) == 4:
                                zoom_requests.append(ZoomRequest(
                                    page_number=item.get("page_number", 0),
                                    image_id=item.get("image_id"),
                                    coords_norm=coord_set,
                                    coords_px=None,
                                    reason=item.get("reason", "")
                                ))
                    else:
                        # Обычный одиночный зум
                        zoom_requests.append(ZoomRequest(
                            page_number=item.get("page_number", 0),
                            image_id=item.get("image_id"),
                            coords_norm=coords_norm,
                            coords_px=coords_px,
                            reason=item.get("reason", "")
                        ))
                else:
                    # Нет coords_norm, может быть coords_px
                    zoom_requests.append(ZoomRequest(
                        page_number=item.get("page_number", 0),
                        image_id=item.get("image_id"),
                        coords_norm=coords_norm,
                        coords_px=coords_px,
                        reason=item.get("reason", "")
                    ))
        return zoom_requests

    def parse_image_requests(self, response_text: str) -> List[ImageRequest]:
        """
        Ищет в ответе JSON-команды tool=request_images и возвращает список ImageRequest.
        Поддерживает как прямой формат {"tool": "request_images", ...},
        так и вложенный {"tool_calls": [{"tool": "request_images", ...}]}.
        """
        response_text = (response_text or "").strip()
        if not response_text:
            return []

        # Используем универсальный экстрактор
        data_list = extract_json_objects(response_text)

        # Разворачиваем tool_calls если есть
        all_items = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
            # Если есть tool_calls — добавляем их содержимое
            if "tool_calls" in item and isinstance(item["tool_calls"], list):
                for tc in item["tool_calls"]:
                    if isinstance(tc, dict):
                        all_items.append(tc)
            # Также проверяем сам объект (на случай прямого формата)
            if item.get("tool"):
                all_items.append(item)

        requests_out: List[ImageRequest] = []
        for item in all_items:
            if item.get("tool") != "request_images":
                continue
            ids = item.get("image_ids") or item.get("images") or item.get("ids") or []
            if isinstance(ids, str):
                ids = [ids]
            if not isinstance(ids, list):
                ids = []
            ids = [str(x) for x in ids if x]
            if not ids:
                continue
            requests_out.append(ImageRequest(image_ids=ids, reason=str(item.get("reason") or "")))

        return requests_out

    def parse_document_requests(self, response_text: str) -> List[DocumentRequest]:
        """
        Ищет в ответе JSON-команды tool=request_documents и возвращает список DocumentRequest.
        """
        response_text = (response_text or "").strip()
        if not response_text:
            return []

        data_list = extract_json_objects(response_text)
        requests_out: List[DocumentRequest] = []
        
        for item in data_list:
            if not isinstance(item, dict):
                continue
            if item.get("tool") != "request_documents":
                continue
            
            docs = item.get("documents") or item.get("docs") or []
            if isinstance(docs, str):
                docs = [docs]
            if not isinstance(docs, list):
                docs = []
            
            docs = [str(x) for x in docs if x]
            if not docs:
                continue
                
            requests_out.append(DocumentRequest(documents=docs, reason=str(item.get("reason") or "")))

        return requests_out

    def parse_flash_context(self, response_text: str) -> Optional[FlashExtractedContext]:
        """
        Парсит ответ Flash-модели и извлекает готовый контекст.
        Возвращает FlashExtractedContext если status="ready", иначе None.
        """
        response_text = (response_text or "").strip()
        if not response_text:
            return None

        data_list = extract_json_objects(response_text)
        
        for item in data_list:
            if not isinstance(item, dict):
                continue
            
            # Ищем объект со status="ready"
            if item.get("status") == "ready":
                # Поддерживаем оба формата: relevant_blocks (новый) и relevant_text_chunks (старый)
                blocks = item.get("relevant_blocks") or item.get("relevant_text_chunks") or []
                images = item.get("relevant_images") or []
                reasoning = item.get("reasoning") or ""
                
                return FlashExtractedContext(
                    relevant_blocks=blocks,
                    relevant_images=images,
                    zoom_crops=[],  # Зумы заполняются отдельно
                    flash_reasoning=reasoning
                )
        
        return None

    def call_flash_model(self, messages: List[Dict[str, Any]], temperature: float = 0.1, 
                         response_json: bool = True, response_schema: dict = None) -> str:
        """
        Вызывает Flash-модель напрямую через Google SDK.
        Используется для этапа экстракции контекста.
        
        Args:
            messages: Список сообщений в формате OpenAI
            temperature: Температура генерации
            response_json: Если True, требует JSON ответ
            response_schema: JSON Schema для валидации ответа (опционально)
        """
        if not self.google_client:
            raise RuntimeError("Google GenAI SDK не инициализирован. Проверьте GOOGLE_API_KEY.")
        
        flash_model = "gemini-3-flash-preview"
        
        # Конвертируем сообщения в формат SDK
        contents = []
        system_instruction = None
        
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
                continue
            
            role = "user" if msg["role"] == "user" else "model"
            parts = []
            content = msg["content"]
            
            if isinstance(content, str):
                parts.append(genai_types.Part(text=content))
            elif isinstance(content, list):
                for p in content:
                    if p["type"] == "text":
                        parts.append(genai_types.Part(text=p["text"]))
                    elif p["type"] == "image_url":
                        url = p["image_url"]["url"]
                        if url.startswith("data:image"):
                            b64_data = url.split(",")[1]
                            image_data = base64.b64decode(b64_data)
                            parts.append(genai_types.Part(inline_data={"mime_type": "image/jpeg", "data": image_data}))
                        elif url.startswith("files/") or url.startswith("gs://") or "generativelanguage.googleapis.com/v1beta/files/" in url:
                            parts.append(genai_types.Part(file_data={"mime_type": "image/png", "file_uri": url}))
                        else:
                            try:
                                r = requests.get(url, timeout=10)
                                if r.status_code == 200:
                                    parts.append(genai_types.Part(inline_data={"mime_type": "image/jpeg", "data": r.content}))
                            except Exception as e:
                                logger.warning(f"Не удалось скачать картинку для Flash: {e}")
            
            contents.append(genai_types.Content(role=role, parts=parts))
        
        # Маппинг media_resolution
        media_res_map = {
            "low": "MEDIA_RESOLUTION_LOW",
            "medium": "MEDIA_RESOLUTION_MEDIUM",
            "high": "MEDIA_RESOLUTION_HIGH",
            "ultra_high": "MEDIA_RESOLUTION_ULTRA_HIGH",
        }
        media_res = media_res_map.get(config.MEDIA_RESOLUTION.lower(), "MEDIA_RESOLUTION_HIGH")
        
        config_args = {
            "temperature": temperature,
            "max_output_tokens": 4096,
            "top_p": config.LLM_TOP_P,
            "media_resolution": media_res,
        }
        if system_instruction:
            config_args["system_instruction"] = system_instruction
        
        # Строгий JSON режим
        if response_json:
            config_args["response_mime_type"] = "application/json"
            if response_schema:
                config_args["response_schema"] = response_schema
        
        # Включаем thinking для Flash если настроено
        if config.THINKING_ENABLED:
            thinking_config = {"include_thoughts": True}
            if config.THINKING_BUDGET > 0:
                thinking_config["thinking_budget"] = config.THINKING_BUDGET
            config_args["thinking_config"] = thinking_config
        
        mime_type = "application/json" if response_json else "text/plain"
        logger.info(f"Flash API call: temp={temperature}, top_p={config.LLM_TOP_P}, media_res={media_res}, thinking={config.THINKING_ENABLED}, response_mime_type={mime_type}")
        
        response = self.google_client.models.generate_content(
            model=flash_model,
            contents=contents,
            config=genai_types.GenerateContentConfig(**config_args)
        )
        
        # Сохраняем usage если доступен
        if hasattr(response, 'usage_metadata'):
            self.last_usage = {
                "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0),
                "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0),
                "total_tokens": getattr(response.usage_metadata, 'total_token_count', 0),
            }
        
        # Извлекаем текст
        text = None
        if hasattr(response, 'text') and response.text:
            text = response.text
        elif response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                parts = candidate.content.parts
                if parts:
                    text_parts = [part.text for part in parts if hasattr(part, 'text') and part.text]
                    text = "".join(text_parts)
        
        if not text:
            raise ValueError("Получен пустой ответ от Flash модели")
        
        return text

    def call_pro_model(self, messages: List[Dict[str, Any]], temperature: float = None,
                        response_json: bool = True, response_schema: dict = None) -> str:
        """
        Вызывает Pro-модель напрямую через Google SDK.
        Используется для финального анализа.
        
        Args:
            messages: Список сообщений в формате OpenAI
            temperature: Температура генерации (по умолчанию из config)
            response_json: Если True, требует JSON ответ
            response_schema: JSON Schema для валидации ответа (опционально)
        """
        if not self.google_client:
            raise RuntimeError("Google GenAI SDK не инициализирован. Проверьте GOOGLE_API_KEY.")
        
        pro_model = "gemini-3-pro-preview"
        
        # Конвертируем сообщения в формат SDK
        contents = []
        system_instruction = None
        
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
                continue
            
            role = "user" if msg["role"] == "user" else "model"
            parts = []
            content = msg["content"]
            
            if isinstance(content, str):
                parts.append(genai_types.Part(text=content))
            elif isinstance(content, list):
                for p in content:
                    if p["type"] == "text":
                        parts.append(genai_types.Part(text=p["text"]))
                    elif p["type"] == "image_url":
                        url = p["image_url"]["url"]
                        if url.startswith("data:image"):
                            b64_data = url.split(",")[1]
                            image_data = base64.b64decode(b64_data)
                            parts.append(genai_types.Part(inline_data={"mime_type": "image/jpeg", "data": image_data}))
                        elif url.startswith("files/") or url.startswith("gs://") or "generativelanguage.googleapis.com/v1beta/files/" in url:
                            parts.append(genai_types.Part(file_data={"mime_type": "image/png", "file_uri": url}))
                        else:
                            try:
                                r = requests.get(url, timeout=10)
                                if r.status_code == 200:
                                    parts.append(genai_types.Part(inline_data={"mime_type": "image/jpeg", "data": r.content}))
                            except Exception as e:
                                logger.warning(f"Не удалось скачать картинку для Pro: {e}")
            
            contents.append(genai_types.Content(role=role, parts=parts))
        
        # Маппинг media_resolution
        media_res_map = {
            "low": "MEDIA_RESOLUTION_LOW",
            "medium": "MEDIA_RESOLUTION_MEDIUM",
            "high": "MEDIA_RESOLUTION_HIGH",
            "ultra_high": "MEDIA_RESOLUTION_ULTRA_HIGH",
        }
        media_res = media_res_map.get(config.MEDIA_RESOLUTION.lower(), "MEDIA_RESOLUTION_HIGH")
        
        # Используем temperature из config если не передан явно
        temp = temperature if temperature is not None else config.LLM_TEMPERATURE
        
        config_args = {
            "temperature": temp,
            "max_output_tokens": config.MAX_TOKENS,
            "top_p": config.LLM_TOP_P,
            "media_resolution": media_res,
        }
        if system_instruction:
            config_args["system_instruction"] = system_instruction
        
        # Строгий JSON режим
        if response_json:
            config_args["response_mime_type"] = "application/json"
            if response_schema:
                config_args["response_schema"] = response_schema
        
        # Включаем thinking для Pro если настроено
        if config.THINKING_ENABLED:
            thinking_config = {"include_thoughts": True}
            if config.THINKING_BUDGET > 0:
                thinking_config["thinking_budget"] = config.THINKING_BUDGET
            config_args["thinking_config"] = thinking_config
        
        mime_type = "application/json" if response_json else "text/plain"
        logger.info(f"Pro API call: temp={temp}, top_p={config.LLM_TOP_P}, media_res={media_res}, thinking={config.THINKING_ENABLED}, response_mime_type={mime_type}")
        
        response = self.google_client.models.generate_content(
            model=pro_model,
            contents=contents,
            config=genai_types.GenerateContentConfig(**config_args)
        )
        
        # Сохраняем usage если доступен
        if hasattr(response, 'usage_metadata'):
            self.last_usage = {
                "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0),
                "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0),
                "total_tokens": getattr(response.usage_metadata, 'total_token_count', 0),
            }
        
        # Извлекаем текст
        text = None
        if hasattr(response, 'text') and response.text:
            text = response.text
        elif response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                parts = candidate.content.parts
                if parts:
                    text_parts = [part.text for part in parts if hasattr(part, 'text') and part.text]
                    text = "".join(text_parts)
        
        if not text:
            raise ValueError("Получен пустой ответ от Pro модели")
        
        return text
