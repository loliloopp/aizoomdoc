"""
Клиент для взаимодействия с LLM (OpenRouter) в режиме диалога.
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests
from google import genai
from google.genai import types

from .config import config
from .models import ViewportCrop, ZoomRequest, ImageRequest, ImageSelection

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


def estimate_prompt_tokens(messages: List[Dict[str, Any]], image_token_cost: int = 120) -> Dict[str, int]:
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
    Загружает системный промт для анализа (Часть 1: Общая логика).
    """
    default_prompt = """Ты — эксперт-инженер. Твоя задача — анализировать документацию.

ПОРЯДОК РАБОТЫ (ОБЯЗАТЕЛЬНО ПЕРЕД ОТВЕТОМ):
1. Изучи текстовую информацию и каталог изображений.
2. Если для ответа нужны визуальные данные, ЗАПРОСИ изображения (tool: request_images). Ты можешь запрашивать ЛЮБОЕ количество изображений (хоть все сразу), если это нужно для полноты анализа.
3. Изучи полученные изображения (тебе придут полные версии или превью).
4. Если на превью не видны детали или ты не уверен в анализе на 100% — ОБЯЗАТЕЛЬНО запроси ZOOM (tool: zoom) для конкретных узлов.
5. Сформулируй ответ только тогда, когда изучил все критические данные.

ИНСТРУКЦИЯ ПО РАБОТЕ С ИЗОБРАЖЕНИЯМИ:
1. Изначально ты видишь только ОПИСАНИЯ в каталоге. Сами картинки не загружены.
2. Чтобы увидеть чертеж/схему, используй `request_images`. Количество `image_ids` не ограничено.

ФОРМАТ ЗАПРОСА ИЗОБРАЖЕНИЙ (JSON):
```json
{
  "tool": "request_images",
  "image_ids": ["image_id_1", "image_id_2", "..."],
  "reason": "Нужно изучить все листы принципиальных схем и планов для выявления нестыковок"
}
```

ВАЖНО:
- `image_id`/`image_ids` бери ТОЛЬКО из каталога.
- Не выдумывай ID, которых нет в каталоге.
 Ссылайся на источники."""
    
    if data_root is None:
        data_root = Path.cwd() / "data"
    
    prompt_file = Path(data_root) / "llm_system_prompt.txt"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения llm_system_prompt.txt: {e}")
    
    return default_prompt

