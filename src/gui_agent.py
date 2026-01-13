"""
Адаптер агента для работы в GUI (PyQt6).
С поддержкой выбора md файлов из GUI.
"""

import logging
import json
import uuid
import asyncio
import copy
from pathlib import Path
from datetime import datetime
from typing import List
from PyQt6.QtCore import QThread, pyqtSignal

from .config import config
from .llm_client import LLMClient
from .image_processor import ImageProcessor
from .markdown_parser import MarkdownParser
from .file_processor import FileProcessor
from .html_ocr_processor import HtmlOcrProcessor
from .supabase_client import supabase_client
from .s3_storage import s3_storage
from .schemas import PRO_ANSWER_SCHEMA, FLASH_EXTRACTOR_SCHEMA

logger = logging.getLogger(__name__)

class AgentWorker(QThread):
    sig_log = pyqtSignal(str)
    sig_message = pyqtSignal(str, str, str)  # role, content, model
    sig_image = pyqtSignal(str, str)
    sig_finished = pyqtSignal()
    sig_error = pyqtSignal(str)
    sig_history_saved = pyqtSignal(str, str)
    sig_usage = pyqtSignal(int, int) # used, remaining
    
    def __init__(self, data_root: Path, query: str, model: str, md_files: List[str] = None, 
                 existing_chat_id: str = None, existing_db_chat_id: str = None, md_mode: str = "full_md",
                 user_prompt: str = None):
        super().__init__()
        self.data_root = data_root
        self.query = query
        self.model = model
        self.md_files = md_files or []
        # Режим RAG убран — всегда используем full_md
        self.md_mode = "full_md"
        self.user_prompt = user_prompt
        self.is_running = True
        
        # Счетчик токенов для текущего чата
        self.total_tokens_used = 0
        
        if existing_chat_id:
            self.chat_id = existing_chat_id
            self.is_new_chat = False
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.chat_id = f"{timestamp}_{uuid.uuid4().hex[:6]}"
            self.is_new_chat = True
        
        self.chat_dir = data_root / "chats" / self.chat_id
        self.images_dir = self.chat_dir / "images"
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # Определяем имя файла лога с инкрементальным индексом для каждого запроса
        log_idx = 1
        while (self.chat_dir / f"full_log_{log_idx}.txt").exists():
            log_idx += 1
        self.full_log_path = self.chat_dir / f"full_log_{log_idx}.txt"
        
        self.db_chat_id = existing_db_chat_id
        
        # Загружаем токены из БД для существующего чата
        if not self.is_new_chat and self.db_chat_id and supabase_client.is_connected():
            try:
                chat_data = asyncio.run(supabase_client.get_chat(self.db_chat_id))
                if chat_data and chat_data.get("metadata"):
                    metadata = chat_data["metadata"]
                    self.total_tokens_used = metadata.get("total_tokens", 0)
            except Exception as e:
                logger.error(f"Ошибка загрузки токенов из БД: {e}")
        
        if self.is_new_chat:
            self.chat_history_data = {
                "id": self.chat_id,
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "query": query,
                "model": model,
                "md_files": self.md_files,
                "messages": []
            }
        else:
            # Загружаем существующую историю
            history_path = self.chat_dir / "history.json"
            if history_path.exists():
                with open(history_path, "r", encoding="utf-8") as f:
                    self.chat_history_data = json.load(f)
                    # Восстанавливаем список файлов из истории, если он не передан явно
                    if not self.md_files and "md_files" in self.chat_history_data:
                        self.md_files = self.chat_history_data["md_files"]
            else:
                self.chat_history_data = {
                    "id": self.chat_id,
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                    "query": query,
                    "model": model,
                    "md_files": self.md_files,
                    "messages": []
                }

    def save_message(self, role: str, content: str, images: list = None):
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        # Сохраняем модель для сообщений ассистента
        if role == "assistant":
            msg["model"] = self.model
            
        if images:
            msg["images"] = [img.image_path for img in images if img.image_path]
        
        self.chat_history_data["messages"].append(msg)
        self._save_to_disk()
        
        # Сохранение в БД и S3
        # БД считается основной всегда, но работаем только если есть подключение
        if supabase_client.is_connected():
            try:
                # В БД модель пока не сохраняем (нет поля в схеме),
                # но она есть в metadata чата (общая для чата)
                db_role = role
                if role == "system":
                    db_role = "assistant"
                    if not content.startswith("⚠️") and not content.startswith("SYSTEM ALERT:"):
                        content = "SYSTEM ALERT: " + content

                asyncio.run(self._save_to_db(db_role, content, images, model=msg.get("model")))
            except Exception as e:
                logger.error(f"Ошибка сохранения в БД: {e}")

    async def _save_to_db(self, role: str, content: str, images: list = None, model: str = None):
        """Асинхронное сохранение сообщения и картинок в Supabase и S3."""
        try:
            if not self.db_chat_id:
                logger.warning("Supabase chat_id не инициализирован, сохранение невозможно")
                return

            # 1. Добавляем сообщение
            msg_id = await supabase_client.add_message(
                chat_id=self.db_chat_id,
                role=role,
                content=content,
                model=model
            )
            
            if not msg_id:
                logger.warning("Не удалось сохранить сообщение в Supabase")
                return
            
            self._current_msg_id = msg_id # Сохраняем для привязки результатов поиска

            # 2. Если есть картинки - загружаем в S3 и регистрируем
            if images:
                processed_paths = set()
                for img in images:
                    if not img.image_path or not Path(img.image_path).exists():
                        continue
                    
                    if img.image_path in processed_paths:
                        continue
                    processed_paths.add(img.image_path)
                        
                    # Генерируем путь в S3
                    img_type = "zoom_crop" if img.is_zoom_request else "viewport"
                    filename = Path(img.image_path).name
                    s3_key = s3_storage.generate_s3_path(self.db_chat_id, img_type, filename)
                    
                    # Загружаем в S3
                    try:
                        if getattr(img, 's3_url', None):
                            s3_url = img.s3_url
                        else:
                            s3_url = await s3_storage.upload_file(img.image_path, s3_key)
                        
                        if s3_url:
                            # Регистрируем в БД (это также создает запись в storage_files)
                            await supabase_client.add_image_to_message(
                                chat_id=self.db_chat_id,
                                message_id=msg_id,
                                image_name=filename,
                                s3_path=s3_key,
                                s3_url=s3_url,
                                image_type=img_type,
                                description=img.description
                            )
                            
                            # ПРОВЕРКА: Если это превью, загружаем также и оригинал (full)
                            if "_preview.png" in img.image_path:
                                full_path = img.image_path.replace("_preview.png", "_full.png")
                                if Path(full_path).exists():
                                    s3_full_key = s3_key.replace("_preview.png", "_full.png")
                                    await s3_storage.upload_file(full_path, s3_full_key)
                                    # Просто регистрируем в хранилище файлов
                                    await supabase_client.register_file(
                                        user_id="default_user",
                                        source_type="llm_generated",
                                        filename=Path(full_path).name,
                                        storage_path=s3_full_key
                                    )
                        else:
                            logger.error(f"Не удалось загрузить {filename} в S3 (s3_url is None)")
                    except Exception as upload_err:
                        logger.error(f"Ошибка загрузки/регистрации изображения {filename}: {upload_err}")
                        
        except Exception as e:
            logger.error(f"Критическая ошибка в _save_to_db: {e}", exc_info=True)

    def _save_gui_search_log(self, query, text_snippets, doc_index):
        """Сохраняет лог поиска для GUI-версии."""
        import datetime
        from .doc_index import tokenize_query
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.data_root / f"search_log_gui_{timestamp}.md"
        
        try:
            tokens = tokenize_query(query)
            relevant_pages = sorted(list(set(
                entry.page for entry in doc_index.images.values() 
                if entry.page is not None and any(t in entry.searchable_text().lower() for t in tokens)
            )))

            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"# Лог поиска (GUI): {query}\n\n")
                
                f.write("## 1. Запрос\n")
                f.write(f"{query}\n\n")
                
                f.write("## 2. Ключевые слова-синонимы (токены)\n")
                f.write(f"{', '.join(tokens)}\n\n")
                
                f.write("## 3. Список релевантных текстовых блоков\n")
                if text_snippets:
                    for i, (chunk_id, text) in enumerate(text_snippets, 1):
                        f.write(f"### Блок {i} (ID: {chunk_id})\n")
                        f.write(f"{text}\n\n")
                else:
                    f.write("Текстовые блоки не найдены.\n\n")
                
                f.write("## 4. Релевантные изображения из каталога\n")
                # Ищем изображения, в которых есть токены запроса
                found_images = False
                for entry in doc_index.images.values():
                    if any(t in entry.searchable_text().lower() for t in tokens):
                        f.write(f"- **{entry.image_id}** (стр. {entry.page})\n")
                        f.write(f"  - Описание: {entry.content_summary}\n")
                        f.write(f"  - Ссылка: {entry.uri}\n")
                        found_images = True
                if not found_images:
                    f.write("Релевантные изображения в каталоге не найдены.\n")
                
                f.write("\n## 5. Релевантные страницы (на основе поиска по каталогу)\n")
                if relevant_pages:
                    f.write(f"{', '.join(map(str, relevant_pages))}\n")
                else:
                    f.write("Релевантные страницы не определены.\n")
            
            logger.info(f"Лог поиска сохранен: {log_path.absolute()}")
            print(f"--- SEARCH LOG SAVED: {log_path.absolute()} ---")
            self.sig_log.emit(f"Лог поиска сохранен: {log_path.name}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении лога поиска (GUI): {e}")

    def _upload_images_to_s3(self, images: List):
        """Синхронная обертка для загрузки списка картинок в S3 для LLM."""
        if not s3_storage.is_connected():
            return
            
        async def _upload_all():
            tasks = []
            for img in images:
                if img.image_path and Path(img.image_path).exists() and not getattr(img, 's3_url', None):
                    img_type = "zoom_crop" if getattr(img, 'is_zoom_request', False) else "viewport"
                    filename = Path(img.image_path).name
                    chat_id_for_path = self.db_chat_id or self.chat_id
                    s3_key = s3_storage.generate_s3_path(chat_id_for_path, img_type, filename)
                    tasks.append((img, s3_storage.upload_file(img.image_path, s3_key)))
            
            if not tasks:
                return

            # Загружаем параллельно для скорости
            for img, task in tasks:
                url = await task
                if url:
                    img.s3_url = url
                    logger.info(f"Изображение {Path(img.image_path).name} загружено в S3: {url}")

        try:
            asyncio.run(_upload_all())
        except Exception as e:
            logger.error(f"Ошибка массовой загрузки в S3: {e}")

    def _upload_images_to_google_files(self, images: List, llm_client) -> None:
        """
        Загружает изображения в Google Files API для использования в Gemini.
        Устанавливает google_file_uri в каждом изображении.
        """
        for img in images:
            if not img.image_path or not Path(img.image_path).exists():
                continue
            
            if getattr(img, 'google_file_uri', None):
                continue  # Уже загружено
            
            try:
                display_name = Path(img.image_path).name
                uri = llm_client.upload_to_google_files(img.image_path, display_name)
                if uri:
                    img.google_file_uri = uri
                    self.sig_log.emit(f"→ Google Files: {display_name}")
            except Exception as e:
                logger.error(f"Ошибка загрузки {img.image_path} в Google Files: {e}")

    def _update_tokens(self, tokens_to_add: int):
        """Добавляет токены к общему счетчику и обновляет БД."""
        self.total_tokens_used += tokens_to_add
        
        # Обновляем счетчик в UI
        # Используем фиксированный лимит контекста для отображения
        ctx_limit = 1_000_000  # 1M токенов для Gemini
        remaining = max(0, ctx_limit - self.total_tokens_used)
        self.sig_usage.emit(self.total_tokens_used, remaining)
        
        # Сохраняем в БД
        if self.db_chat_id and supabase_client.is_connected():
            try:
                asyncio.run(supabase_client.update_chat(
                    self.db_chat_id,
                    {"metadata": {"total_tokens": self.total_tokens_used}}
                ))
            except Exception as e:
                logger.error(f"Ошибка обновления токенов в БД: {e}")

    def _save_to_disk(self):
        history_path = self.chat_dir / "history.json"
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(self.chat_history_data, f, indent=2, ensure_ascii=False)
        self.sig_history_saved.emit(self.chat_id, self.query)

    def _log_full(self, header: str, content: object):
        try:
            with open(self.full_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*20} {header} {'='*20}\n")
                if isinstance(content, (dict, list)):
                    f.write(json.dumps(content, indent=2, ensure_ascii=False))
                else:
                    f.write(str(content))
                f.write("\n")
        except Exception as e:
            logger.error(f"Failed to write full log: {e}")

    def _append_app_log(self, text: str):
        try:
            with open(self.full_log_path, "a", encoding="utf-8") as f:
                f.write(f"{text}\n")
        except: pass

    def _sanitize_messages_for_log(self, messages: list) -> list:
        """Очищает сообщения от длинных base64 данных для логирования."""
        import copy
        sanitized = []
        for msg in messages:
            msg_copy = copy.deepcopy(msg)
            content = msg_copy.get("content", "")
            
            if isinstance(content, str):
                if len(content) > 5000:
                    msg_copy["content"] = f"<{len(content)} chars, truncated...>\n{content[:2000]}..."
            elif isinstance(content, list):
                new_content = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            txt = part.get("text", "")
                            if len(txt) > 3000:
                                new_content.append({"type": "text", "text": f"<{len(txt)} chars truncated...>\n{txt[:1500]}..."})
                            else:
                                new_content.append(part)
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                new_content.append({"type": "image_url", "image_url": {"url": f"<base64 image, {len(url)} chars>"}})
                            else:
                                new_content.append({"type": "image_url", "image_url": {"url": url[:200]}})
                        else:
                            new_content.append(part)
                    else:
                        new_content.append(part)
                msg_copy["content"] = new_content
            
            sanitized.append(msg_copy)
        return sanitized

    def run(self):
        try:
            # 0. Инициализация (лог файлов)
            attached_files_info = "Нет прикрепленных файлов."
            if self.md_files:
                attached_files_info = "Прикрепленные файлы:\n" + "\n".join([str(Path(p).name) for p in self.md_files])
            elif Path(config.get_document_paths(self.data_root)[0]).exists():
                 p = Path(config.get_document_paths(self.data_root)[0])
                 attached_files_info = f"Прикрепленный файл (auto): {p.name}"

            self._log_full("ИНФОРМАЦИЯ О ФАЙЛАХ", attached_files_info)
            self._log_full("Запрос пользователя", self.query)
            
            self.sig_log.emit(f"Старт чата {self.chat_id}...")
            self._current_msg_id = None # Для привязки блоков к сообщению
            
            # 0. Инициализация чата в Supabase (только для новых чатов)
            if not self.db_chat_id and supabase_client.is_connected():
                try:
                    title = self.query[:100]
                    self.db_chat_id = asyncio.run(supabase_client.create_chat(
                        title=title,
                        user_id="default_user",
                        description=self.query,
                        metadata={
                            "local_chat_id": self.chat_id,
                            "model": self.model,
                            "md_files": self.md_files
                        }
                    ))
                    if self.db_chat_id:
                        self.sig_log.emit(f"Чат зарегистрирован в облаке: {self.db_chat_id}")
                except Exception as e:
                    logger.error(f"Ошибка создания чата в Supabase: {e}")

            image_processor = ImageProcessor(self.data_root)
            image_processor.temp_dir = self.images_dir
            
            self.current_step = 0

            def llm_log_callback(phase, data):
                log_data = data
                try:
                    # Санитизация для логов: скрываем огромный текст файлов
                    if phase == "request" and isinstance(data, dict) and "messages" in data:
                        log_data = copy.deepcopy(data)
                        for msg in log_data.get("messages", []):
                            content = msg.get("content", "")
                            if isinstance(content, str) and len(content) > 2000:
                                msg["content"] = f"<{len(content)} chars truncated. See attached files list at the beginning of the log...>"
                            elif isinstance(content, list): # Multimodal
                                for part in content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        txt = part.get("text", "")
                                        if len(txt) > 2000:
                                            part["text"] = f"<{len(txt)} chars truncated. See attached files list...>"
                                    elif isinstance(part, dict) and part.get("type") == "image_url":
                                        # Можно также сократить base64 если он там есть
                                        url = part.get("image_url", {}).get("url", "")
                                        if len(url) > 500:
                                            part["image_url"]["url"] = f"<{len(url)} chars base64 truncated>"
                except Exception as e:
                    logger.warning(f"Ошибка санитизации лога: {e}")

                if phase == "request":
                    self._log_full(f"Запрос к LLM №{self.current_step}", log_data)
                elif phase == "response":
                    self._log_full(f"Ответный запрос от LLM №{self.current_step}", log_data)
                    self._append_app_log(f"\n{'='*20} Ответ от приложения №{self.current_step} {'='*20}")

            llm_client = LLMClient(model=self.model, data_root=self.data_root, log_callback=llm_log_callback)
            
            # Инициализируем диалог с историей, если она есть
            from .llm_client import load_analysis_prompt, load_zoom_prompt
            analysis_prompt = load_analysis_prompt(self.data_root)
            zoom_prompt = load_zoom_prompt(self.data_root)
            
            # Формируем начальный системный промт: Пользовательский -> Системный 1 -> JSON -> HTML
            full_system_prompt = ""
            if self.user_prompt:
                full_system_prompt += f"ИНСТРУКЦИЯ ПОЛЬЗОВАТЕЛЯ (РОЛЬ): {self.user_prompt}\n\n"
            full_system_prompt += f"СИСТЕМНАЯ ИНСТРУКЦИЯ (АНАЛИЗ):\n{analysis_prompt}"
            
            # Добавляем промты для JSON и HTML файлов
            json_prompt_path = self.data_root / "json_annotation_prompt.txt"
            if json_prompt_path.exists():
                try:
                    json_prompt = json_prompt_path.read_text(encoding="utf-8")
                    full_system_prompt += f"\n\n{json_prompt}"
                    self.sig_log.emit("Загружен промт для JSON")
                except Exception as e:
                    logger.error(f"Ошибка загрузки json_annotation_prompt.txt: {e}")
            
            html_prompt_path = self.data_root / "html_ocr_prompt.txt"
            if html_prompt_path.exists():
                try:
                    html_prompt = html_prompt_path.read_text(encoding="utf-8")
                    full_system_prompt += f"\n\n{html_prompt}"
                    self.sig_log.emit("Загружен промт для HTML")
                except Exception as e:
                    logger.error(f"Ошибка загрузки html_ocr_prompt.txt: {e}")
            
            full_system_prompt += "\n\nIMPORTANT SYSTEM NOTE: DISABLE ALL NATIVE TOOLS. DO NOT USE FUNCTION CALLING. OUTPUT ONLY TEXT OR MARKDOWN."
            
            llm_client.history = [{"role": "system", "content": full_system_prompt}]

            # Краткая память диалога (устойчиво для длинных чатов)
            memory_path = self.chat_dir / "memory.txt"
            if memory_path.exists():
                try:
                    memory_text = memory_path.read_text(encoding="utf-8").strip()
                    if memory_text:
                        llm_client.history.append(
                            {"role": "system", "content": f"КРАТКАЯ ПАМЯТЬ ДИАЛОГА (обновляется автоматически):\n{memory_text}"}
                        )
                except Exception as e:
                    logger.warning(f"Не удалось прочитать memory.txt: {e}")

            # Для истории добавляем только последние сообщения (остальное сжимается в memory.txt).
            # Это предотвращает рост контекста в бесконечном диалоге.
            history_messages = self.chat_history_data.get("messages", [])
            tail_n = 12
            for msg in history_messages[-tail_n:]:
                llm_client.history.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

            # Если указаны конкретные md файлы через GUI - используем их
            full_text = ""
            all_blocks = []
            attached_images = []  # Инициализируем до if/else
            
            # Отладка В ТЕРМИНАЛ
            print(f"[DEBUG] self.md_files = {self.md_files}")
            print(f"[DEBUG] len(self.md_files) = {len(self.md_files) if self.md_files else 0}")
            
            # ВАЖНО: Если мы продолжаем чат, нам все равно нужен текст документа в контексте.
            # Для варианта A мы просто заново читаем файлы.
            if self.md_files:
                print(f"[DEBUG] Начинаю обработку {len(self.md_files)} файлов")
                self.sig_log.emit(f"Используются выбранные файлы: {len(self.md_files)}")
                
                for file_path_str in self.md_files:
                    try:
                        file_path = Path(file_path_str)
                        print(f"[DEBUG] Читаю файл: {file_path}")
                        print(f"[DEBUG] Файл существует: {file_path.exists()}")
                        self.sig_log.emit(f"Читаю: {file_path}")
                        
                        # Загружаем файл в S3 и регистрируем в БД
                        if self.db_chat_id:
                            try:
                                s3_doc_key = s3_storage.generate_s3_path(self.db_chat_id, "document", file_path.name)
                                s3_url = asyncio.run(s3_storage.upload_file(str(file_path), s3_doc_key))
                                
                                asyncio.run(supabase_client.register_file(
                                    user_id="default_user",
                                    source_type="user_upload",
                                    filename=file_path.name,
                                    storage_path=s3_doc_key,
                                    external_url=s3_url
                                ))
                            except Exception as e:
                                logger.error(f"Ошибка загрузки/регистрации файла: {e}")

                        # Обрабатываем файл в зависимости от типа
                        print(f"[DEBUG] Вызываю FileProcessor.process_file...")
                        text, blocks, image = FileProcessor.process_file(file_path, self.db_chat_id)
                        
                        print(f"[DEBUG] FileProcessor вернул: text={len(text)} chars, blocks={len(blocks) if blocks else 0}, image={image is not None}")
                        
                        # Отладка
                        self.sig_log.emit(f"  → Получено текста: {len(text)} символов, блоков: {len(blocks) if blocks else 0}")
                        
                        # Добавляем текст в контекст
                        full_text += text
                        print(f"[DEBUG] full_text после добавления: {len(full_text)} chars")
                        
                        # Добавляем блоки (для .md файлов)
                        if blocks:
                            all_blocks.extend(blocks)
                            self.sig_log.emit(f"Прочитано блоков: {len(blocks)}")
                        
                        # Для изображений - добавляем в список для передачи в LLM
                        if image:
                            # Загружаем изображение в S3
                            if self.db_chat_id:
                                try:
                                    s3_img_key = s3_storage.generate_s3_path(
                                        self.db_chat_id, 
                                        "document", 
                                        file_path.name
                                    )
                                    s3_img_url = asyncio.run(s3_storage.upload_file(
                                        str(file_path), 
                                        s3_img_key,
                                        content_type=f"image/{file_path.suffix[1:]}"
                                    ))
                                    image.s3_url = s3_img_url
                                except Exception as e:
                                    logger.error(f"Ошибка загрузки изображения в S3: {e}")
                            
                            attached_images.append(image)
                            self.sig_log.emit(f"Изображение добавлено: {file_path.name}")

                    except Exception as e:
                        print(f"[DEBUG] ❌ ИСКЛЮЧЕНИЕ при обработке файла: {e}")
                        import traceback
                        print(traceback.format_exc())
                        self.sig_log.emit(f"Ошибка чтения {file_path_str}: {e}")
                        import traceback
                        self.sig_log.emit(traceback.format_exc())
            else:
                # По умолчанию берем result.md
                print(f"[DEBUG] Ищу result.md в {self.data_root}")
                self.sig_log.emit(f"Ищу result.md в {self.data_root}")
                markdown_path, _ = config.get_document_paths(self.data_root)
                print(f"[DEBUG] Путь: {markdown_path}, Существует: {Path(markdown_path).exists()}")
                self.sig_log.emit(f"  Путь: {markdown_path}")
                self.sig_log.emit(f"  Существует: {Path(markdown_path).exists()}")
                
                if Path(markdown_path).exists():
                    parser = MarkdownParser(markdown_path)
                    blocks = parser.parse()
                    all_blocks = blocks
                    
                    # Заполняем full_text из блоков
                    for block in blocks:
                        full_text += block.text + "\n\n"
                    
                    # Если парсер не извлек текст, читаем файл напрямую
                    if not full_text.strip():
                        full_text = Path(markdown_path).read_text(encoding='utf-8')
                        self.sig_log.emit(f"  → Прочитано {len(full_text)} символов напрямую")
                    else:
                        self.sig_log.emit(f"  → Извлечено {len(full_text)} символов из {len(blocks)} блоков")
                else:
                    self.sig_log.emit(f"  ⚠️ result.md НЕ НАЙДЕН!")
                    
                    # Загружаем MD в S3
                    if self.db_chat_id:
                        try:
                            s3_doc_key = s3_storage.generate_s3_path(self.db_chat_id, "document", Path(markdown_path).name)
                            s3_url = asyncio.run(s3_storage.upload_file(str(markdown_path), s3_doc_key))
                            asyncio.run(supabase_client.register_file(
                                user_id="default_user",
                                source_type="user_upload",
                                filename=Path(markdown_path).name,
                                storage_path=s3_doc_key,
                                external_url=s3_url
                            ))
                        except: pass

                    for block in blocks:
                        full_text += block.text + "\n\n"
                        
                        if self.db_chat_id:
                            try:
                                asyncio.run(supabase_client.add_search_result(
                                    chat_id=self.db_chat_id,
                                    message_id=None,
                                    block_id=block.block_id,
                                    block_text=block.text[:1000]
                                ))
                            except: pass
            
            # Проверка наличия данных ТОЛЬКО если нет прикрепленных файлов вообще
            if not self.md_files and not attached_images:
                # Проверяем, есть ли дефолтный result.md
                markdown_path, _ = config.get_document_paths(self.data_root)
                if not Path(markdown_path).exists():
                    # Отладка
                    print(f"[DEBUG] ❌ Нет прикрепленных файлов и result.md не найден!")
                    print(f"[DEBUG]   md_files: {self.md_files}")
                    print(f"[DEBUG]   attached_images: {len(attached_images)}")
                    
                    self.sig_log.emit(f"❌ Ошибка: нет файлов для анализа")
                    self.sig_log.emit(f"  md_files: {self.md_files}")
                    self.sig_log.emit(f"  result.md path: {markdown_path}")
                    
                    raise ValueError("В чате нет прикрепленных документов для анализа. Прикрепите файлы (md, jpg, png, html, json) или изображения.")
            
            # Если есть только изображения без текста — это допустимо (например, кроп PDF)

            # 1. Читаем и регистрируем MD файлы
            full_md_text = ""
            all_blocks = []
            
            # Собираем список файлов для обработки
            files_to_process = []
            if self.md_files:
                files_to_process = self.md_files
            else:
                markdown_path, _ = config.get_document_paths(self.data_root)
                if Path(markdown_path).exists():
                    files_to_process = [str(markdown_path)]

            for md_path_str in files_to_process:
                try:
                    md_path = Path(md_path_str)
                    self.sig_log.emit(f"Обработка: {md_path.name}")
                    
                    # Регистрация в S3/DB
                    if self.db_chat_id:
                        try:
                            s3_doc_key = s3_storage.generate_s3_path(self.db_chat_id, "document", md_path.name)
                            s3_url = asyncio.run(s3_storage.upload_file(str(md_path), s3_doc_key))
                            asyncio.run(supabase_client.register_file(
                                user_id="default_user",
                                source_type="user_upload",
                                filename=md_path.name,
                                storage_path=s3_doc_key,
                                external_url=s3_url
                            ))
                        except: pass

                    # Чтение текста
                    if md_path.suffix.lower() == '.html':
                        llm_text, _ = HtmlOcrProcessor.process(md_path)
                        full_md_text += llm_text + "\n\n"
                    else:
                        text = md_path.read_text(encoding="utf-8")
                        full_md_text += text + "\n\n"
                    
                    # Парсинг блоков для RAG и поиска
                    if md_path.suffix.lower() == '.md':
                        parser = MarkdownParser(md_path)
                        all_blocks.extend(parser.parse())
                except Exception as e:
                    self.sig_log.emit(f"Ошибка файла {md_path_str}: {e}")

            if not full_md_text.strip():
                # Требуем текст для индексации
                if not full_text.strip():
                    raise ValueError("Нет текста документов для анализа.")
                # Используем full_text из первого прохода
                full_md_text = full_text
            
            # Если нет текста, но есть изображения — это режим "только изображения"
            only_images_mode = (not full_md_text.strip() and attached_images)
            
            if only_images_mode:
                self.sig_log.emit("📷 Режим: Только изображения (без текстового контекста)")
                # Пропускаем индексацию, сразу передаём запрос + изображения в LLM
                context = f"ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n{self.query}\n\nОтветь на основе прикреплённых изображений."
                
                # Сохраняем сообщение пользователя
                self.save_message("user", self.query, images=None)
                
                # Передаём изображения в LLM
                llm_client.add_user_message(context, images=attached_images)
                
                # Получаем ответ (JSON)
                response_json = llm_client.get_response()
                
                # Парсим JSON и извлекаем answer_markdown
                try:
                    response_data = json.loads(response_json)
                    answer_text = response_data.get("answer_markdown", "")
                    if not answer_text or not answer_text.strip():
                        answer_text = "⚠️ Модель не вернула ответ (answer_markdown пустой)"
                except json.JSONDecodeError as e:
                    answer_text = f"⚠️ Ошибка парсинга JSON: {e}\n\nСырой ответ:\n{response_json}"
                
                self.sig_message.emit("assistant", answer_text, self.model)
                self.save_message("assistant", answer_text, images=None)
                
                self.sig_finished.emit()
                return

            # ===== РЕЖИМ FLASH + PRO =====
            if self.model == "flash+pro":
                self.sig_log.emit("🔄 Режим: Flash + Pro (двухэтапная обработка)")
                self._run_flash_pro_mode(
                    full_md_text=full_md_text,
                    files_to_process=files_to_process,
                    attached_images=attached_images if 'attached_images' in locals() else [],
                    all_blocks=all_blocks
                )
                return

            # ===== ПОДГОТОВКА КОНТЕКСТА =====
            
            from .doc_index import build_index, strip_json_blocks, ImageCatalogEntry
            from .json_annotation_processor import JsonAnnotationProcessor
            doc_index = build_index(full_md_text)
            
            # Добавляем изображения из JSON и HTML файлов в каталог
            for md_path_str in files_to_process:
                md_path = Path(md_path_str)
                suffix = md_path.suffix.lower()
                
                if suffix == '.json':
                    try:
                        _, annotation = JsonAnnotationProcessor.process(md_path)
                        if annotation:
                            for img_block in annotation.image_blocks:
                                # Добавляем ID из JSON в каталог изображений
                                entry = ImageCatalogEntry(
                                    image_id=img_block.block_id,
                                    page=img_block.page_number,
                                    uri=img_block.crop_url or "",
                                    content_summary=img_block.content_summary or "",
                                    detailed_description=img_block.detailed_description or "",
                                    clean_ocr_text=img_block.ocr_text or "",
                                    key_entities=img_block.key_entities or []
                                )
                                doc_index.images[img_block.block_id] = entry
                            self.sig_log.emit(f"Добавлено {len(annotation.image_blocks)} изображений из JSON в каталог")
                    except Exception as e:
                        logger.error(f"Ошибка добавления изображений из JSON {md_path}: {e}")
                
                elif suffix == '.html':
                    try:
                        _, document = HtmlOcrProcessor.process(md_path)
                        if document:
                            for img_block in document.image_blocks:
                                entry = ImageCatalogEntry(
                                    image_id=img_block.block_id,
                                    page=img_block.page_number,
                                    uri=img_block.crop_url or "",
                                    content_summary=img_block.content_summary or "",
                                    detailed_description=img_block.detailed_description or "",
                                    clean_ocr_text=img_block.ocr_text or "",
                                    key_entities=img_block.key_entities or [],
                                    sheet_name=img_block.sheet_name or ""
                                )
                                doc_index.images[img_block.block_id] = entry
                            self.sig_log.emit(f"Добавлено {len(document.image_blocks)} изображений из HTML в каталог")
                    except Exception as e:
                        logger.error(f"Ошибка добавления изображений из HTML {md_path}: {e}")
                
                elif suffix == '.md':
                    # Парсинг нового MD формата (_document.md)
                    try:
                        md_image_blocks = FileProcessor.parse_md_image_blocks(md_path)
                        for img_block in md_image_blocks:
                            entry = ImageCatalogEntry(
                                image_id=img_block.block_id,
                                page=img_block.page_number,
                                uri=img_block.crop_url or "",
                                content_summary=img_block.content_summary or "",
                                detailed_description=img_block.detailed_description or "",
                                clean_ocr_text=img_block.ocr_text or "",
                                key_entities=img_block.key_entities or [],
                                sheet_name=img_block.sheet_name or "",
                                local_path=img_block.local_path or ""
                            )
                            doc_index.images[img_block.block_id] = entry
                        if md_image_blocks:
                            self.sig_log.emit(f"Добавлено {len(md_image_blocks)} изображений из MD в каталог")
                    except Exception as e:
                        logger.error(f"Ошибка добавления изображений из MD {md_path}: {e}")
            
            tail_n = 12 # Начальный размер истории
            context = ""
            
            # Цикл формирования контекста с попыткой впихнуть максимум
            while tail_n >= 0:
                # Очищаем историю для новой попытки
                llm_client.history = [{"role": "system", "content": full_system_prompt}]
                
                if memory_path.exists():
                    try:
                        mem = memory_path.read_text(encoding="utf-8").strip()
                        if mem: llm_client.history.append({"role": "system", "content": f"КРАТКАЯ ПАМЯТЬ: {mem}"})
                    except: pass
                
                # Добавляем хвост истории
                history_messages = self.chat_history_data.get("messages", [])
                for msg in history_messages[-(tail_n if tail_n > 0 else 0):] if tail_n > 0 else []:
                    llm_client.history.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

                # Режим full_md (RAG удалён)
                self.sig_log.emit(f"Режим: Полный MD (history_n={tail_n})...")
                
                doc_text = strip_json_blocks(full_md_text)
                # Кэшируем документ для Gemini если еще не кэширован
                if not llm_client.current_cache:
                    llm_client.set_document_context(doc_text)
                
                img_entries = sorted(doc_index.images.values(), key=lambda e: ((e.page or 0), e.image_id))
                catalog_text = "\n".join([f"- {e.image_id} (стр. {e.page}): {e.content_summary[:150]}" for e in img_entries])
                
                # Если кэш активен, не шлем текст документа повторно в сообщениях
                doc_prefix = "" if llm_client.current_cache else f"ПОЛНЫЙ ТЕКСТ ДОКУМЕНТА:\n{doc_text}\n\n"
                
                context = (
                    f"{doc_prefix}"
                    f"КАТАЛОГ ИЗОБРАЖЕНИЙ:\n{catalog_text}\n\n"
                    f"ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n{self.query}\n\n"
                    f"Используй tool=request_images и tool=zoom для работы с графикой."
                )

                # Проверяем, влезает ли
                temp_history = llm_client.history + [{"role": "user", "content": context}]
                est = llm_client.build_context_report(temp_history, max_tokens=config.MAX_TOKENS)
                
                if not est.get("will_overflow"):
                    self.sig_log.emit(f"OK: Промпт ~{est.get('prompt_tokens_est')} токенов.")
                    break
                
                if tail_n == 0:
                    # Переполнение даже без истории — ошибка (RAG fallback удалён)
                    raise ValueError("Документ слишком большой для контекста модели. Используйте режим flash+pro для автоматического сжатия.")
                
                tail_n -= 3 # Уменьшаем историю и пробуем снова
                self.sig_log.emit(f"⚠️ Переполнение. Сокращаю историю до {tail_n}...")

            self.save_message("user", self.query, images=None)
            
            # Сохранение результатов поиска в БД (пакетно)
            if self.db_chat_id and hasattr(self, '_current_msg_id') and self._current_msg_id:
                bulk_data = [{"chat_id": self.db_chat_id, "message_id": self._current_msg_id, "block_id": b.block_id, "block_text": b.text[:1000]} for b in all_blocks]
                if bulk_data:
                    try: asyncio.run(supabase_client.add_search_results_bulk(bulk_data))
                    except: pass

            # Передаём прикреплённые изображения (если есть) вместе с контекстом
            llm_client.add_user_message(context, images=attached_images if 'attached_images' in locals() else None)
            
            step = 0
            max_steps = 10
            # Какие изображения (full/preview) уже были отправлены модели в этом запуске.
            # Нужно, чтобы ZOOM выполнялся только после того, как модель увидела базовую картинку.
            sent_image_ids = set()
            
            # Отслеживание повторных запросов одних и тех же несуществующих ID
            last_missing_ids = set()
            missing_repeat_count = 0
            max_missing_repeats = 3
            
            while step < max_steps and self.is_running:
                step += 1
                self.current_step = step
                self.sig_log.emit(f"Шаг {step}...")

                # Прогноз по контексту
                try:
                    est = llm_client.last_prompt_estimate or llm_client.build_context_report(llm_client.history, max_tokens=config.MAX_TOKENS)
                    if est and est.get("will_overflow"):
                        self.sig_log.emit("⚠️ Риск переполнения контекста на текущем шаге!")
                except: pass
                
                try:
                    response_json = llm_client.get_response()
                except Exception as e:
                    if "context_length" in str(e).lower():
                        err = "Критическое переполнение контекста. Попробуйте режим RAG или другую модель."
                        self.sig_log.emit(f"❌ {err}")
                        self.save_message("system", err)
                        raise ValueError(err)
                    raise e
                
                # Парсим JSON ответ
                try:
                    response_data = json.loads(response_json)
                except json.JSONDecodeError as e:
                    err = f"⚠️ Ошибка парсинга JSON от модели: {e}"
                    self.sig_log.emit(err)
                    self.sig_message.emit("assistant", f"{err}\n\nСырой ответ:\n{response_json[:500]}", self.model)
                    self.save_message("assistant", err)
                    break
                
                # Извлекаем answer_markdown для показа пользователю
                answer_markdown = response_data.get("answer_markdown", "")
                needs_more_evidence = response_data.get("needs_more_evidence", False)
                followup_images = response_data.get("followup_images", [])
                followup_zooms = response_data.get("followup_zooms", [])
                
                # Показываем ответ пользователю (если есть)
                if answer_markdown and answer_markdown.strip():
                    self.sig_message.emit("assistant", answer_markdown, self.model)
                    self.save_message("assistant", answer_markdown)
                
                # Факт по usage (анализ)
                try:
                    usage = llm_client.last_usage
                    if isinstance(usage, dict) and usage.get("prompt_tokens") is not None:
                        pt = usage.get("prompt_tokens")
                        ct = usage.get("completion_tokens")
                        tt = usage.get("total_tokens")
                        ctx = llm_client.get_model_context_length()
                        rem = (ctx - pt) if (isinstance(ctx, int) and isinstance(pt, int)) else None
                        self.sig_log.emit(
                            f"[Контекст/факт][анализ] prompt={pt}, completion={ct}, total={tt}, "
                            f"лимит={ctx if ctx is not None else 'неизв.'}, остаток={rem if rem is not None else 'неизв.'}"
                        )
                        if isinstance(tt, int) and tt > 0:
                            self._update_tokens(tt)
                except Exception:
                    pass
                
                # Флаг, указывающий, что был выполнен какой-то инструмент (images, zoom) и нужно продолжать цикл
                tools_executed = False

                # 1) Обрабатываем запросы на подгрузку изображений из followup_images
                if followup_images and needs_more_evidence:
                    # Собираем уникальные id
                    req_ids = []
                    for rid in followup_images:
                        rid = str(rid).strip()
                        if rid.endswith(".pdf"):
                            rid = rid[:-4]
                        if rid and rid not in req_ids:
                            req_ids.append(rid)

                    info_msg = f"🖼️ Запрошены изображения: {', '.join(req_ids[:15])}{' ...' if len(req_ids) > 15 else ''}"
                    self.sig_log.emit(f"LLM запросила изображения: {req_ids}")
                    self._append_app_log(f"Запрошены изображения: {req_ids}")
                    self.sig_message.emit("assistant", info_msg, self.model)
                    self.save_message("assistant", info_msg)

                    downloaded_imgs = []
                    missing_ids = []
                    for rid in req_ids:
                        if not self.is_running:
                            return
                        entry = doc_index.images.get(rid)
                        if not entry:
                            missing_ids.append(rid)
                            continue
                        self.sig_log.emit(f"Скачивание (по id): {rid}")
                        self._append_app_log(f"Скачивание (по id): {rid}")
                        
                        # Используем локальный путь если нет URI
                        image_source = entry.uri if entry.uri else entry.local_path
                        if not image_source:
                            self._append_app_log(f"  ⚠️ Нет источника изображения: {rid}")
                            missing_ids.append(rid)
                            continue
                        
                        # Получаем список (превью + возможные авто-зумы)
                        crops = image_processor.download_and_process_pdf(image_source, image_id=rid)
                        if crops:
                            downloaded_imgs.extend(crops)
                            sent_image_ids.add(str(rid))
                            for c in crops:
                                if c.image_path:
                                    self.sig_image.emit(c.image_path, f"Image ID: {rid}")

                    if missing_ids:
                        # Проверяем, повторяются ли те же ID
                        current_missing = set(missing_ids)
                        if current_missing == last_missing_ids:
                            missing_repeat_count += 1
                            if missing_repeat_count >= max_missing_repeats:
                                err_msg = f"⚠️ Модель {max_missing_repeats} раза запрашивает несуществующие ID: {', '.join(sorted(current_missing)[:10])}. Прерываю цикл."
                                self.sig_log.emit(err_msg)
                                self._append_app_log(err_msg)
                                
                                # Отправляем финальное сообщение с объяснением
                                final_msg = (
                                    f"{err_msg}\n\n"
                                    f"**Доступные изображения в каталоге:**\n"
                                    f"{chr(10).join([f'- {img_id}' for img_id in sorted(doc_index.images.keys())[:20]])}"
                                    f"{chr(10)}... всего {len(doc_index.images)} изображений"
                                )
                                self.sig_message.emit("system", final_msg, None)
                                self.save_message("system", final_msg)
                                break  # Выходим из цикла
                        else:
                            last_missing_ids = current_missing
                            missing_repeat_count = 1
                        
                        warn = f"⚠️ Не найдено в каталоге: {', '.join(missing_ids[:10])}{' ...' if len(missing_ids) > 10 else ''}"
                        self.sig_log.emit(warn)
                        self._append_app_log(warn)
                        self.save_message("assistant", warn)

                    if downloaded_imgs:
                        # Загружаем в S3 для LLM (чтобы избежать 503 и лимитов на размер запроса)
                        self._upload_images_to_s3(downloaded_imgs)

                        # Формируем сообщение
                        msg_text = "🖼️ Загружены изображения по запросу модели."
                        
                        # Так как мы отправляем только ссылки, можем передать все изображения без ограничений
                        self.save_message("assistant", msg_text, images=downloaded_imgs)
                        llm_client.add_user_message(msg_text, images=downloaded_imgs)
                        
                        tools_executed = True
                    else:
                        # Нечего показывать модели — продолжаем, чтобы она могла переформулировать запрос
                        llm_client.add_user_message("Не удалось загрузить запрошенные изображения. Попробуй указать другие image_ids из каталога.")
                        tools_executed = True

                # 2) Обрабатываем запросы zoom из followup_zooms
                # Конвертируем followup_zooms в ZoomRequest объекты для совместимости
                zoom_reqs = []
                if followup_zooms and needs_more_evidence:
                    for fz in followup_zooms:
                        zoom_req = ZoomRequest(
                            image_id=fz.get("image_id"),
                            coords_norm=fz.get("coords_norm"),
                            coords_px=None,
                            reason=fz.get("reason", "Детальный анализ")
                        )
                        zoom_reqs.append(zoom_req)
                
                print(f"[GUI_AGENT] Zoom запросов: {len(zoom_reqs)}")
                
                if zoom_reqs:
                    tools_executed = True
                    self._append_app_log(f"LLM Tool Call: Zoom ({len(zoom_reqs)} requests)")
                    
                    # Логирование деталей зума для отладки
                    for i, zr in enumerate(zoom_reqs):
                        is_full = False
                        try:
                            if zr.coords_norm:
                                x1, y1, x2, y2 = zr.coords_norm
                                if x1 <= 0.01 and y1 <= 0.01 and x2 >= 0.99 and y2 >= 0.99:
                                    is_full = True
                        except: pass

                        type_str = "Full Image" if is_full else "Crop"
                        detail_log = f"Request #{i+1} ({type_str}): ImageID={zr.image_id}, "
                        if zr.coords_norm:
                            detail_log += f"Coords(Norm)={zr.coords_norm}, "
                        if zr.coords_px:
                            detail_log += f"Coords(Px)={zr.coords_px}, "
                        detail_log += f"Reason={zr.reason}"
                        self._append_app_log(detail_log)

                    # При запросе зума добавляем системный промт 2 (ZOOM инструкции)
                    llm_client.history.append({"role": "system", "content": f"ТЕХНИЧЕСКАЯ ИНСТРУКЦИЯ ПО ZOOM:\n{zoom_prompt}"})
                    
                    # 0) Если модель просит ZOOM до того, как увидела базовую картинку (full/preview),
                    # или просит "zoom на весь лист" (coords_norm 0..1), мы НЕ выполняем zoom.
                    # Вместо этого сначала отправляем базовое изображение и просим уточнить координаты.
                    need_base_ids = []
                    need_refine_ids = []

                    def _is_full_frame_norm(coords_norm) -> bool:
                        try:
                            if not coords_norm or len(coords_norm) != 4:
                                return False
                            x1, y1, x2, y2 = coords_norm
                            # Толеранс, чтобы отлавливать [0,0,1,1] и близкие варианты.
                            return (x1 <= 0.01 and y1 <= 0.01 and x2 >= 0.99 and y2 >= 0.99)
                        except Exception:
                            return False

                    # Собираем, какие image_id требуют базового изображения и/или уточнения координат.
                    for zr in zoom_reqs:
                        img_id = getattr(zr, "image_id", None)
                        if isinstance(img_id, str) and img_id.endswith(".pdf"):
                            img_id = img_id[:-4]
                            zr.image_id = img_id

                        if not isinstance(img_id, str) or not img_id.strip():
                            continue

                        if img_id not in sent_image_ids:
                            # Проверяем, нужно ли скачивать базовую картинку
                            # Но НЕ добавляем в need_base_ids, если мы уже собираемся делать zoom сейчас.
                            # Вместо этого просто убеждаемся, что она скачана, чтобы process_zoom_request сработал.
                            
                            # Логика need_base_ids была нужна для того, чтобы ПОКАЗАТЬ пользователю и модели
                            # общий план ПЕРЕД тем, как показывать зумы. Это полезно.
                            # Но continue прерывает выполнение зумов.
                            # Изменим так: если нужны базовые картинки, мы их скачиваем, ПОКАЗЫВАЕМ,
                            # но НЕ прерываем цикл, а идем дальше к зумам.
                            
                            if img_id not in need_base_ids:
                                need_base_ids.append(img_id)

                        # Запрещаем "zoom на весь лист" — это по сути request_images.
                        if _is_full_frame_norm(getattr(zr, "coords_norm", None)) or (not zr.coords_norm and not zr.coords_px):
                            if img_id not in need_refine_ids:
                                need_refine_ids.append(img_id)

                    # Если не было базовой картинки — отправляем её.
                    # Раньше тут был continue, который прерывал зумы. Убираем его.
                    if need_base_ids:
                        base_imgs = []
                        missing_ids = []
                        for img_id in need_base_ids:
                            if not self.is_running:
                                return
                            entry = doc_index.images.get(img_id)
                            if not entry:
                                missing_ids.append(img_id)
                                continue
                            self.sig_log.emit(f"Подгружаю базовое изображение перед zoom: {img_id}")
                            self._append_app_log(f"Подгружаю базовое изображение перед zoom: {img_id}")
                            
                            # Получаем список (превью + возможные авто-зумы)
                            crops = image_processor.download_and_process_pdf(entry.uri, image_id=img_id)
                            if crops:
                                base_imgs.extend(crops)
                                sent_image_ids.add(img_id)
                                for c in crops:
                                    if c.image_path:
                                        self.sig_image.emit(c.image_path, f"Image ID: {img_id}")

                        if missing_ids:
                            warn = f"⚠️ Не найдено в каталоге (для zoom): {', '.join(missing_ids[:10])}{' ...' if len(missing_ids) > 10 else ''}"
                            self.sig_log.emit(warn)
                            self.save_message("assistant", warn)

                        if base_imgs:
                            note = (
                                "🖼️ Подгружены базовые изображения (full/preview). "
                                "Ниже следуют запрошенные детальные фрагменты (Zoom)."
                            )
                            # Сохраняем сообщение с базовыми картинками
                            self.save_message("assistant", note, images=base_imgs)
                            # Добавляем в контекст модели, чтобы она знала, что они есть
                            llm_client.add_user_message(note, images=base_imgs)
                            
                            # УБРАЛИ continue: идем выполнять зумы сразу же!
                            # continue 

                    # Если базовые картинки уже были, но zoom некорректный — просим уточнить координаты.
                    if need_refine_ids:
                        msg = (
                            "⚠️ Нужны уточнённые координаты для zoom. "
                            "Укажи `coords_norm` как рамку вокруг интересующей зоны (меньше, чем весь лист)."
                        )
                        self.save_message("assistant", msg)
                        llm_client.add_user_message(msg, images=None)
                        continue

                    zoom_crops = []
                    for i, zr in enumerate(zoom_reqs):
                        zoom_msg = f"🔄 *Zoom [{i+1}/{len(zoom_reqs)}]:* {zr.reason}"
                        self.sig_log.emit(zoom_msg)
                        self._append_app_log(zoom_msg)
                        self.sig_message.emit("assistant", zoom_msg, self.model)

                        # Если модель просит zoom по image_id, но базовая картинка ещё не загружена —
                        # подгружаем её автоматически по каталогу (устойчивость).
                        try:
                            img_id = getattr(zr, "image_id", None)
                            if isinstance(img_id, str) and img_id:
                                # Нормализация: иногда модель присылает id с .pdf
                                if img_id.endswith(".pdf"):
                                    img_id = img_id[:-4]
                                    zr.image_id = img_id
                                if img_id not in getattr(image_processor, "_image_cache", {}):
                                    entry = doc_index.images.get(img_id)
                                    if entry:
                                        self.sig_log.emit(f"Подгружаю изображение для zoom: {img_id}")
                                        image_processor.download_and_process_pdf(entry.uri, image_id=img_id)
                        except Exception as e:
                            self.sig_log.emit(f"Не удалось подготовить изображение для zoom: {e}")
                        
                        # Определяем имя файла. Если кроп будет больше 2000px, помечаем как preview.
                        prefix = "zoom_step"
                        try:
                            if img_id and img_id in image_processor._image_sizes:
                                w_full, h_full = image_processor._image_sizes[img_id]
                                cw, ch = 0, 0
                                if zr.coords_norm:
                                    nx1, ny1, nx2, ny2 = zr.coords_norm
                                    cw = abs(nx2 - nx1) * w_full
                                    ch = abs(ny2 - ny1) * h_full
                                elif zr.coords_px:
                                    x1, y1, x2, y2 = zr.coords_px
                                    cw = abs(x2 - x1)
                                    ch = abs(y2 - y1)
                                
                                if max(cw, ch) > 2000:
                                    scale_factor = max(cw, ch) / 2000
                                    prefix = f"zoom_preview_{scale_factor:.1f}_step"
                        except: pass

                        zoom_crop = image_processor.process_zoom_request(
                            zr,
                            output_path=self.images_dir / f"{prefix}_{step}_{i}.png"
                        )
                        
                        if zoom_crop:
                            zoom_crops.append(zoom_crop)
                            self._append_app_log(f"Zoom {i+1} OK: {zoom_crop.image_path}")
                            if zoom_crop.image_path:
                                self.sig_image.emit(zoom_crop.image_path, f"Zoom {i+1}")
                        else:
                            self.sig_log.emit(f"Ошибка Zoom {i+1}")
                            self._append_app_log(f"Ошибка Zoom {i+1}")

                    if zoom_crops:
                        # Загружаем в S3 для LLM
                        self._upload_images_to_s3(zoom_crops)
                        
                        # Сохраняем в историю и БД ОДНИМ сообщением со всеми картинками
                        # Текст рассуждений уже сохранен выше (в response), здесь только фиксируем факт Zoom и картинки.
                        self.save_message("assistant", "🔎 Выполнен Zoom (см. изображения)", images=zoom_crops)
                        llm_client.add_user_message("Результаты Zoom:", images=zoom_crops)
                    else:
                        self.sig_log.emit("Ошибка Zoom: не удалось получить фрагменты.")
                        self._append_app_log("Ошибка Zoom: не удалось получить фрагменты.")
                        self.save_message("assistant", "⚠️ Ошибка Zoom: не удалось получить фрагменты.")
                
                if not tools_executed:
                    self._append_app_log("Финальный ответ получен.")
                    # Ответ уже сохранен в начале цикла
                    
                    # Обновляем краткую память диалога (для устойчивых длинных чатов)
                    try:
                        prev_mem = ""
                        if memory_path.exists():
                            prev_mem = memory_path.read_text(encoding="utf-8").strip()
                        new_mem = llm_client.update_memory_summary(prev_mem, self.query, response)
                        if new_mem:
                            memory_path.write_text(new_mem.strip(), encoding="utf-8")
                    except Exception as e:
                        logger.warning(f"Не удалось обновить память диалога: {e}")

                    self.sig_finished.emit()
                    return

            if self.is_running:
                err = "Лимит шагов."
                self.sig_error.emit(err)
                self.save_message("system", err)
                
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            self.sig_error.emit(str(e))
            self.sig_finished.emit()

    def stop(self):
        self.is_running = False

    def _run_flash_pro_mode(self, full_md_text: str, files_to_process: list, 
                            attached_images: list, all_blocks: list):
        """
        Двухэтапная обработка: Flash собирает контекст, Pro анализирует.
        """
        from .doc_index import build_index, strip_json_blocks, ImageCatalogEntry
        from .json_annotation_processor import JsonAnnotationProcessor
        from .llm_client import LLMClient, load_flash_extractor_prompt, load_analysis_prompt
        from .image_processor import ImageProcessor
        
        # Логирование начала Flash+Pro режима
        self._log_full("РЕЖИМ FLASH+PRO", {
            "query": self.query,
            "files": [str(f) for f in files_to_process],
            "attached_images_count": len(attached_images) if attached_images else 0
        })
        
        # Инициализация
        image_processor = ImageProcessor(self.data_root)
        image_processor.temp_dir = self.images_dir
        
        llm_client = LLMClient(model="gemini-3-flash-preview", data_root=self.data_root)
        
        # Строим индекс документа
        doc_index = build_index(full_md_text)
        
        # Добавляем изображения из JSON и HTML файлов
        for md_path_str in files_to_process:
            md_path = Path(md_path_str)
            suffix = md_path.suffix.lower()
            
            if suffix == '.json':
                try:
                    _, annotation = JsonAnnotationProcessor.process(md_path)
                    if annotation:
                        for img_block in annotation.image_blocks:
                            entry = ImageCatalogEntry(
                                image_id=img_block.block_id,
                                page=img_block.page_number,
                                uri=img_block.crop_url or "",
                                content_summary=img_block.content_summary or "",
                                detailed_description=img_block.detailed_description or "",
                                clean_ocr_text=img_block.ocr_text or "",
                                key_entities=img_block.key_entities or []
                            )
                            doc_index.images[img_block.block_id] = entry
                except Exception as e:
                    logger.error(f"Ошибка добавления изображений из JSON: {e}")
            
            elif suffix == '.html':
                try:
                    _, document = HtmlOcrProcessor.process(md_path)
                    if document:
                        for img_block in document.image_blocks:
                            entry = ImageCatalogEntry(
                                image_id=img_block.block_id,
                                page=img_block.page_number,
                                uri=img_block.crop_url or "",
                                content_summary=img_block.content_summary or "",
                                detailed_description=img_block.detailed_description or "",
                                clean_ocr_text=img_block.ocr_text or "",
                                key_entities=img_block.key_entities or [],
                                sheet_name=img_block.sheet_name or ""
                            )
                            doc_index.images[img_block.block_id] = entry
                except Exception as e:
                    logger.error(f"Ошибка добавления изображений из HTML: {e}")
            
            elif suffix == '.md':
                # Парсинг нового MD формата (_document.md)
                try:
                    md_image_blocks = FileProcessor.parse_md_image_blocks(md_path)
                    for img_block in md_image_blocks:
                        entry = ImageCatalogEntry(
                            image_id=img_block.block_id,
                            page=img_block.page_number,
                            uri=img_block.crop_url or "",
                            content_summary=img_block.content_summary or "",
                            detailed_description=img_block.detailed_description or "",
                            clean_ocr_text=img_block.ocr_text or "",
                            key_entities=img_block.key_entities or [],
                            sheet_name=img_block.sheet_name or "",
                            local_path=img_block.local_path or ""
                        )
                        doc_index.images[img_block.block_id] = entry
                except Exception as e:
                    logger.error(f"Ошибка добавления изображений из MD: {e}")
        
        # ===== ЭТАП 1: FLASH ЭКСТРАКТОР =====
        self.sig_log.emit("📋 Этап 1: Flash анализирует документ...")
        self.sig_message.emit("system", "🔍 Этап 1: Flash анализирует документацию и собирает контекст...", None)
        
        flash_prompt = load_flash_extractor_prompt(self.data_root)
        doc_text = strip_json_blocks(full_md_text)
        
        # Формируем ОБОГАЩЁННЫЙ каталог изображений для Flash
        img_entries = sorted(doc_index.images.values(), key=lambda e: ((e.page or 0), e.image_id))
        catalog_lines = []
        for e in img_entries:
            # Приоритет: sheet_name (наименование листа) > content_summary
            description = e.sheet_name if e.sheet_name else e.content_summary
            # Добавляем ключевые сущности если есть
            entities_str = ""
            if e.key_entities:
                entities_str = f" | Сущности: {', '.join(e.key_entities[:8])}"
            catalog_lines.append(f"- {e.image_id} (стр. {e.page}): {description[:200]}{entities_str}")
        catalog_text = "\n".join(catalog_lines)
        
        flash_context = f"""ДОКУМЕНТ:
{doc_text}

КАТАЛОГ ИЗОБРАЖЕНИЙ:
{catalog_text}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{self.query}

Извлеки ВСЕ релевантные данные для ответа на этот запрос."""
        
        flash_messages = [
            {"role": "system", "content": flash_prompt},
            {"role": "user", "content": flash_context}
        ]
        
        # Логируем начальный запрос Flash
        self._log_full("FLASH: Системный промпт", flash_prompt)
        self._log_full("FLASH: Начальный контекст (усечено)", flash_context[:10000] + "..." if len(flash_context) > 10000 else flash_context)
        
        # Собираем контекст итеративно
        collected_images = []  # ViewportCrop
        collected_zooms = []   # ViewportCrop
        sent_image_ids = set()
        max_flash_steps = 5
        flash_step = 0
        extracted_context = None
        
        while flash_step < max_flash_steps and self.is_running:
            flash_step += 1
            self.sig_log.emit(f"Flash шаг {flash_step}/{max_flash_steps}...")
            self._append_app_log(f"\n{'='*20} FLASH ШАГ {flash_step} {'='*20}")
            
            # Логируем запрос к Flash
            self._log_full(f"FLASH #{flash_step}: Запрос", self._sanitize_messages_for_log(flash_messages))
            
            try:
                flash_response = llm_client.call_flash_model(
                    flash_messages,
                    response_schema=FLASH_EXTRACTOR_SCHEMA
                )
            except Exception as e:
                self.sig_log.emit(f"Ошибка Flash: {e}")
                self._log_full(f"FLASH #{flash_step}: Ошибка", str(e))
                break
            
            # Обновляем счетчик токенов после вызова Flash
            try:
                usage = llm_client.last_usage
                if isinstance(usage, dict) and usage.get("total_tokens"):
                    tt = usage.get("total_tokens")
                    self._update_tokens(tt)
                    self.sig_log.emit(f"Flash шаг {flash_step}: использовано {tt} токенов")
            except Exception as e:
                logger.debug(f"Не удалось обновить токены Flash: {e}")
            
            # Логируем ответ Flash
            self._log_full(f"FLASH #{flash_step}: Ответ", flash_response)
            
            # Добавляем ответ Flash в историю
            flash_messages.append({"role": "model", "content": flash_response})
            
            # Проверяем, готов ли контекст
            extracted_context = llm_client.parse_flash_context(flash_response)
            if extracted_context:
                self.sig_log.emit("✅ Flash собрал контекст")
                break
            
            # Обрабатываем запросы изображений
            img_reqs = llm_client.parse_image_requests(flash_response)
            if img_reqs:
                self._log_full(f"FLASH #{flash_step}: Запрос изображений", [{"image_ids": r.image_ids, "reason": r.reason} for r in img_reqs])
                
                downloaded_imgs = []
                for r in img_reqs:
                    for rid in r.image_ids:
                        if rid in sent_image_ids:
                            continue
                        entry = doc_index.images.get(rid)
                        if not entry:
                            self._append_app_log(f"  ⚠️ Изображение не найдено: {rid}")
                            continue
                        self.sig_log.emit(f"Flash запросила изображение: {rid}")
                        self._append_app_log(f"  📥 Загрузка изображения: {rid}")
                        
                        # Используем локальный путь если нет URI
                        image_source = entry.uri if entry.uri else entry.local_path
                        if not image_source:
                            self._append_app_log(f"  ⚠️ Нет источника изображения: {rid}")
                            continue
                        crops = image_processor.download_and_process_pdf(image_source, image_id=rid)
                        if crops:
                            downloaded_imgs.extend(crops)
                            sent_image_ids.add(rid)
                            for c in crops:
                                if c.image_path:
                                    self.sig_image.emit(c.image_path, f"Flash: {rid}")
                
                if downloaded_imgs:
                    # Загружаем в Google Files API для Gemini
                    self._upload_images_to_google_files(downloaded_imgs, llm_client)
                    # Fallback на S3 если Google Files не сработал
                    self._upload_images_to_s3(downloaded_imgs)
                    collected_images.extend(downloaded_imgs)
                    self._log_full(f"FLASH #{flash_step}: Загружено изображений", len(downloaded_imgs))
                    
                    # Добавляем изображения в контекст Flash
                    img_content = [{"type": "text", "text": "Загружены изображения:"}]
                    for img in downloaded_imgs:
                        # Приоритет: Google Files URI, потом S3 URL
                        img_url = getattr(img, 'google_file_uri', None) or img.s3_url
                        if img_url:
                            img_content.append({
                                "type": "image_url",
                                "image_url": {"url": img_url}
                            })
                    flash_messages.append({"role": "user", "content": img_content})
                    continue
            
            # Обрабатываем запросы зумов
            zoom_reqs = llm_client.parse_zoom_request(flash_response)
            if zoom_reqs:
                self._log_full(f"FLASH #{flash_step}: Запросы ZOOM", [
                    {"image_id": zr.image_id, "coords_norm": zr.coords_norm, "coords_px": zr.coords_px, "reason": zr.reason} 
                    for zr in zoom_reqs
                ])
                
                zoom_crops = []
                for i, zr in enumerate(zoom_reqs):
                    self.sig_log.emit(f"Flash запросила zoom: {zr.reason[:50]}")
                    self._append_app_log(f"  🔍 ZOOM #{i+1}: {zr.image_id}, coords_norm={zr.coords_norm}, reason={zr.reason[:80]}")
                    
                    # Подготавливаем изображение если нужно
                    img_id = getattr(zr, "image_id", None)
                    if isinstance(img_id, str) and img_id:
                        if img_id.endswith(".pdf"):
                            img_id = img_id[:-4]
                            zr.image_id = img_id
                        if img_id not in getattr(image_processor, "_image_cache", {}):
                            entry = doc_index.images.get(img_id)
                            if entry:
                                # Используем локальный путь если нет URI
                                image_source = entry.uri if entry.uri else entry.local_path
                                if image_source:
                                    image_processor.download_and_process_pdf(image_source, image_id=img_id)
                    
                    zoom_crop = image_processor.process_zoom_request(
                        zr,
                        output_path=self.images_dir / f"flash_zoom_{flash_step}_{i}.png"
                    )
                    
                    if zoom_crop:
                        zoom_crops.append(zoom_crop)
                        self._append_app_log(f"    ✅ ZOOM сохранен: {zoom_crop.image_path}")
                        if zoom_crop.image_path:
                            self.sig_image.emit(zoom_crop.image_path, f"Flash zoom {i+1}")
                    else:
                        self._append_app_log(f"    ❌ ZOOM не удался")
                
                if zoom_crops:
                    # Загружаем в Google Files API для Gemini
                    self._upload_images_to_google_files(zoom_crops, llm_client)
                    # Fallback на S3
                    self._upload_images_to_s3(zoom_crops)
                    collected_zooms.extend(zoom_crops)
                    self._log_full(f"FLASH #{flash_step}: Выполнено ZOOM", len(zoom_crops))
                    
                    # Добавляем зумы в контекст Flash
                    zoom_content = [{"type": "text", "text": "Результаты ZOOM:"}]
                    for zc in zoom_crops:
                        # Приоритет: Google Files URI, потом S3 URL
                        img_url = getattr(zc, 'google_file_uri', None) or zc.s3_url
                        if img_url:
                            zoom_content.append({
                                "type": "image_url",
                                "image_url": {"url": img_url}
                            })
                    flash_messages.append({"role": "user", "content": zoom_content})
                    continue
            
            # Если нет запросов инструментов, просим Flash завершить
            flash_messages.append({
                "role": "user", 
                "content": "Если ты собрал достаточно контекста, верни JSON со status: 'ready'. Иначе запроси нужные изображения или зумы."
            })
        
        # Сохраняем промежуточный контекст для отладки
        flash_context_data = {
            "flash_steps": flash_step,
            "extracted_context": {
                "relevant_text_chunks": extracted_context.relevant_text_chunks if extracted_context else [],
                "relevant_images": extracted_context.relevant_images if extracted_context else [],
                "flash_reasoning": extracted_context.flash_reasoning if extracted_context else ""
            },
            "collected_images": [img.image_path for img in collected_images if img.image_path],
            "collected_zooms": [z.image_path for z in collected_zooms if z.image_path],
            "flash_messages_history": self._sanitize_messages_for_log(flash_messages)
        }
        
        # Логируем итоги Flash
        self._append_app_log(f"\n{'='*20} FLASH ИТОГИ {'='*20}")
        self._log_full("FLASH: Итоговая статистика", {
            "steps": flash_step,
            "collected_images": len(collected_images),
            "collected_zooms": len(collected_zooms),
            "text_chunks": len(extracted_context.relevant_text_chunks) if extracted_context else 0,
            "reasoning": extracted_context.flash_reasoning[:500] if extracted_context and extracted_context.flash_reasoning else ""
        })
        
        flash_context_path = self.chat_dir / "flash_context.json"
        try:
            with open(flash_context_path, "w", encoding="utf-8") as f:
                json.dump(flash_context_data, f, indent=2, ensure_ascii=False)
            self.sig_log.emit(f"Сохранен контекст Flash: {flash_context_path.name}")
            self._append_app_log(f"📄 Сохранен: {flash_context_path}")
        except Exception as e:
            logger.error(f"Ошибка сохранения flash_context.json: {e}")
        
        # Формируем контекст для Pro
        analysis_prompt = load_analysis_prompt(self.data_root)
        
        # Создаём индекс блоков по ID для быстрого поиска
        blocks_by_id = {}
        for block in all_blocks:
            if block.block_id:
                blocks_by_id[block.block_id] = block
        
        # Собираем ПОЛНЫЕ тексты блоков по block_id от Flash
        text_blocks_str = ""
        blocks_found = 0
        added_block_ids = set()  # Чтобы не добавлять дубликаты
        
        if extracted_context and extracted_context.relevant_blocks:
            for block_ref in extracted_context.relevant_blocks:
                block_id = block_ref.get("block_id")
                reason = block_ref.get("reason", "")
                
                # Ищем блок по ID
                if block_id and block_id in blocks_by_id and block_id not in added_block_ids:
                    block = blocks_by_id[block_id]
                    # Используем page_hint из блока (парсится из MD)
                    page = block.page_hint if block.page_hint else "?"
                    text_blocks_str += f"\n### БЛОК [{block_id}] (Стр. {page})\n"
                    if reason:
                        text_blocks_str += f"*Причина выбора: {reason}*\n"
                    text_blocks_str += f"{block.text}\n"
                    blocks_found += 1
                    added_block_ids.add(block_id)
                    
                    # Добавляем связанные блоки (→ID)
                    for linked_id in block.linked_block_ids:
                        if linked_id in blocks_by_id and linked_id not in added_block_ids:
                            linked_block = blocks_by_id[linked_id]
                            linked_page = linked_block.page_hint if linked_block.page_hint else "?"
                            text_blocks_str += f"\n### БЛОК [{linked_id}] (Стр. {linked_page}, связан с {block_id})\n"
                            text_blocks_str += f"{linked_block.text}\n"
                            blocks_found += 1
                            added_block_ids.add(linked_id)
                            
                elif block_id and block_id not in added_block_ids:
                    # Блок не найден, но есть content из старого формата
                    content = block_ref.get("content", "")
                    page = block_ref.get("page", "?")
                    if content:
                        text_blocks_str += f"\n### БЛОК [{block_id}] (Стр. {page})\n{content}\n"
                        blocks_found += 1
                        added_block_ids.add(block_id)
        
        self.sig_log.emit(f"Pro получит {blocks_found} текстовых блоков")
        
        # Выводим собранный контекст в чат (Этап 1 завершён)
        flash_summary_parts = []
        flash_summary_parts.append("📋 **Контекст для Pro (собран Flash):**\n")
        
        # Рассуждения Flash
        if extracted_context and extracted_context.flash_reasoning:
            reasoning_preview = extracted_context.flash_reasoning[:300]
            if len(extracted_context.flash_reasoning) > 300:
                reasoning_preview += "..."
            flash_summary_parts.append(f"**Анализ Flash:**\n_{reasoning_preview}_\n")
        
        # Блоки
        if added_block_ids:
            flash_summary_parts.append(f"**Текстовые блоки ({len(added_block_ids)}):**")
            for bid in list(added_block_ids)[:10]:  # Показываем первые 10
                block = blocks_by_id.get(bid)
                if block:
                    page = block.page_hint if block.page_hint else "?"
                    preview = block.text[:100].replace('\n', ' ') + "..." if len(block.text) > 100 else block.text.replace('\n', ' ')
                    flash_summary_parts.append(f"• `{bid}` (стр. {page}): {preview}")
            if len(added_block_ids) > 10:
                flash_summary_parts.append(f"  _...и ещё {len(added_block_ids) - 10} блоков_")
        
        # Изображения
        all_images_for_pro = collected_images + collected_zooms + (attached_images or [])
        if all_images_for_pro:
            flash_summary_parts.append(f"\n**Изображения ({len(all_images_for_pro)}):**")
            for img in all_images_for_pro[:5]:  # Показываем первые 5
                desc = img.description[:80] if img.description else "Без описания"
                flash_summary_parts.append(f"• {desc}")
            if len(all_images_for_pro) > 5:
                flash_summary_parts.append(f"  _...и ещё {len(all_images_for_pro) - 5} изображений_")
        
        flash_summary = "\n".join(flash_summary_parts)
        self.sig_message.emit("system", flash_summary, None)
        
        # Показываем изображения в чате
        for img in all_images_for_pro:
            if hasattr(img, 'image_path') and img.image_path:
                self.sig_image.emit(img.image_path, f"Для Pro: {img.description[:50] if img.description else 'Изображение'}")
        
        # ===== ЭТАП 2: PRO АНАЛИЗ =====
        self.sig_log.emit("🧠 Этап 2: Pro анализирует собранный контекст...")
        self.sig_message.emit("system", "🧠 Этап 2: Pro анализирует собранный контекст и формирует ответ...", None)
        
        # Сохраняем сообщение пользователя
        self.save_message("user", self.query, images=None)
        
        flash_reasoning = ""
        if extracted_context and extracted_context.flash_reasoning:
            flash_reasoning = f"\nАНАЛИЗ FLASH:\n{extracted_context.flash_reasoning}\n"
        
        pro_context = f"""КОНТЕКСТ ДЛЯ АНАЛИЗА (собран Flash-моделью):
{flash_reasoning}

РЕЛЕВАНТНЫЕ ТЕКСТОВЫЕ БЛОКИ ({blocks_found} шт.):
{text_blocks_str if text_blocks_str else 'Текстовые блоки не найдены.'}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{self.query}

Изображения и зумы прикреплены ниже. Проанализируй данные и ответь на вопрос."""
        
        pro_messages = [
            {"role": "system", "content": f"""{analysis_prompt}

## ФОРМАТ ОТВЕТА (JSON):

Твой ответ должен быть в формате JSON со следующими полями:
- `answer_markdown` (string, обязательно): Полный ответ на вопрос в формате Markdown.
- `summary` (string): Краткое резюме ответа (1-2 предложения).
- `counts` (array): Подсчёты объектов (если применимо), каждый элемент: {{object_type, count, locations[]}}.
- `citations` (array): Ссылки на источники, каждый элемент: {{image_id, coords_norm[4], note}}.
- `confidence` (string): Уверенность в ответе ("high", "medium", "low").
- `needs_more_evidence` (boolean): true если нужны дополнительные данные для более полного ответа.
- `followup_images` (array[string]): Список ID изображений для запроса (если needs_more_evidence=true).
- `followup_zooms` (array): Список запросов zoom (если needs_more_evidence=true), каждый элемент: {{image_id, coords_norm[4], reason}}.

**Важно:** Если ты можешь ответить на вопрос с имеющимися данными, установи `needs_more_evidence=false` и оставь `followup_*` пустыми.
"""}
        ]
        
        # Добавляем контекст и изображения
        all_images = collected_images + collected_zooms + (attached_images or [])
        
        # Загружаем attached_images в Google Files API если ещё не загружены
        if attached_images:
            self._upload_images_to_google_files(attached_images, llm_client)
        
        if all_images:
            pro_content = [{"type": "text", "text": pro_context}]
            for img in all_images:
                # Приоритет: Google Files URI, потом S3 URL
                img_url = getattr(img, 'google_file_uri', None) or getattr(img, 's3_url', None)
                if img_url:
                    desc = img.description[:100] if img.description else "Изображение"
                    pro_content.append({"type": "text", "text": f"[{desc}]"})
                    pro_content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url}
                    })
            pro_messages.append({"role": "user", "content": pro_content})
        else:
            pro_messages.append({"role": "user", "content": pro_context})
        
        # Логируем запрос к Pro
        self._append_app_log(f"\n{'='*20} PRO ЗАПРОС {'='*20}")
        self._log_full("PRO: Системный промпт", analysis_prompt)
        self._log_full("PRO: Контекст", pro_context)
        self._log_full("PRO: Запрос (полный)", self._sanitize_messages_for_log(pro_messages))
        self._log_full("PRO: Изображений в запросе", len(all_images))
        
        # Вызываем Pro (response_json=True для структурированного ответа)
        try:
            pro_response_json = llm_client.call_pro_model(
                pro_messages, 
                response_json=True,
                response_schema=PRO_ANSWER_SCHEMA
            )
        except Exception as e:
            err = f"Ошибка Pro модели: {e}"
            self.sig_log.emit(f"❌ {err}")
            self._log_full("PRO: Ошибка", str(e))
            self.sig_message.emit("assistant", f"⚠️ {err}", "gemini-3-pro-preview")
            self.save_message("assistant", f"⚠️ {err}")
            self.sig_finished.emit()
            return
        
        # Обновляем счетчик токенов после вызова Pro
        try:
            usage = llm_client.last_usage
            if isinstance(usage, dict) and usage.get("total_tokens"):
                tt = usage.get("total_tokens")
                self._update_tokens(tt)
                self.sig_log.emit(f"Pro: использовано {tt} токенов")
        except Exception as e:
            logger.debug(f"Не удалось обновить токены Pro: {e}")
        
        # Логируем ответ Pro
        self._log_full("PRO: Ответ (JSON)", pro_response_json)
        
        # Парсим JSON ответ
        try:
            pro_data = json.loads(pro_response_json)
        except json.JSONDecodeError as e:
            err = f"Ошибка парсинга JSON от Pro: {e}"
            self.sig_log.emit(f"❌ {err}")
            self._log_full("PRO: JSON error", str(e))
            self.sig_message.emit("assistant", f"⚠️ {err}\n\nСырой ответ:\n{pro_response_json}", "gemini-3-pro-preview")
            self.save_message("assistant", f"⚠️ {err}")
            self.sig_finished.emit()
            return
        
        # Извлекаем данные из JSON ответа
        answer_markdown = pro_data.get("answer_markdown", "")
        needs_more_evidence = pro_data.get("needs_more_evidence", False)
        followup_images = pro_data.get("followup_images", [])
        followup_zooms = pro_data.get("followup_zooms", [])
        confidence = pro_data.get("confidence", "medium")
        
        self._log_full("PRO: answer_markdown", answer_markdown)
        self._log_full("PRO: needs_more_evidence", needs_more_evidence)
        self._log_full("PRO: confidence", confidence)
        
        # ===== ЦИКЛ ОБРАБОТКИ TOOL CALLS ОТ PRO =====
        pro_step = 1
        max_pro_steps = 10
        
        while pro_step <= max_pro_steps and needs_more_evidence:
            self._append_app_log(f"\n{'='*20} PRO ШАГ {pro_step} (ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ) {'='*20}")
            
            has_new_data = False
            
            # Обработка followup_images
            if followup_images:
                self._log_full(f"PRO #{pro_step}: Запросы изображений", followup_images)
                
                new_images = []
                for img_id in followup_images:
                    self.sig_log.emit(f"Pro запросила изображение: {img_id}")
                    entry = doc_index.images.get(img_id)
                    if not entry:
                        self._append_app_log(f"  ⚠️ Изображение не найдено: {img_id}")
                        continue
                    
                    self._append_app_log(f"  📥 Загрузка изображения: {img_id}")
                    try:
                        # Используем локальный путь если нет URI
                        image_source = entry.uri if entry.uri else entry.local_path
                        if not image_source:
                            self._append_app_log(f"  ⚠️ Нет источника изображения: {img_id}")
                            continue
                        
                        loaded = image_processor.download_and_process_pdf(image_source, image_id=img_id)
                        new_images.extend(loaded)
                    except Exception as e:
                        self._append_app_log(f"  ❌ Ошибка загрузки {img_id}: {e}")
                
                if new_images:
                    # Загружаем в Google Files API
                    self._upload_images_to_google_files(new_images, llm_client)
                    # Fallback на S3
                    self._upload_images_to_s3(new_images)
                    all_images.extend(new_images)
                    has_new_data = True
                    
                    # Добавляем изображения в историю Pro
                    content_with_images = [{"type": "text", "text": "Загружены дополнительные изображения:"}]
                    for vc in new_images:
                        img_url = getattr(vc, 'google_file_uri', None) or vc.s3_url
                        if img_url:
                            content_with_images.append({
                                "type": "image_url",
                                "image_url": {"url": img_url}
                            })
                    pro_messages.append({"role": "user", "content": content_with_images})
            
            # Обработка followup_zooms
            if followup_zooms:
                self._log_full(f"PRO #{pro_step}: Запросы ZOOM", followup_zooms)
                
                zoom_crops = []
                for i, fz in enumerate(followup_zooms):
                    img_id = fz.get("image_id")
                    coords_norm = fz.get("coords_norm")
                    reason = fz.get("reason", "")
                    
                    # ФИКС: Проверяем формат coords_norm
                    if coords_norm and isinstance(coords_norm, list):
                        # Если это плоский массив координат (ошибка модели), пропускаем
                        if len(coords_norm) != 4:
                            self._append_app_log(f"  ⚠️ ZOOM #{i+1}: Неверный формат coords_norm (ожидается [x1,y1,x2,y2], получено {len(coords_norm)} элементов). Пропускаю.")
                            continue
                        # Проверяем что все координаты - числа
                        if not all(isinstance(c, (int, float)) for c in coords_norm):
                            self._append_app_log(f"  ⚠️ ZOOM #{i+1}: coords_norm содержит не-числа. Пропускаю.")
                            continue
                    else:
                        self._append_app_log(f"  ⚠️ ZOOM #{i+1}: Отсутствуют coords_norm. Пропускаю.")
                        continue
                    
                    self.sig_log.emit(f"Pro запросила zoom: {reason[:50]}")
                    self._append_app_log(f"  🔍 PRO ZOOM #{i+1}: {img_id}, coords_norm={coords_norm}, reason={reason[:80]}")
                    
                    # Загружаем изображение если нужно
                    if isinstance(img_id, str) and img_id:
                        entry = doc_index.images.get(img_id)
                        if not entry:
                            self._append_app_log(f"  ⚠️ Изображение не найдено: {img_id}")
                            continue
                        
                        # Загружаем и обрабатываем
                        try:
                            # Используем локальный путь если нет URI
                            image_source = entry.uri if entry.uri else entry.local_path
                            if not image_source:
                                self._append_app_log(f"  ⚠️ Нет источника изображения: {img_id}")
                                continue
                            
                            loaded = image_processor.download_and_process_pdf(image_source, image_id=img_id)
                            # Создаем zoom crop
                            zoom_output_path = self.data_root / "temp" / f"pro_zoom_{pro_step}_{i}.png"
                            zoom_result = image_processor.process_zoom_request(img_id, coords_norm, output_path=zoom_output_path)
                            if zoom_result:
                                zoom_crops.append(zoom_result)
                        except Exception as e:
                            self._append_app_log(f"  ❌ Ошибка zoom {img_id}: {e}")
                
                if zoom_crops:
                    # Загружаем зумы в Google Files API
                    self._upload_images_to_google_files(zoom_crops, llm_client)
                    # Fallback на S3
                    self._upload_images_to_s3(zoom_crops)
                    all_images.extend(zoom_crops)
                    has_new_data = True
                    
                    # Добавляем в историю Pro
                    content_with_zooms = [{"type": "text", "text": "Выполнены zoom запросы:"}]
                    for zc in zoom_crops:
                        desc = zc.description[:100] if zc.description else "Zoom"
                        img_url = getattr(zc, 'google_file_uri', None) or zc.s3_url
                        if img_url:
                            content_with_zooms.append({"type": "text", "text": f"[{desc}]"})
                            content_with_zooms.append({
                                "type": "image_url",
                                "image_url": {"url": img_url}
                            })
                    pro_messages.append({"role": "user", "content": content_with_zooms})
            
            # Если нет новых данных - выход
            if not has_new_data:
                self._append_app_log("  ℹ️ Нет новых данных для загрузки")
                break
            
            # Повторный запрос к Pro
            try:
                pro_response_json = llm_client.call_pro_model(
                    pro_messages, 
                    response_json=True,
                    response_schema=PRO_ANSWER_SCHEMA
                )
            except Exception as e:
                err = f"Ошибка Pro модели (шаг {pro_step}): {e}"
                self.sig_log.emit(f"❌ {err}")
                self._log_full(f"PRO шаг {pro_step}: Ошибка", str(e))
                break
            
            # Обновляем токены
            try:
                usage = llm_client.last_usage
                if isinstance(usage, dict) and usage.get("total_tokens"):
                    self._update_tokens(usage.get("total_tokens"))
            except:
                pass
            
            # Парсим ответ
            try:
                pro_data = json.loads(pro_response_json)
                answer_markdown = pro_data.get("answer_markdown", answer_markdown)  # Обновляем ответ
                needs_more_evidence = pro_data.get("needs_more_evidence", False)
                followup_images = pro_data.get("followup_images", [])
                followup_zooms = pro_data.get("followup_zooms", [])
                confidence = pro_data.get("confidence", confidence)
                
                self._log_full(f"PRO шаг {pro_step}: answer_markdown", answer_markdown)
                self._log_full(f"PRO шаг {pro_step}: needs_more_evidence", needs_more_evidence)
            except json.JSONDecodeError as e:
                self._log_full(f"PRO шаг {pro_step}: JSON error", str(e))
                break
            
            pro_step += 1
        
        if pro_step > max_pro_steps:
            self.sig_log.emit(f"⚠️ Достигнут лимит шагов Pro: {max_pro_steps}")
        
        # Отправляем финальный ответ пользователю (answer_markdown)
        # ФИКС: Проверяем что answer_markdown не пустой
        if not answer_markdown or not answer_markdown.strip():
            err = "⚠️ Pro модель не вернула финальный ответ (answer_markdown пустой)"
            self.sig_log.emit(err)
            self._log_full("PRO: Ошибка", err)
            self.sig_message.emit("assistant", err, "gemini-3-pro-preview")
            self.save_message("assistant", err)
        else:
            self.sig_message.emit("assistant", answer_markdown, "gemini-3-pro-preview")
            self.save_message("assistant", answer_markdown, images=all_images)
        
        self._append_app_log(f"\n{'='*20} FLASH+PRO ЗАВЕРШЕНО {'='*20}")
        self.sig_log.emit("✅ Flash + Pro обработка завершена")
        self.sig_finished.emit()
