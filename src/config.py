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
    
    # ===== OpenRouter API (LEGACY - не используется) =====
    # OpenRouter отключён, все запросы идут через прямой Google Gemini SDK
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")  # legacy
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", 
        "https://openrouter.ai/api/v1"
    )  # legacy

    # ===== Google Gemini API (ОСНОВНОЙ) =====
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

    DEFAULT_MODEL: str = os.getenv(
        "DEFAULT_MODEL", 
        "gemini-3-flash-preview"  # Прямой вызов через Google SDK
    )

    # Параметры генерации LLM
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "8192"))
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "1.0"))
    LLM_TOP_P: float = float(os.getenv("LLM_TOP_P", "0.95"))
    
    # Разрешение медиа для Gemini: low, medium, high
    # high - для технических чертежей с мелкими деталями
    # medium - баланс качества и скорости
    # low - быстро и дешево
    MEDIA_RESOLUTION: str = os.getenv("MEDIA_RESOLUTION", "high")
    
    # ===== Thinking (Deep Think) настройки =====
    # Включить thinking для улучшения качества рассуждений
    THINKING_ENABLED: bool = os.getenv("THINKING_ENABLED", "true").lower() == "true"
    # Бюджет токенов для thinking (0 = без ограничений)
    THINKING_BUDGET: int = int(os.getenv("THINKING_BUDGET", "0"))
    
    # ===== Flash+Pro Token Budget =====
    # Целевой бюджет токенов для первого запроса в Pro (режим flash+pro)
    PRO_FIRST_REQUEST_TOKEN_BUDGET: int = int(os.getenv("PRO_FIRST_REQUEST_TOKEN_BUDGET", "100000"))
    
    # ===== Контроль размытости/детализации изображений =====
    # Максимальный размер стороны preview (px)
    PREVIEW_MAX_SIDE: int = int(os.getenv("PREVIEW_MAX_SIDE", "2000"))
    # Максимальный размер стороны zoom preview (px)
    ZOOM_PREVIEW_MAX_SIDE: int = int(os.getenv("ZOOM_PREVIEW_MAX_SIDE", "2000"))
    # Порог scale_factor для автоматического создания квадрантов
    AUTO_QUADRANTS_THRESHOLD: float = float(os.getenv("AUTO_QUADRANTS_THRESHOLD", "2.5"))
    # Требовать повторный zoom если кроп был scaled
    FORCE_REPEAT_ZOOM_IF_SCALED: bool = os.getenv("FORCE_REPEAT_ZOOM_IF_SCALED", "true").lower() == "true"
    # Максимальная глубина повторных zoom
    MAX_REPEAT_ZOOM_DEPTH: int = int(os.getenv("MAX_REPEAT_ZOOM_DEPTH", "3"))

    # Ранее в коде использовался флаг USE_DATABASE. БД для чатов считается основной всегда,
    # поэтому этот флаг не должен влиять на отправку запросов в модель. Оставляем для совместимости.
    USE_DATABASE: bool = True
    
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
    
    # ===== Supabase Chat DB (основная БД для чатов) =====
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    
    # ===== Supabase Projects DB (БД для дерева проектов) =====
    SUPABASE_PROJECTS_URL: str = os.getenv("SUPABASE_PROJECTS_URL", "")
    SUPABASE_PROJECTS_ANON_KEY: str = os.getenv("SUPABASE_PROJECTS_ANON_KEY", "")
    SUPABASE_PROJECTS_SERVICE_KEY: str = os.getenv("SUPABASE_PROJECTS_SERVICE_KEY", "")
    USE_PROJECTS_DATABASE: bool = os.getenv("USE_PROJECTS_DATABASE", "false").lower() == "true"
    
    # ===== S3 / Cloudflare R2 Configuration =====
    # Хранилище для изображений и документов (по умолчанию R2)
    S3_ENDPOINT: str = os.getenv("R2_ENDPOINT_URL", os.getenv("S3_ENDPOINT", ""))
    S3_ACCESS_KEY: str = os.getenv("R2_ACCESS_KEY_ID", os.getenv("S3_ACCESS_KEY", ""))
    S3_SECRET_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", os.getenv("S3_SECRET_KEY", ""))
    S3_BUCKET: str = os.getenv("R2_BUCKET_NAME", os.getenv("S3_BUCKET", "aizoomdoc"))
    S3_REGION: str = os.getenv("S3_REGION", "auto") # R2 обычно использует 'auto'
    
    # Публичный домен (опционально)
    S3_PUBLIC_DOMAIN: str = os.getenv("R2_PUBLIC_DOMAIN", "")
    
    # Публичный URL для разработки (опционально, например через туннель или dev-домен)
    S3_DEV_URL: str = os.getenv("S3_DEV_URL", "")
    USE_S3_DEV_URL: bool = os.getenv("USE_S3_DEV_URL", "false").lower() == "true"
    
    # URL для разработки (dev) бакета с файлами дерева проектов
    S3_PROJECTS_DEV_URL: str = os.getenv("S3_PROJECTS_DEV_URL", "")
    
    # Включить хранение в S3/R2
    USE_S3_STORAGE: bool = os.getenv("USE_S3_STORAGE", "true").lower() == "true"
    
    # Максимальный размер файла (МБ)
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    
    # TTL для подписанных S3 URLs (секунды)
    S3_URL_EXPIRATION: int = int(os.getenv("S3_URL_EXPIRATION", "3600"))

    @classmethod
    def validate(cls) -> None:
        """Проверяет обязательные параметры конфигурации."""
        # GOOGLE_API_KEY обязателен (OpenRouter отключён)
        if not cls.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY не задан. Установите его в .env файле для работы с Gemini API."
            )
        
        # Проверка Supabase Chat DB (обязательна)
        if not cls.SUPABASE_URL:
            raise ValueError("SUPABASE_URL не задан.")
        if not cls.SUPABASE_ANON_KEY:
            raise ValueError("SUPABASE_ANON_KEY не задан.")
        
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