def load_zoom_prompt(data_root: Optional[Path] = None) -> str:
    """
    Загружает системный промт для ZOOM (Часть 2: Техническая инструкция).
    """
    default_prompt = """ИНСТРУКЦИЯ ПО ZOOM:
1. Если на превью не видны детали или ты не уверен в анализе на 100% — ОБЯЗАТЕЛЬНО запроси ZOOM (tool: zoom).
2. Если после первого ZOOM картина не ясна или нужно проверить соседний узел — запрашивай ZOOM ПОВТОРНО. Не делай окончательных выводов на основе догадок.
3. Получив изображение, ты увидишь его целиком (или сжатое превью до 2000px).
4. Если детали слишком мелкие или текст неразборчив, используй `zoom` для получения фрагмента в исходном качестве.
5. НЕ используй `zoom` для просмотра всего листа целиком (например `coords_norm: [0,0,1,1]`). Для этого есть `request_images`.
6. ТРЕБУЙ дополнительные зумы до тех пор, пока не будешь ТВЕРДО УБЕЖДЕН в своем анализе.

ФОРМАТ ЗАПРОСА ZOOM (JSON):
```json
{
  "tool": "zoom",
  "image_id": "image_id_1",
  "coords_px": [1000, 2000, 1500, 2500],
  "reason": "Неразборчивый текст в таблице"
}
```"""
    
    if data_root is None:
        data_root = Path.cwd() / "data"
    
    prompt_file = Path(data_root) / "zoom_prompt.txt"
    
    if prompt_file.exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения zoom_prompt.txt: {e}")
    
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

        # Инициализация Google Gemini
        self.google_client = None
        if config.GOOGLE_API_KEY:
            self.google_client = genai.Client(api_key=config.GOOGLE_API_KEY)

        # Контроль контекста / usage
        self._context_length_cache: Dict[str, int] = {}
        self.last_usage: Optional[Dict[str, int]] = None
        self.last_usage_selection: Optional[Dict[str, int]] = None
        self.last_prompt_estimate: Optional[Dict[str, int]] = None
        self.last_prompt_estimate_selection: Optional[Dict[str, int]] = None

    def _is_google_direct(self) -> bool:
        """Проверяет, является ли модель прямой моделью Google."""
        return self.model in ["gemini-3-flash-preview", "gemini-3-pro-preview"]

    def _call_google_direct(self, messages: List[Dict[str, Any]], temperature: float = 0.2, max_tokens: int = 4000, response_json: bool = False) -> str:
        """Вызов нового Google GenAI API с обработкой лимитов (429)."""
        if not self.google_client:
            raise ValueError("GOOGLE_API_KEY не настроен")

        import time
        max_retries = 3
        delay = 15 # Для бесплатного уровня Gemini нужно ждать заметно

        for attempt in range(max_retries):
            try:
                google_contents = []
                system_instruction = None
                
                for msg in messages:
                    if msg["role"] == "system":
                        system_instruction = msg["content"]
                        continue
                    
                    parts = []
                    content = msg["content"]
                    if isinstance(content, str):
                        parts.append(types.Part.from_text(text=content))
                    elif isinstance(content, list):
                        for part in content:
                            if part["type"] == "text":
                                parts.append(types.Part.from_text(text=part["text"]))
                            elif part["type"] == "image_url":
                                # Извлекаем base64
                                url = part["image_url"]["url"]
                                if url.startswith("data:image"):
                                    b64_data = url.split(",")[1]
                                    image_data = base64.b64decode(b64_data)
                                    parts.append(types.Part.from_bytes(data=image_data, mime_type="image/jpeg"))
                    
                    google_contents.append(types.Content(
                        role="user" if msg["role"] == "user" else "model", 
                        parts=parts
                    ))
                
                config_params = {
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                }
                if system_instruction:
                    config_params["system_instruction"] = system_instruction
                if response_json:
                    config_params["response_mime_type"] = "application/json"

                response = self.google_client.models.generate_content(
                    model=self.model,
                    contents=google_contents,
                    config=types.GenerateContentConfig(**config_params)
                )
                return response.text
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "resource_exhausted" in err_str:
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ Лимит Google API (429). Попытка {attempt+1}, жду {delay}с...")
                        time.sleep(delay)
                        continue
                raise e
        
        raise ValueError("Не удалось получить ответ от Google API после повторов")

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
        
        # Если модель прямая от Google
        if self._is_google_direct():
            try:
                print(f"[SELECT_IMAGES] Прямой вызов Google API для {self.model}")
                content = self._call_google_direct(
                    messages, 
                    temperature=0.1, 
                    max_tokens=800, 
                    response_json=True
                )
                
                # Попытка парсинга
                original_content = content
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
            except Exception as e:
                print(f"[SELECT_IMAGES] ⚠️ Ошибка прямого вызова Google: {e}")
                # Проваливаемся в общую логику (хотя она тоже может не сработать если это не OpenRouter)

        # Попытки повтора для выбора картинок (OpenRouter)
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
                    print(f"[SELECT_IMAGES] ⚠️ Ошибка JSON парсинга: {e}")
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
        
        # Если модель прямая от Google
        if self._is_google_direct():
            try:
                print(f"[GET_RESPONSE] Прямой вызов Google API для {self.model}")
                answer = self._call_google_direct(
                    self.history,
                    temperature=0.2,
                    max_tokens=50000
                )
                if not answer:
                    raise ValueError("Пустой ответ от Google API")
                
                print(f"[GET_RESPONSE] ✓ Получен ответ длиной {len(answer)} символов")
                self.add_assistant_message(answer)
                return answer
            except Exception as e:
                print(f"[GET_RESPONSE] ⚠️ Ошибка прямого вызова Google: {e}")
                raise

        # Попытки повтора (Retries) для OpenRouter
        max_retries = 3
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": self.model,
                    "messages": self.history,
                    "temperature": 0.2,
                    "max_tokens": 50000  # Увеличим лимит токенов
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
                    print(f"[GET_RESPONSE] RAW RESPONSE: {response_data}")
                    if attempt < max_retries - 1:
                        print("[GET_RESPONSE] Жду 10 сек перед повтором...")
                        import time
                        time.sleep(10)
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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]

        if self._is_google_direct():
            try:
                return self._call_google_direct(messages, temperature=0.1, max_tokens=600).strip()
            except Exception:
                return (prev_summary or "").strip()

        payload = {
            "model": self.model,
            "messages": messages,
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
        response_text = response_text.strip()
        data = None
        
        # Попытка найти JSON внутри текста, даже если он не в начале
        json_start = response_text.find("```json")
        if json_start != -1:
            try:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
                data = json.loads(json_str)
            except Exception as e:
                print(f"[ZOOM_PARSE] ⚠️ Ошибка в блоке ```json: {e}")
        elif "```" in response_text: # Иногда модель забывает 'json'
             try:
                json_str = response_text.split("```")[1].split("```")[0].strip()
                data = json.loads(json_str)
             except Exception as e:
                print(f"[ZOOM_PARSE] ⚠️ Ошибка в блоке ```: {e}")
        elif response_text.startswith("{") or response_text.startswith("["):
             try:
                data = json.loads(response_text)
             except Exception as e:
                print(f"[ZOOM_PARSE] ⚠️ Ошибка raw JSON: {e}")
            
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

    def parse_image_requests(self, response_text: str) -> List[ImageRequest]:
        """
        Ищет в ответе JSON-команды tool=request_images и возвращает список ImageRequest.
        Поддерживает:
        - один объект
        - список объектов
        - JSON внутри ```json``` или ```...```
        """
        response_text = (response_text or "").strip()
        if not response_text:
            return []

        data_list: List[dict] = []

        # 1) JSON в fenced blocks
        json_blocks = re.findall(r"```json\s*(\{.*?\}|\[.*?\])\s*```", response_text, re.DOTALL | re.IGNORECASE)
        if not json_blocks:
            json_blocks = re.findall(r"```\s*(\{.*?\}|\[.*?\])\s*```", response_text, re.DOTALL)

        for block in json_blocks:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict):
                    data_list.append(parsed)
                elif isinstance(parsed, list):
                    data_list.extend([x for x in parsed if isinstance(x, dict)])
            except Exception as e:
                print(f"[IMG_REQ_PARSE] ⚠️ Ошибка парсинга json блока: {e}", flush=True)

        # 2) raw json (редко, но бывает)
        if not data_list and (response_text.startswith("{") or response_text.startswith("[")):
            try:
                parsed = json.loads(response_text)
                if isinstance(parsed, dict):
                    data_list.append(parsed)
                elif isinstance(parsed, list):
                    data_list.extend([x for x in parsed if isinstance(x, dict)])
            except Exception:
                pass

        requests_out: List[ImageRequest] = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
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
