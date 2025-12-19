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
    
    def __init__(self, data_root: Path, query: str, model: str, md_files: List[str] = None):
        super().__init__()
        self.data_root = data_root
        self.query = query
        self.model = model
        self.md_files = md_files or []
        self.is_running = True
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.chat_id = f"{timestamp}_{uuid.uuid4().hex[:6]}"
        
        self.chat_dir = data_root / "chats" / self.chat_id
        self.images_dir = self.chat_dir / "images"
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        self.chat_history_data = {
            "id": self.chat_id,
            "timestamp": timestamp,
            "query": query,
            "model": model,
            "md_files": self.md_files,
            "messages": []
        }
        self.db_chat_id = None

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
            
            # 0. Инициализация чата в Supabase (сразу, чтобы иметь ID)
            if config.USE_DATABASE:
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
            
            # Если указаны конкретные md файлы через GUI - используем их
            full_text = ""
            all_blocks = []
            
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
                                    asyncio.run(supabase_client.add_search_result(
                                        chat_id=self.db_chat_id,
                                        message_id=None,
                                        block_id=block.block_id,
                                        block_text=block.text[:1000]
                                    ))
                                except: pass

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
                raise ValueError("Документ пуст")
            
            self.sig_log.emit("Анализ запроса и выбор картинок...")
            selection = llm_client.select_relevant_images(full_text, self.query)
            
            self.sig_log.emit(f"Выбрано изображений: {len(selection.image_urls)}")
            
            downloaded_images = []
            if selection.needs_images and selection.image_urls:
                info_msg = f"🔎 *Анализ:* {selection.reasoning}\nСкачиваю {len(selection.image_urls)} изображений..."
                self.sig_message.emit("assistant", info_msg)
                self.save_message("assistant", info_msg)
                
                for url in selection.image_urls:
                    if not self.is_running: return
                    self.sig_log.emit(f"Скачивание: {url}")
                    
                    crop_info = image_processor.download_and_process_pdf(url)
                    if crop_info:
                        downloaded_images.append(crop_info)
                        if crop_info.image_path:
                            self.sig_image.emit(crop_info.image_path, f"Источник: {url}")
            else:
                msg = "Изображения не требуются."
                self.sig_message.emit("assistant", msg)
                self.save_message("assistant", msg)

            llm_client.init_analysis_chat()
            
            # Передаем ВЕСЬ документ - ответ может быть в любом блоке
            context = f"ДОКУМЕНТ:\n{full_text}\n\nЗАПРОС ПОЛЬЗОВАТЕЛЯ: {self.query}"
            
            print(f"[GUI_AGENT] Инициализирован анализ-чат")
            print(f"[GUI_AGENT] Размер контекста: {len(context)} символов")
            print(f"[GUI_AGENT] Количество картинок: {len(downloaded_images)}")
            
            self.save_message("user", self.query, images=downloaded_images)
            
            llm_client.add_user_message(context, images=downloaded_images)
            
            step = 0
            max_steps = 5
            
            while step < max_steps and self.is_running:
                step += 1
                print(f"[GUI_AGENT] === ШАГ {step} ===")
                self.sig_log.emit(f"Шаг {step}...")
                
                response = llm_client.get_response()
                print(f"[GUI_AGENT] Получен ответ длиной {len(response)} символов")
                print(f"[GUI_AGENT] Первые 300 символов ответа: {response[:300]}")
                
                zoom_reqs = llm_client.parse_zoom_request(response)
                print(f"[GUI_AGENT] Zoom запросов: {len(zoom_reqs)}")
                
                if zoom_reqs:
                    zoom_crops = []
                    for i, zr in enumerate(zoom_reqs):
                        zoom_msg = f"🔄 *Zoom [{i+1}/{len(zoom_reqs)}]:* {zr.reason}"
                        self.sig_log.emit(zoom_msg)
                        self.sig_message.emit("assistant", zoom_msg)
                        
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
