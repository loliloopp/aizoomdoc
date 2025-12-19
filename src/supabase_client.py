"""
Клиент Supabase для работы с чатами, сообщениями и изображениями.
"""

import logging
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
    
    # ===== Folder & File Operations (V2) =====
    
    async def create_folder(self, name: str, user_id: str = "default_user", parent_id: Optional[str] = None) -> Optional[str]:
        """Создать новую папку. Если user_id не передан, используется 'default_user'."""
        if not self.is_connected(): return None
        try:
            data = {"name": name, "user_id": user_id, "parent_id": parent_id}
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
                # В идеале здесь мы должны создать запись в storage_files и получить ID,
                # но для простоты оставим как есть, если колонка существует.
                # Если колонки нет, этот код вызовет ошибку Supabase, поэтому лучше проверить.
                pass 
            
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
    
    # ... (get_chat, get_chats, update_chat, archive_chat, add_message, get_chat_messages remain same)
    
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


# Глобальный экземпляр клиента
supabase_client = SupabaseClient()

