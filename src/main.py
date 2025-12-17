"""
Главный модуль приложения.
CLI интерфейс для анализа строительной документации.
"""

import argparse
import logging
import sys
from pathlib import Path

from .config import config
from .llm_client import LLMClient
from .search_engine import SearchEngine

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("aizoomdoc.log", encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)


def query_single_stage(
    data_root: Path,
    user_query: str,
    model: str = None
) -> str:
    """
    Обрабатывает запрос для одной стадии проектирования.
    
    Args:
        data_root: Корневая папка с данными
        user_query: Запрос пользователя
        model: Имя модели LLM (опционально)
    
    Returns:
        Ответ от LLM
    """
    logger.info(f"=== Обработка запроса для одной стадии ===")
    logger.info(f"Данные: {data_root}")
    logger.info(f"Запрос: {user_query}")
    
    # Проверяем наличие необходимых файлов
    markdown_path, annotation_path = config.get_document_paths(data_root)
    
    if not markdown_path.exists():
        raise FileNotFoundError(f"Файл не найден: {markdown_path}")
    if not annotation_path.exists():
        raise FileNotFoundError(f"Файл не найден: {annotation_path}")
    
    # Инициализируем компоненты
    search_engine = SearchEngine(data_root)
    llm_client = LLMClient(model=model)
    
    # Выполняем поиск
    logger.info("Выполнение поиска...")
    search_result = search_engine.find_ventilation_equipment(user_query)
    
    if search_result.is_empty():
        logger.warning("Поиск не дал результатов")
        return "К сожалению, по вашему запросу не найдено релевантной информации в документах."
    
    # Отправляем запрос к LLM
    logger.info("Отправка запроса к LLM...")
    answer = llm_client.query(user_query, search_result)
    
    return answer


def query_comparison(
    stage_p_root: Path,
    stage_r_root: Path,
    user_query: str,
    model: str = None
) -> str:
    """
    Обрабатывает запрос для сравнения двух стадий.
    
    Args:
        stage_p_root: Корневая папка стадии П
        stage_r_root: Корневая папка стадии Р
        user_query: Запрос пользователя
        model: Имя модели LLM (опционально)
    
    Returns:
        Ответ от LLM
    """
    logger.info(f"=== Обработка запроса сравнения двух стадий ===")
    logger.info(f"Стадия П: {stage_p_root}")
    logger.info(f"Стадия Р: {stage_r_root}")
    logger.info(f"Запрос: {user_query}")
    
    # Инициализируем компоненты для обеих стадий
    search_engine_p = SearchEngine(stage_p_root)
    search_engine_r = SearchEngine(stage_r_root)
    llm_client = LLMClient(model=model)
    
    # Выполняем поиск в обеих стадиях
    logger.info("Поиск в стадии П...")
    result_p = search_engine_p.find_ventilation_equipment(user_query)
    
    logger.info("Поиск в стадии Р...")
    result_r = search_engine_r.find_ventilation_equipment(user_query)
    
    if result_p.is_empty() and result_r.is_empty():
        logger.warning("Поиск не дал результатов ни в одной из стадий")
        return "К сожалению, по вашему запросу не найдено релевантной информации в документах обеих стадий."
    
    # Отправляем запрос сравнения к LLM
    logger.info("Отправка запроса сравнения к LLM...")
    answer = llm_client.query_comparison(user_query, result_p, result_r)
    
    return answer


def main():
    """Главная функция CLI."""
    parser = argparse.ArgumentParser(
        description="AIZoomDoc - Анализ строительной документации с помощью LLM"
    )
    
    parser.add_argument(
        "query",
        type=str,
        help="Запрос пользователя"
    )
    
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Путь к корневой папке с данными (для запроса по одной стадии)"
    )
    
    parser.add_argument(
        "--stage-p",
        type=Path,
        help="Путь к папке со стадией П (для сравнения)"
    )
    
    parser.add_argument(
        "--stage-r",
        type=Path,
        help="Путь к папке со стадией Р (для сравнения)"
    )
    
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Имя модели LLM (по умолчанию: {config.DEFAULT_MODEL})"
    )
    
    parser.add_argument(
        "--output",
        type=Path,
        help="Путь для сохранения результата в файл (опционально)"
    )
    
    args = parser.parse_args()
    
    try:
        # Проверяем конфигурацию
        config.validate()
        
        # Определяем режим работы
        if args.stage_p and args.stage_r:
            # Режим сравнения
            answer = query_comparison(
                stage_p_root=args.stage_p,
                stage_r_root=args.stage_r,
                user_query=args.query,
                model=args.model
            )
        elif args.data_root:
            # Режим одной стадии
            answer = query_single_stage(
                data_root=args.data_root,
                user_query=args.query,
                model=args.model
            )
        else:
            print("Ошибка: укажите либо --data-root, либо --stage-p и --stage-r")
            sys.exit(1)
        
        # Выводим результат
        print("\n" + "="*80)
        print("РЕЗУЛЬТАТ АНАЛИЗА")
        print("="*80 + "\n")
        print(answer)
        print("\n" + "="*80 + "\n")
        
        # Сохраняем в файл если указано
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(answer)
            logger.info(f"Результат сохранён в {args.output}")
        
    except Exception as e:
        logger.error(f"Ошибка выполнения: {e}", exc_info=True)
        print(f"\nОшибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

