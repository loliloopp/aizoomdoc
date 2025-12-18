"""
S3 Storage client для cloud.ru.
"""

import logging
import os
from pathlib import Path
from typing import Optional, BinaryIO
from datetime import datetime, timedelta
from urllib.parse import urljoin

import boto3
from botocore.exceptions import ClientError

from .config import config

logger = logging.getLogger(__name__)


class S3Storage:
    """Клиент для работы с S3 cloud.ru."""
    
    def __init__(self):
        """Инициализировать S3 клиент."""
        if not config.USE_S3_STORAGE or not config.S3_ACCESS_KEY or not config.S3_SECRET_KEY:
            logger.warning("S3 отключен или не сконфигурирован")
            self.client = None
            self.resource = None
            return
        
        try:
            self.client = boto3.client(
                "s3",
                endpoint_url=config.S3_ENDPOINT,
                region_name=config.S3_REGION,
                aws_access_key_id=config.S3_ACCESS_KEY,
                aws_secret_access_key=config.S3_SECRET_KEY,
            )
            
            self.resource = boto3.resource(
                "s3",
                endpoint_url=config.S3_ENDPOINT,
                region_name=config.S3_REGION,
                aws_access_key_id=config.S3_ACCESS_KEY,
                aws_secret_access_key=config.S3_SECRET_KEY,
            )
            
            logger.info("✅ S3 клиент инициализирован")
            self._test_connection()
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации S3: {e}")
            self.client = None
            self.resource = None
    
    def is_connected(self) -> bool:
        """Проверить подключение к S3."""
        return self.client is not None and self.resource is not None
    
    def _test_connection(self) -> None:
        """Проверить подключение к S3."""
        try:
            self.client.head_bucket(Bucket=config.S3_BUCKET)
            logger.info(f"✅ Бакет '{config.S3_BUCKET}' доступен")
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                logger.warning(f"⚠️  Бакет '{config.S3_BUCKET}' не существует")
            else:
                logger.error(f"❌ Ошибка доступа к бакету: {e}")
    
    # ===== File Upload Operations =====
    
    async def upload_file(
        self,
        file_path: str,
        s3_key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Загрузить файл на S3.
        
        Args:
            file_path: Локальный путь к файлу
            s3_key: Ключ (путь) в S3
            content_type: MIME type файла
            metadata: Метаданные файла
        
        Returns:
            URL файла на S3 или None в случае ошибки
        """
        if not self.is_connected():
            logger.warning("S3 не подключен, файл не загружен")
            return None
        
        if not os.path.exists(file_path):
            logger.error(f"Файл не найден: {file_path}")
            return None
        
        try:
            file_size = os.path.getsize(file_path)
            
            # Проверить максимальный размер
            max_size_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024
            if file_size > max_size_bytes:
                logger.error(
                    f"Размер файла ({file_size} байт) превышает лимит "
                    f"({max_size_bytes} байт)"
                )
                return None
            
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                extra_args["Metadata"] = metadata
            
            self.client.upload_file(
                file_path,
                config.S3_BUCKET,
                s3_key,
                ExtraArgs=extra_args
            )
            
            url = self._get_s3_url(s3_key)
            logger.info(f"✅ Файл загружен: {s3_key}")
            
            return url
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки файла {s3_key}: {e}")
            return None
    
    async def upload_file_object(
        self,
        file_obj: BinaryIO,
        s3_key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Загрузить файл из file object.
        
        Args:
            file_obj: File object (например из BytesIO)
            s3_key: Ключ (путь) в S3
            content_type: MIME type файла
            metadata: Метаданные файла
        
        Returns:
            URL файла на S3 или None в случае ошибки
        """
        if not self.is_connected():
            logger.warning("S3 не подключен, файл не загружен")
            return None
        
        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                extra_args["Metadata"] = metadata
            
            self.client.upload_fileobj(
                file_obj,
                config.S3_BUCKET,
                s3_key,
                ExtraArgs=extra_args
            )
            
            url = self._get_s3_url(s3_key)
            logger.info(f"✅ Файл загружен: {s3_key}")
            
            return url
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки файла {s3_key}: {e}")
            return None
    
    # ===== File Download Operations =====
    
    async def download_file(
        self,
        s3_key: str,
        local_path: str
    ) -> bool:
        """
        Скачать файл с S3.
        
        Args:
            s3_key: Ключ (путь) в S3
            local_path: Локальный путь для сохранения
        
        Returns:
            True если успешно, False иначе
        """
        if not self.is_connected():
            logger.warning("S3 не подключен, файл не скачан")
            return False
        
        try:
            # Создать директорию если не существует
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            self.client.download_file(
                config.S3_BUCKET,
                s3_key,
                local_path
            )
            
            logger.info(f"✅ Файл скачан: {s3_key} -> {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания файла {s3_key}: {e}")
            return False
    
    # ===== URL Operations =====
    
    def get_signed_url(
        self,
        s3_key: str,
        expires_in: Optional[int] = None
    ) -> Optional[str]:
        """
        Получить подписанный URL на временное время.
        
        Args:
            s3_key: Ключ (путь) в S3
            expires_in: Время жизни в секундах (по умолчанию из конфига)
        
        Returns:
            Подписанный URL или None в случае ошибки
        """
        if not self.is_connected():
            logger.warning("S3 не подключен, подписанный URL не получен")
            return None
        
        try:
            expires_in = expires_in or config.S3_URL_EXPIRATION
            
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": config.S3_BUCKET, "Key": s3_key},
                ExpiresIn=expires_in,
            )
            
            logger.info(f"✅ Подписанный URL получен: {s3_key}")
            return url
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения подписанного URL {s3_key}: {e}")
            return None
    
    # ===== File Operations =====
    
    async def delete_file(self, s3_key: str) -> bool:
        """
        Удалить файл с S3.
        
        Args:
            s3_key: Ключ (путь) в S3
        
        Returns:
            True если успешно, False иначе
        """
        if not self.is_connected():
            logger.warning("S3 не подключен, файл не удален")
            return False
        
        try:
            self.client.delete_object(Bucket=config.S3_BUCKET, Key=s3_key)
            logger.info(f"✅ Файл удален: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка удаления файла {s3_key}: {e}")
            return False
    
    async def file_exists(self, s3_key: str) -> bool:
        """
        Проверить существует ли файл на S3.
        
        Args:
            s3_key: Ключ (путь) в S3
        
        Returns:
            True если существует, False иначе
        """
        if not self.is_connected():
            return False
        
        try:
            self.client.head_object(Bucket=config.S3_BUCKET, Key=s3_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            logger.error(f"❌ Ошибка проверки файла {s3_key}: {e}")
            return False
    
    async def get_file_metadata(self, s3_key: str) -> Optional[dict]:
        """
        Получить метаданные файла.
        
        Args:
            s3_key: Ключ (путь) в S3
        
        Returns:
            Словарь с метаданными или None
        """
        if not self.is_connected():
            return None
        
        try:
            response = self.client.head_object(Bucket=config.S3_BUCKET, Key=s3_key)
            
            return {
                "size": response.get("ContentLength"),
                "content_type": response.get("ContentType"),
                "modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {}),
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения метаданных {s3_key}: {e}")
            return None
    
    # ===== Helper Methods =====
    
    def _get_s3_url(self, s3_key: str) -> str:
        """
        Получить публичный URL файла в S3/R2.
        
        Args:
            s3_key: Ключ (путь) в S3
        
        Returns:
            Публичный URL
        """
        if config.S3_PUBLIC_DOMAIN:
            # Если задан публичный домен R2 (например https://pub-xxx.r2.dev)
            return f"{config.S3_PUBLIC_DOMAIN}/{s3_key}"
        
        # Если нет, возвращаем endpoint URL (может не работать публично без настройки прав)
        return f"{config.S3_ENDPOINT}/{config.S3_BUCKET}/{s3_key}"
    
    def generate_s3_path(
        self,
        chat_id: str,
        file_type: str,
        filename: Optional[str] = None
    ) -> str:
        """
        Сгенерировать путь для файла в S3.
        
        Args:
            chat_id: UUID чата
            file_type: Тип файла ('viewport', 'zoom_crop', 'document', и т.д.)
            filename: Имя файла (если None, будет сгенерировано)
        
        Returns:
            Путь в S3
        """
        if filename is None:
            timestamp = datetime.utcnow().isoformat().replace(":", "-")
            filename = f"{file_type}_{timestamp}.tmp"
        
        # Структура: chats/{chat_id}/images/{filename}
        if file_type in ("viewport", "zoom_crop", "processed"):
            return f"chats/{chat_id}/images/{filename}"
        elif file_type == "document":
            return f"chats/{chat_id}/documents/{filename}"
        else:
            return f"chats/{chat_id}/other/{filename}"
    
    # ===== Batch Operations =====
    
    async def delete_folder(self, prefix: str) -> int:
        """
        Удалить все файлы по префиксу.
        
        Args:
            prefix: Префикс пути (например 'chats/chat_id/')
        
        Returns:
            Количество удаленных файлов
        """
        if not self.is_connected():
            logger.warning("S3 не подключен, папка не удалена")
            return 0
        
        try:
            bucket = self.resource.Bucket(config.S3_BUCKET)
            deleted_count = 0
            
            for obj in bucket.objects.filter(Prefix=prefix):
                obj.delete()
                deleted_count += 1
            
            if deleted_count > 0:
                logger.info(f"✅ Удалено {deleted_count} файлов по префиксу {prefix}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Ошибка удаления папки {prefix}: {e}")
            return 0
    
    async def list_files(self, prefix: str) -> list:
        """
        Получить список файлов по префиксу.
        
        Args:
            prefix: Префикс пути (например 'chats/chat_id/')
        
        Returns:
            Список объектов (ключей) в S3
        """
        if not self.is_connected():
            return []
        
        try:
            response = self.client.list_objects_v2(
                Bucket=config.S3_BUCKET,
                Prefix=prefix
            )
            
            if "Contents" not in response:
                return []
            
            return [obj["Key"] for obj in response["Contents"]]
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка файлов {prefix}: {e}")
            return []


# Глобальный экземпляр хранилища
s3_storage = S3Storage()

