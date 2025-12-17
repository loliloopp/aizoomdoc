# Руководство по разработке AIZoomDoc

## Настройка окружения разработки

### 1. Клонирование и установка

```bash
git clone <repository-url>
cd aizoomdoc

# Создание виртуального окружения
python -m venv venv

# Активация
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Настройка .env

Скопируйте `.env.example` в `.env` и заполните:

```bash
copy .env.example .env  # Windows
cp .env.example .env    # Linux/Mac
```

## Стандарты кодирования

### Python Style Guide

Следуем [PEP 8](https://pep8.org/) с дополнениями:

1. **Type Hints:** Обязательны для всех публичных функций
2. **Docstrings:** Google Style для всех классов и функций
3. **Именование:**
   - Классы: `PascalCase`
   - Функции/методы: `snake_case`
   - Константы: `UPPER_CASE`
   - Приватные: `_leading_underscore`

### Пример хорошего кода

```python
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class MyModel:
    """Краткое описание модели.
    
    Attributes:
        field1: Описание поля
        field2: Описание поля
    """
    field1: str
    field2: int


def process_data(
    input_data: List[str],
    filter_empty: bool = True
) -> Optional[List[str]]:
    """
    Обрабатывает входные данные.
    
    Args:
        input_data: Список строк для обработки
        filter_empty: Удалять ли пустые строки
    
    Returns:
        Обработанные данные или None при ошибке
    
    Raises:
        ValueError: Если input_data пуст
    """
    if not input_data:
        raise ValueError("input_data не может быть пустым")
    
    result = [item.strip() for item in input_data]
    
    if filter_empty:
        result = [item for item in result if item]
    
    return result if result else None
```

## Инструменты разработки

### Black - Форматирование кода

```bash
# Форматирование всех файлов
black src/

# Проверка без изменений
black --check src/
```

### isort - Сортировка импортов

```bash
# Сортировка импортов
isort src/

# Проверка
isort --check-only src/
```

### mypy - Проверка типов

```bash
# Проверка типов
mypy src/
```

### Настройка mypy

Создайте `mypy.ini`:

```ini
[mypy]
python_version = 3.12
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True

[mypy-cv2.*]
ignore_missing_imports = True

[mypy-PIL.*]
ignore_missing_imports = True
```

## Структура коммитов

### Формат сообщений

```
<тип>: <краткое описание>

<опциональное детальное описание>

<опциональные ссылки>
```

### Типы коммитов

- `feat`: Новая функциональность
- `fix`: Исправление бага
- `docs`: Изменения в документации
- `style`: Форматирование, отступы (не влияет на код)
- `refactor`: Рефакторинг кода
- `test`: Добавление тестов
- `chore`: Обновление зависимостей, конфигов

### Примеры

```bash
git commit -m "feat: добавлен поиск по нескольким ключевым словам"

git commit -m "fix: исправлена ошибка при отсутствии изображения страницы"

git commit -m "docs: обновлена документация API"

git commit -m "refactor: упрощена логика кластеризации блоков"
```

## Workflow разработки

### 1. Создание ветки

```bash
git checkout -b feature/название-фичи
# или
git checkout -b fix/название-бага
```

### 2. Разработка

```bash
# Пишите код
# ...

# Форматирование и проверка
black src/
isort src/
mypy src/

# Коммит
git add .
git commit -m "feat: описание изменений"
```

### 3. Pull Request

1. Убедитесь, что код проходит все проверки
2. Добавьте описание изменений
3. Ссылайтесь на связанные issues
4. Запросите review

## Добавление новых модулей

### Шаблон модуля

```python
"""
Краткое описание модуля.
"""

import logging
from typing import List, Optional

from .models import SomeModel

logger = logging.getLogger(__name__)


