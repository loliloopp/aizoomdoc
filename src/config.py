"""
Конфигурация приложения.
"""

import os
from pathlib import Path
from typing import Tuple
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()


class Config:
    """Центральная конфигурация приложения."""
    
    # OpenRouter API
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", 
        "https://openrouter.ai/api/v1"
    )
    DEFAULT_MODEL: str = os.getenv(
        "DEFAULT_MODEL", 
        "google/gemini-3-flash-preview"
    )
    
    # Пути к данным
    DATA_ROOT: Path = Path(os.getenv("DATA_ROOT", "./data"))
    STAGE_P_ROOT: Path = Path(os.getenv("STAGE_P_ROOT", "./data/stage_p"))
    STAGE_R_ROOT: Path = Path(os.getenv("STAGE_R_ROOT", "./data/stage_r"))
    
    # Параметры обработки изображений
    VIEWPORT_SIZE: int = int(os.getenv("VIEWPORT_SIZE", "2048"))
    VIEWPORT_PADDING: int = int(os.getenv("VIEWPORT_PADDING", "512"))
    
    # Параметры подсветки блоков на изображениях
    HIGHLIGHT_COLOR_RGB: Tuple[int, int, int] = tuple(
        map(int, os.getenv("HIGHLIGHT_COLOR_RGB", "255,0,0").split(","))
    )  # type: ignore
    HIGHLIGHT_THICKNESS: int = int(os.getenv("HIGHLIGHT_THICKNESS", "10"))
    
    # Логирование
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Имена файлов по умолчанию
    MARKDOWN_FILENAME: str = "result.md"
    ANNOTATION_FILENAME: str = "annotation.json"
    
    # Параметры поиска
    # Порог для определения "маленьких" блоков (надписи на чертежах)
    SMALL_BLOCK_THRESHOLD: float = 0.2  # 20% от размера страницы
    
    # Порог расстояния для группировки близких блоков в один viewport (в пикселях)
    CLUSTERING_DISTANCE_THRESHOLD: int = 500
    
    # ===== Supabase Configuration =====
    # PostgreSQL БД для хранения чатов и сообщений
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    
    # Включить сохранение в БД
    USE_DATABASE: bool = os.getenv("USE_DATABASE", "false").lower() == "true"
    
    # ===== S3 / Cloudflare R2 Configuration =====
    # Хранилище для изображений и документов (по умолчанию R2)
    S3_ENDPOINT: str = os.getenv("R2_ENDPOINT_URL", os.getenv("S3_ENDPOINT", ""))
    S3_ACCESS_KEY: str = os.getenv("R2_ACCESS_KEY_ID", os.getenv("S3_ACCESS_KEY", ""))
    S3_SECRET_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", os.getenv("S3_SECRET_KEY", ""))
    S3_BUCKET: str = os.getenv("R2_BUCKET_NAME", os.getenv("S3_BUCKET", "aizoomdoc"))
    S3_REGION: str = os.getenv("S3_REGION", "auto") # R2 обычно использует 'auto'
    
    # Публичный домен (опционально)
    S3_PUBLIC_DOMAIN: str = os.getenv("R2_PUBLIC_DOMAIN", "")
    
    # Включить хранение в S3/R2
    USE_S3_STORAGE: bool = os.getenv("USE_S3_STORAGE", "true").lower() == "true"
    
    # Максимальный размер файла (МБ)
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    
    # TTL для подписанных S3 URLs (секунды)
    S3_URL_EXPIRATION: int = int(os.getenv("S3_URL_EXPIRATION", "3600"))

    @classmethod
    def validate(cls) -> None:
        """Проверяет обязательные параметры конфигурации."""
        if not cls.OPENROUTER_API_KEY:
            raise ValueError(
                "OPENROUTER_API_KEY не задан. Установите его в .env файле."
            )
        
        # Проверка Supabase (если включена БД)
        if cls.USE_DATABASE:
            if not cls.SUPABASE_URL:
                raise ValueError(
                    "SUPABASE_URL не задан."
                )
        
        # Проверка S3/R2
        if cls.USE_S3_STORAGE:
            if not cls.S3_ENDPOINT:
                 raise ValueError("R2_ENDPOINT_URL (или S3_ENDPOINT) не задан.")
            if not cls.S3_ACCESS_KEY or not cls.S3_SECRET_KEY:
                raise ValueError("R2/S3 ключи доступа не заданы.")
    
    @classmethod
    def get_document_paths(cls, root_path: Path) -> Tuple[Path, Path]:
        """
        Получить пути к result.md и annotation.json для указанной корневой папки.
        
        Args:
            root_path: Корневая папка с документами
        
        Returns:
            Кортеж (путь к markdown, путь к annotation)
        """
        markdown_path = root_path / cls.MARKDOWN_FILENAME
        annotation_path = root_path / cls.ANNOTATION_FILENAME
        return markdown_path, annotation_path


# Глобальный экземпляр конфигурации
config = Config()

