"""
Клиент Supabase для работы с чатами, сообщениями и изображениями.
"""

import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

import supabase
from supabase import create_client

from .config import config

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Клиент для работы с Supabase PostgreSQL."""
    
    def __init__(self):
        """Инициализировать Supabase клиент."""
        if not config.USE_DATABASE or not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
            logger.warning("Supabase отключен или не сконфигурирован")
            self.client = None
            return
        
        try:
            self.client = create_client(
                config.SUPABASE_URL,
                config.SUPABASE_ANON_KEY
            )
            logger.info("✅ Supabase клиент инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации Supabase: {e}")
            self.client = None
    
    def is_connected(self) -> bool:
        """Проверить подключение к БД."""
        return self.client is not None
    
    async def _retry_request(self, func, *args, max_retries: int = 3, delay: float = 1.0, **kwargs):
        """Вспомогательный метод для повторных попыток при сетевых ошибках."""
        last_err = None
        for i in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if "disconnected" in err_str or "timeout" in err_str or "connection" in err_str:
                    logger.warning(f"⚠️ Сетевая ошибка (попытка {i+1}/{max_retries}): {e}. Жду {delay}с...")
                    await asyncio.sleep(delay)
                    delay *= 2 # Экспоненциальная задержка
                    continue
                raise e
        raise last_err

    # ===== Global Settings (UI / App) =====

    async def get_settings_row(self, user_id: str = "default_user") -> Optional[Dict[str, Any]]:
        """
        Получить строку настроек пользователя из таблицы settings.
        Ожидаемая схема (см. scripts/SUPABASE_SETTINGS.sql):
        - user_id (text, unique)
        - page_settings (jsonb)
        """
        if not self.is_connected():
            return None
        try:
            resp = (
                self.client.table("settings")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0]
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка чтения settings для user_id={user_id}: {e}")
            return None

    async def upsert_settings_row(self, user_id: str, page_settings: Dict[str, Any]) -> bool:
        """
        Upsert строки settings по user_id.
        """
        if not self.is_connected():
            return False
        try:
            data = {
                "user_id": user_id,
                "page_settings": page_settings or {},
                "updated_at": datetime.utcnow().isoformat(),
            }
            self.client.table("settings").upsert(data, on_conflict="user_id").execute()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка upsert settings для user_id={user_id}: {e}")
            return False

    async def get_page_settings(self, page_key: str, user_id: str = "default_user") -> Dict[str, Any]:
        """
        Возвращает объект настроек для конкретной страницы/экрана (page_key) из page_settings (jsonb).
        """
        row = await self.get_settings_row(user_id=user_id)
        if not row:
            return {}
        page_settings = row.get("page_settings")
        if not isinstance(page_settings, dict):
            return {}
        page_obj = page_settings.get(page_key)
        return page_obj if isinstance(page_obj, dict) else {}

    async def update_page_settings(self, page_key: str, patch: Dict[str, Any], user_id: str = "default_user") -> bool:
        """
        Обновляет (shallow-merge) настройки конкретной страницы/экрана в page_settings.
        """
        if not isinstance(patch, dict):
            return False

        row = await self.get_settings_row(user_id=user_id)
        page_settings: Dict[str, Any] = {}
        if row and isinstance(row.get("page_settings"), dict):
            page_settings = dict(row["page_settings"])

        page_obj: Dict[str, Any] = {}
        if isinstance(page_settings.get(page_key), dict):
            page_obj = dict(page_settings[page_key])

        page_obj.update(patch)
        page_settings[page_key] = page_obj
        return await self.upsert_settings_row(user_id=user_id, page_settings=page_settings)

    async def get_md_processing_mode(self, user_id: str = "default_user", page_key: str = "main_window") -> str:
        """
        Текущее значение переключателя режима обработки MD.
        Возвращает 'rag' (по умолчанию) или 'full_md'.
        """
        page = await self.get_page_settings(page_key=page_key, user_id=user_id)
        mode = page.get("md_processing_mode")
        if mode in ("rag", "full_md"):
            return mode
        return "rag"

    async def set_md_processing_mode(self, mode: str, user_id: str = "default_user", page_key: str = "main_window") -> bool:
        """
        Сохранить режим обработки MD в settings.page_settings[page_key].md_processing_mode.
        """
        if mode not in ("rag", "full_md"):
            return False
        return await self.update_page_settings(page_key=page_key, patch={"md_processing_mode": mode}, user_id=user_id)

    # ===== Folder & File Operations (V2) =====
    
    async def create_folder(self, name: str, user_id: str = "default_user", parent_id: Optional[str] = None, slug: Optional[str] = None) -> Optional[str]:
        """Создать новую папку. Если user_id не передан, используется 'default_user'."""
        if not self.is_connected(): return None
        try:
            data = {"name": name, "user_id": user_id, "parent_id": parent_id}
            if slug:
                data["slug"] = slug
            response = self.client.table("folders").insert(data).execute()
            if response.data:
                folder_id = response.data[0]["id"]
                logger.info(f"✅ Папка создана: {folder_id}")
                return folder_id
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка создания папки: {e}")
            return None

    async def get_folders(self, user_id: str = "default_user") -> List[Dict[str, Any]]:
        """Получить список папок пользователя."""
        if not self.is_connected(): return []
        try:
            return self.client.table("folders").select("*").eq("user_id", user_id).execute().data or []
        except Exception as e:
            logger.error(f"❌ Ошибка получения папок: {e}")
            return []

    async def register_file(self, 
        source_type: str, 
        filename: str, 
        user_id: str = "default_user",
        storage_path: Optional[str] = None, 
        external_url: Optional[str] = None,
        mime_type: Optional[str] = None,
        size_bytes: Optional[int] = None
    ) -> Optional[str]:
        """
        Зарегистрировать файл в центральной таблице storage_files.
        Args:
            source_type: 'user_upload', 'llm_generated', 'external_link'
        """
        if not self.is_connected(): return None
        try:
            data = {
                "user_id": user_id,
                "source_type": source_type,
                "filename": filename,
                "storage_path": storage_path,
                "external_url": external_url,
                "mime_type": mime_type,
                "size_bytes": size_bytes
            }
            response = self.client.table("storage_files").insert(data).execute()
            if response.data:
                file_id = response.data[0]["id"]
                logger.info(f"✅ Файл зарегистрирован: {file_id}")
                return file_id
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка регистрации файла: {e}")
            return None

    async def add_file_to_folder(self, folder_id: str, file_id: str) -> bool:
        """Добавить существующий файл в папку."""
        if not self.is_connected(): return False
        try:
            self.client.table("folder_items").insert({"folder_id": folder_id, "file_id": file_id}).execute()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления файла в папку: {e}")
            return False

    async def get_folder_files(self, folder_id: str) -> List[Dict[str, Any]]:
        """Получить список файлов в папке."""
        if not self.is_connected(): return []
        try:
            items = self.client.table("folder_items").select("file_id").eq("folder_id", folder_id).execute().data or []
            if not items: return []
            file_ids = [item["file_id"] for item in items]
            files = self.client.table("storage_files").select("*").in_("id", file_ids).execute().data or []
            return files
        except Exception as e:
            logger.error(f"❌ Ошибка получения файлов папки: {e}")
            return []

    async def delete_folder(self, folder_id: str) -> bool:
        """Удалить папку и связи с файлами."""
        if not self.is_connected(): return False
        try:
            # Сначала удаляем связи
            self.client.table("folder_items").delete().eq("folder_id", folder_id).execute()
            # Затем саму папку
            self.client.table("folders").delete().eq("id", folder_id).execute()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления папки: {e}")
            return False

    async def delete_file_from_folder(self, folder_id: str, file_id: str) -> bool:
        """Удалить файл из конкретной папки (связь)."""
        if not self.is_connected(): return False
        try:
            self.client.table("folder_items").delete().eq("folder_id", folder_id).eq("file_id", file_id).execute()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления файла из папки: {e}")
            return False

    async def add_attachment_to_message(self, message_id: str, file_id: str) -> bool:
        """Прикрепить файл (из папки или загруженный) к сообщению."""
        if not self.is_connected(): return False
        try:
            self.client.table("message_attachments").insert({"message_id": message_id, "file_id": file_id}).execute()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка прикрепления файла к сообщению: {e}")
            return False

    # ===== Updated Chat & Image Operations (V2) =====

    async def create_chat(
        self,
        title: str,
        user_id: Optional[str] = None,
        description: Optional[str] = None,
        document_path: Optional[str] = None, # Deprecated legacy arg, ignored if file_id present
        document_file_id: Optional[str] = None, # New V2 arg
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Создать новый чат.
        V2 Update: Использует document_file_id вместо document_path.
        """
        if not self.is_connected():
            logger.warning("Supabase не подключен, чат не сохранен")
            return None
        
        try:
            data = {
                "title": title,
                "user_id": user_id,
                "description": description,
                "metadata": metadata or {},
            }
            # Поддержка новой схемы
            if document_file_id:
                data["document_file_id"] = document_file_id
            
            # Обратная совместимость (если миграция не удалила колонку)
            if document_path and not document_file_id:
                data["document_path"] = document_path
            
            response = self.client.table("chats").insert(data).execute()
            
            if response.data and len(response.data) > 0:
                chat_id = response.data[0]["id"]
                logger.info(f"✅ Чат создан: {chat_id}")
                return chat_id
            else:
                logger.error("Ошибка создания чата: пустой ответ")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка создания чата: {e}")
            return None
            
    async def add_image_to_message(
        self,
        chat_id: str,
        message_id: str,
        image_name: str,
        s3_path: str,
        s3_url: Optional[str] = None,
        image_type: str = "viewport",
        description: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        file_size: Optional[int] = None,
        # V2 Argument
        file_id: Optional[str] = None 
    ) -> Optional[str]:
        """
        Добавить картинку к сообщению.
        V2 Update: Если передан file_id, использует его.
        Если file_id нет, но есть s3_path - пытается сначала зарегистрировать файл.
        """
        if not self.is_connected():
            return None
        
        try:
            # V2 Logic: Auto-register file if needed
            if not file_id and s3_path:
                # Пытаемся автоматически зарегистрировать файл
                # Используем default_user, так как это системная операция генерации файла
                file_id = await self.register_file(
                    user_id="default_user",
                    source_type="llm_generated",
                    filename=image_name,
                    storage_path=s3_path,
                    mime_type="image/png",
                    size_bytes=file_size
                )

            data = {
                "chat_id": chat_id,
                "message_id": message_id,
                "image_type": image_type,
                "description": description,
                "width": width,
                "height": height,
            }
            
            if file_id:
                data["file_id"] = file_id
            else:
                # Fallback to legacy columns if migration wasn't strict
                data["image_name"] = image_name
                # data["s3_path"] = s3_path # Удалено в V2 схеме
            
            response = self.client.table("chat_images").insert(data).execute()
            
            if response.data:
                return response.data[0]["id"]
            return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка добавления картинки: {e}")
            return None

    # ===== Old Methods (Keep for interface compatibility but create_chat/add_image are overridden above) =====
    
    async def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        message_type: str = "text"
    ) -> Optional[str]:
        """Добавить сообщение в чат с поддержкой повторных попыток."""
        if not self.is_connected():
            return None
        
        async def _do_insert():
            data = {
                "chat_id": chat_id,
                "role": role,
                "content": content,
                "message_type": message_type
            }
            return self.client.table("chat_messages").insert(data).execute()

        try:
            response = await self._retry_request(_do_insert)
            if response.data:
                msg_id = response.data[0]["id"]
                logger.info(f"✅ Сообщение добавлено: {msg_id}")
                return msg_id
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка добавления сообщения после попыток: {e}")
            return None

    async def get_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о чате."""
        if not self.is_connected(): return None
        try:
            response = self.client.table("chats").select("*").eq("id", chat_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения чата {chat_id}: {e}")
            return None

    async def get_chats(self, user_id: str = "default_user", limit: int = 50) -> List[Dict[str, Any]]:
        """Получить список чатов пользователя."""
        if not self.is_connected(): return []
        try:
            response = (
                self.client.table("chats")
                .select("*")
                .eq("user_id", user_id)
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(f"❌ Ошибка получения чатов: {e}")
            return []

    async def update_chat(self, chat_id: str, data: Dict[str, Any]) -> bool:
        """Обновить информацию о чате."""
        if not self.is_connected(): return False
        try:
            data["updated_at"] = datetime.utcnow().isoformat()
            self.client.table("chats").update(data).eq("id", chat_id).execute()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления чата {chat_id}: {e}")
            return False

    async def get_chat_messages(self, chat_id: str) -> List[Dict[str, Any]]:
        """Получить все сообщения чата."""
        if not self.is_connected(): return []
        try:
            response = (
                self.client.table("chat_messages")
                .select("*")
                .eq("chat_id", chat_id)
                .order("created_at", desc=False)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(f"❌ Ошибка получения сообщений чата {chat_id}: {e}")
            return []

    async def archive_chat(self, chat_id: str) -> bool:
        """Архивировать чат."""
        return await self.update_chat(chat_id, {"is_archived": True})
    
    async def delete_chat(self, chat_id: str) -> bool:
        """
        Полностью удалить чат из БД.
        Связанные сообщения, картинки и результаты поиска будут удалены каскадно.
        """
        if not self.is_connected(): return False
        try:
            self.client.table("chats").delete().eq("id", chat_id).execute()
            logger.info(f"✅ Чат удален из БД: {chat_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления чата {chat_id} из БД: {e}")
            return False
    
    async def get_message_images(self, message_id: str) -> List[Dict[str, Any]]:
        """
        Получить все картинки сообщения.
        
        Args:
            message_id: UUID сообщения
        
        Returns:
            Список картинок
        """
        if not self.is_connected():
            return []
        
        try:
            response = (
                self.client.table("chat_images")
                .select("*")
                .eq("message_id", message_id)
                .execute()
            )
            
            return response.data if response.data else []
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения картинок сообщения {message_id}: {e}")
            return []
    
    # ===== Search Results Operations =====
    
    async def add_search_results_bulk(
        self,
        results: List[Dict[str, Any]]
    ) -> bool:
        """
        Пакетное добавление результатов поиска.
        Каждый элемент в results должен содержать: chat_id, message_id, block_id, etc.
        """
        if not self.is_connected() or not results:
            return False
            
        async def _do_bulk_insert():
            return self.client.table("search_results").insert(results).execute()

        try:
            await self._retry_request(_do_bulk_insert)
            logger.info(f"✅ Пакетно добавлено результатов поиска: {len(results)}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка пакетного добавления результатов: {e}")
            return False

    async def add_search_result(
        self,
        chat_id: str,
        message_id: str,
        block_id: Optional[str] = None,
        page_number: Optional[int] = None,
        block_text: Optional[str] = None,
        coords_norm: Optional[List[float]] = None,
        coords_px: Optional[List[int]] = None
    ) -> Optional[str]:
        """
        Добавить результат поиска.
        
        Args:
            chat_id: UUID чата
            message_id: UUID сообщения
            block_id: ID блока из annotation.json
            page_number: Номер страницы
            block_text: Текст блока
            coords_norm: Нормализованные координаты
            coords_px: Координаты в пикселях
        
        Returns:
            UUID результата или None в случае ошибки
        """
        if not self.is_connected():
            logger.warning("Supabase не подключен, результат поиска не сохранен")
            return None
        
        try:
            data = {
                "chat_id": chat_id,
                "message_id": message_id,
                "block_id": block_id,
                "page_number": page_number,
                "block_text": block_text,
                "coords_norm": coords_norm,
                "coords_px": coords_px,
            }
            
            response = self.client.table("search_results").insert(data).execute()
            
            if response.data and len(response.data) > 0:
                result_id = response.data[0]["id"]
                logger.info(f"✅ Результат поиска добавлен: {result_id}")
                return result_id
            else:
                logger.error("Ошибка добавления результата поиска: пустой ответ")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка добавления результата поиска: {e}")
            return None
    
    async def get_search_results(self, chat_id: str) -> List[Dict[str, Any]]:
        """
        Получить результаты поиска чата.
        
        Args:
            chat_id: UUID чата
        
        Returns:
            Список результатов
        """
        if not self.is_connected():
            return []
        
        try:
            response = (
                self.client.table("search_results")
                .select("*")
                .eq("chat_id", chat_id)
                .execute()
            )
            
            return response.data if response.data else []
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения результатов поиска {chat_id}: {e}")
            return []


    async def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о файле."""
        if not self.is_connected(): return None
        try:
            response = self.client.table("storage_files").select("*").eq("id", file_id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения инфо о файле {file_id}: {e}")
            return None

# Глобальный экземпляр клиента
supabase_client = SupabaseClient()

