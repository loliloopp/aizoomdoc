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
        "google/gemini-2.0-flash-thinking-exp"
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
    
    @classmethod
    def validate(cls) -> None:
        """Проверяет обязательные параметры конфигурации."""
        if not cls.OPENROUTER_API_KEY:
            raise ValueError(
                "OPENROUTER_API_KEY не задан. Установите его в .env файле."
            )
    
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