class NewComponent:
    """Описание компонента."""
    
    def __init__(self, param: str):
        """
        Инициализирует компонент.
        
        Args:
            param: Описание параметра
        """
        self.param = param
        logger.info(f"NewComponent инициализирован: {param}")
    
    def process(self, data: List[str]) -> Optional[List[str]]:
        """
        Обрабатывает данные.
        
        Args:
            data: Входные данные
        
        Returns:
            Обработанные данные или None
        """
        logger.debug(f"Обработка {len(data)} элементов")
        # Логика обработки
        return data
```

### Обновление документации

При добавлении модуля обновите:

1. `README.md` - основная документация
2. `ARCHITECTURE.md` - архитектура
3. Docstrings в коде

## Тестирование (TODO в V2)

### Структура тестов

```
tests/
├── unit/
│   ├── test_annotation_loader.py
│   ├── test_markdown_parser.py
│   └── test_image_processor.py
├── integration/
│   └── test_search_engine.py
└── e2e/
    └── test_full_pipeline.py
```

### Запуск тестов

```bash
pytest tests/
pytest tests/unit/
pytest tests/integration/
```

### Покрытие кода

```bash
pytest --cov=src tests/
```

## Отладка

### Включение DEBUG логирования

В `.env`:

```env
LOG_LEVEL=DEBUG
```

### Использование логгера

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Детальная информация для отладки")
logger.info("Информационное сообщение")
logger.warning("Предупреждение")
logger.error("Ошибка", exc_info=True)  # Включает stack trace
```

### Проверка промта к LLM

В `src/llm_client.py` добавьте перед отправкой:

```python
import json

logger.debug(f"Промт к LLM:\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
```

## Производительность

### Профилирование

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Ваш код

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumtime')
stats.print_stats(20)
```

### Измерение времени

```python
import time

start = time.time()
# Операция
elapsed = time.time() - start
logger.info(f"Операция заняла {elapsed:.2f} сек")
```

## Частые проблемы и решения

### Проблема: ModuleNotFoundError

**Решение:**
```bash
# Убедитесь, что вы в корне проекта
cd aizoomdoc

# Запускайте через -m
python -m src.main "query" --data-root ./data
```

### Проблема: OpenCV не работает на Windows

**Решение:**
```bash
pip uninstall opencv-python
pip install opencv-python-headless
```

### Проблема: Pillow-SIMD не устанавливается

**Решение:**
```bash
# Pillow-SIMD опционален, можно использовать обычный Pillow
pip uninstall Pillow-SIMD
# Pillow уже должен быть установлен
```

## Расширение функциональности

### Добавление новых ключевых слов

В `src/search_engine.py`:

```python
class SearchEngine:
    VENTILATION_KEYWORDS = [
        # Существующие
        "вентиляция", "вентилятор",
        # Добавьте новые
        "рекуператор", "воздухонагреватель"
    ]
```

### Добавление нового типа поиска

```python
def find_heating_equipment(self, query: str) -> SearchResult:
    """Находит отопительное оборудование."""
    HEATING_KEYWORDS = ["отопление", "радиатор", "котёл"]
    return self.search_by_keywords(HEATING_KEYWORDS)
```

### Добавление новой модели LLM

В `.env`:

```env
DEFAULT_MODEL=anthropic/claude-3.5-sonnet
```

Или в командной строке:

```bash
python -m src.main "query" --data-root ./data --model "openai/gpt-4o"
```

## Контрибуция

### Процесс

1. Fork репозитория
2. Создайте ветку для фичи
3. Внесите изменения
4. Напишите/обновите тесты (когда будут)
5. Обновите документацию
6. Отправьте Pull Request

### Что приветствуется

- Исправления багов
- Улучшение документации
- Оптимизации производительности
- Новые фичи (после обсуждения в issues)

### Code Review

При review обращаем внимание на:

- Соответствие style guide
- Наличие type hints и docstrings
- Читаемость кода
- Обработка ошибок
- Логирование важных операций

## Контакты

Вопросы по разработке:
- Создайте issue в репозитории
- Опишите проблему подробно
- Приложите логи если возможно

