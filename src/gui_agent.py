"""
Адаптер агента для работы в GUI (PyQt6).
С поддержкой выбора md файлов из GUI.
"""

import logging
import json
import uuid
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List
from PyQt6.QtCore import QThread, pyqtSignal

from .config import config
from .llm_client import LLMClient
from .image_processor import ImageProcessor
from .markdown_parser import MarkdownParser
from .supabase_client import supabase_client
from .s3_storage import s3_storage

logger = logging.getLogger(__name__)

class AgentWorker(QThread):
    sig_log = pyqtSignal(str)
    sig_message = pyqtSignal(str, str)
    sig_image = pyqtSignal(str, str)
    sig_finished = pyqtSignal()
    sig_error = pyqtSignal(str)
    sig_history_saved = pyqtSignal(str, str)
    sig_usage = pyqtSignal(int, int) # used, remaining
    
    def __init__(self, data_root: Path, query: str, model: str, md_files: List[str] = None, 
                 existing_chat_id: str = None, existing_db_chat_id: str = None):
        super().__init__()
        self.data_root = data_root
        self.query = query
        self.model = model
        self.md_files = md_files or []
        self.is_running = True
        
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
        
        self.db_chat_id = existing_db_chat_id
        
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
        if images:
            msg["images"] = [img.image_path for img in images if img.image_path]
        
        self.chat_history_data["messages"].append(msg)
        self._save_to_disk()
        
        # Сохранение в БД и S3
        if config.USE_DATABASE:
            try:
                asyncio.run(self._save_to_db(role, content, images))
            except Exception as e:
                logger.error(f"Ошибка сохранения в БД: {e}")

    async def _save_to_db(self, role: str, content: str, images: list = None):
        """Асинхронное сохранение сообщения и картинок в Supabase и S3."""
        try:
            if not self.db_chat_id:
                logger.warning("Supabase chat_id не инициализирован, сохранение невозможно")
                return

            # 1. Добавляем сообщение
            msg_id = await supabase_client.add_message(
                chat_id=self.db_chat_id,
                role=role,
                content=content
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

    def _save_to_disk(self):
        history_path = self.chat_dir / "history.json"
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(self.chat_history_data, f, indent=2, ensure_ascii=False)
        self.sig_history_saved.emit(self.chat_id, self.query)

    def run(self):
        try:
            self.sig_log.emit(f"Старт чата {self.chat_id}...")
            self._current_msg_id = None # Для привязки блоков к сообщению
            
            # 0. Инициализация чата в Supabase (только для новых чатов)
            if config.USE_DATABASE and not self.db_chat_id:
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
            
            llm_client = LLMClient(model=self.model, data_root=self.data_root)
            
            # Инициализируем диалог с историей, если она есть
            from .llm_client import load_analysis_prompt
            analysis_prompt = load_analysis_prompt(self.data_root)
            llm_client.history = [{"role": "system", "content": analysis_prompt}]

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
            
            # ВАЖНО: Если мы продолжаем чат, нам все равно нужен текст документа в контексте.
            # Для варианта A мы просто заново читаем файлы.
            if self.md_files:
                self.sig_log.emit(f"Используются выбранные MD файлы: {len(self.md_files)}")
                for md_path_str in self.md_files:
                    try:
                        md_path = Path(md_path_str)
                        self.sig_log.emit(f"Читаю: {md_path}")
                        
                        # Загружаем MD в S3 и регистрируем в БД
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
                            except Exception as e:
                                logger.error(f"Ошибка загрузки/регистрации MD: {e}")

                        parser = MarkdownParser(md_path)
                        blocks = parser.parse()
                        all_blocks.extend(blocks)
                        
                        self.sig_log.emit(f"Прочитано блоков: {len(blocks)}")
                        for block in blocks:
                            full_text += block.text + "\n\n"
                            
                        # Сохраняем блоки в search_results
                        if self.db_chat_id:
                            try:
                                # Для варианта A привязываем блоки к чату.
                                # Если в БД message_id обязателен, то для первичного индекса 
                                # мы пока пропускаем или привязываем к будущему сообщению.
                                pass
                            except Exception as e:
                                logger.error(f"Ошибка сохранения блока: {e}")

                    except Exception as e:
                        self.sig_log.emit(f"Ошибка чтения {md_path_str}: {e}")
                        import traceback
                        self.sig_log.emit(traceback.format_exc())
            else:
                # По умолчанию берем result.md
                self.sig_log.emit(f"Ищу result.md в {self.data_root}")
                markdown_path, _ = config.get_document_paths(self.data_root)
                if Path(markdown_path).exists():
                    parser = MarkdownParser(markdown_path)
                    blocks = parser.parse()
                    all_blocks = blocks
                    
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
            
            if not full_text.strip():
                raise ValueError("В чате нет прикрепленных документов для анализа. Прикрепите .md файлы.")

            # ===== Новая устойчивая схема для длинного диалога =====
            # 1) Локально индексируем документ (извлекаем каталог изображений и делаем чанки текста),
            # чтобы не заставлять модель возвращать длинные URL и не пересылать весь документ целиком.
            self.sig_log.emit("Индексирую документ и готовлю краткий контекст (retrieval)...")

            from .doc_index import build_index, retrieve_text_chunks

            doc_index = build_index(full_text)
            text_snippets = retrieve_text_chunks(doc_index, self.query, top_k=10)

            # Короткий каталог изображений (id + стр. + краткое описание), без URL.
            # Это позволяет модели запросить картинки по id через tool=request_images.
            img_entries = sorted(
                doc_index.images.values(),
                key=lambda e: ((e.page or 0), e.image_id),
            )
            catalog_lines = []
            for e in img_entries:
                summary = (e.content_summary or "").replace("\n", " ").strip()
                if len(summary) > 180:
                    summary = summary[:180] + "..."
                catalog_lines.append(f"- {e.image_id} (стр. {e.page}): {summary}")
            catalog_text = "\n".join(catalog_lines) if catalog_lines else "(каталог изображений пуст)"

            # Собираем минимальный контекст вместо полного result.md
            snippets_text = "\n\n".join([f"[{cid}]\n{txt}" for cid, txt in text_snippets]) if text_snippets else "(релевантных фрагментов текста не найдено)"
            context = (
                f"ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n{self.query}\n\n"
                f"РЕЛЕВАНТНЫЕ ФРАГМЕНТЫ ТЕКСТА/ТАБЛИЦ ИЗ ДОКУМЕНТА:\n{snippets_text}\n\n"
                f"КАТАЛОГ ИЗОБРАЖЕНИЙ (id → страница → краткое описание):\n{catalog_text}\n\n"
                f"Если для вывода нужны чертежи/схемы — запроси их через tool=request_images, используя image_ids из каталога."
            )
            
            print(f"[GUI_AGENT] Инициализирован анализ-чат")
            print(f"[GUI_AGENT] Размер контекста: {len(context)} символов")
            print(f"[GUI_AGENT] Количество картинок: 0")
            
            # В историю сохраняем только запрос пользователя (без многосоттысячного контекста)
            self.save_message("user", self.query, images=None)
            
            # После сохранения первого сообщения пользователя у нас есть message_id.
            # Теперь можно сохранить блоки поиска ПАКЕТНО, привязав их к этому сообщению.
            if self.db_chat_id and hasattr(self, '_current_msg_id') and self._current_msg_id:
                bulk_data = []
                for block in all_blocks:
                    bulk_data.append({
                        "chat_id": self.db_chat_id,
                        "message_id": self._current_msg_id,
                        "block_id": block.block_id,
                        "block_text": block.text[:1000]
                    })
                
                if bulk_data:
                    try:
                        asyncio.run(supabase_client.add_search_results_bulk(bulk_data))
                    except Exception as e:
                        logger.error(f"Ошибка пакетного сохранения блоков: {e}")

            llm_client.add_user_message(context, images=None)
            
            step = 0
            max_steps = 5
            
            while step < max_steps and self.is_running:
                step += 1
                print(f"[GUI_AGENT] === ШАГ {step} ===")
                self.sig_log.emit(f"Шаг {step}...")

                # Прогноз по контексту перед запросом (анализ)
                try:
                    est = llm_client.last_prompt_estimate or llm_client.build_context_report(llm_client.history, max_tokens=4000)
                    if est:
                        ctx = est.get("context_length")
                        prompt_est = est.get("prompt_tokens_est")
                        max_tokens = est.get("max_tokens")
                        img_cnt = est.get("image_count")
                        rem = est.get("remaining_after_max_completion")
                        overflow = est.get("will_overflow")
                        self.sig_log.emit(
                            f"[Контекст/прогноз][анализ] prompt≈{prompt_est} tok (картинок: {img_cnt}), max={max_tokens}, "
                            f"лимит={ctx if ctx is not None else 'неизв.'}, "
                            f"остаток≈{rem if rem is not None else 'неизв.'}, "
                            f"{'⚠️ риск лимита' if overflow else 'OK'}"
                        )
                except Exception:
                    pass
                
                response = llm_client.get_response()
                print(f"[GUI_AGENT] Получен ответ длиной {len(response)} символов")
                print(f"[GUI_AGENT] Первые 300 символов ответа: {response[:300]}")

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
                        if isinstance(pt, int) and isinstance(rem, int):
                            self.sig_usage.emit(pt, rem)
                except Exception:
                    pass
                
                # 1) Обрабатываем запросы на подгрузку изображений
                img_reqs = llm_client.parse_image_requests(response)
                if img_reqs:
                    # Собираем уникальные id
                    req_ids = []
                    for r in img_reqs:
                        for rid in r.image_ids:
                            rid = str(rid).strip()
                            if rid.endswith(".pdf"):
                                rid = rid[:-4]
                            if rid and rid not in req_ids:
                                req_ids.append(rid)

                    info_msg = f"🖼️ Запрошены изображения: {', '.join(req_ids[:15])}{' ...' if len(req_ids) > 15 else ''}"
                    self.sig_message.emit("assistant", info_msg)
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
                        crop_info = image_processor.download_and_process_pdf(entry.uri, image_id=rid)
                        if crop_info:
                            downloaded_imgs.append(crop_info)
                            if crop_info.image_path:
                                self.sig_image.emit(crop_info.image_path, f"Image ID: {rid}")

                    if missing_ids:
                        warn = f"⚠️ Не найдено в каталоге: {', '.join(missing_ids[:10])}{' ...' if len(missing_ids) > 10 else ''}"
                        self.sig_log.emit(warn)
                        self.save_message("assistant", warn)

                    if downloaded_imgs:
                        self.save_message("assistant", "🖼️ Загружены изображения по запросу модели.", images=downloaded_imgs)
                        llm_client.add_user_message("Запрошенные изображения:", images=downloaded_imgs)
                        # Продолжаем цикл — модель увидит картинки и сможет запросить zoom/сделать выводы
                        continue
                    else:
                        # Нечего показывать модели — продолжаем, чтобы она могла переформулировать запрос
                        llm_client.add_user_message("Не удалось загрузить запрошенные изображения. Попробуй указать другие image_ids из каталога.")
                        continue

                zoom_reqs = llm_client.parse_zoom_request(response)
                print(f"[GUI_AGENT] Zoom запросов: {len(zoom_reqs)}")
                
                if zoom_reqs:
                    zoom_crops = []
                    for i, zr in enumerate(zoom_reqs):
                        zoom_msg = f"🔄 *Zoom [{i+1}/{len(zoom_reqs)}]:* {zr.reason}"
                        self.sig_log.emit(zoom_msg)
                        self.sig_message.emit("assistant", zoom_msg)

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
                        
                        zoom_crop = image_processor.process_zoom_request(
                            zr,
                            output_path=self.images_dir / f"zoom_step_{step}_{i}.png"
                        )
                        
                        if zoom_crop:
                            zoom_crops.append(zoom_crop)
                            if zoom_crop.image_path:
                                self.sig_image.emit(zoom_crop.image_path, f"Zoom {i+1}")
                        else:
                            self.sig_log.emit(f"Ошибка Zoom {i+1}")

                    if zoom_crops:
                        # Сохраняем в историю и БД ОДНИМ сообщением со всеми картинками
                        reasons = " | ".join([zr.reason for zr in zoom_reqs])
                        self.save_message("assistant", f"🔎 Выполнен Zoom:\n{reasons}", images=zoom_crops)
                        llm_client.add_user_message("Результаты Zoom:", images=zoom_crops)
                    else:
                        self.sig_log.emit("Ошибка Zoom: не удалось получить фрагменты.")
                        self.save_message("assistant", "⚠️ Ошибка Zoom: не удалось получить фрагменты.")
                else:
                    self.sig_message.emit("assistant", response)
                    self.save_message("assistant", response)

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
