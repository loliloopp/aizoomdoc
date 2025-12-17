# Структура проекта AIZoomDoc

## Полное дерево проекта

```
aizoomdoc/
│
├── src/                              # Исходный код приложения
│   ├── __init__.py                   # Инициализация пакета
│   ├── config.py                     # Конфигурация приложения
│   ├── models.py                     # Модели данных (dataclasses)
│   ├── annotation_loader.py          # Загрузка annotation.json
│   ├── markdown_parser.py            # Парсинг result.md
│   ├── image_processor.py            # Viewport-кропы изображений
│   ├── search_engine.py              # Поисковый движок
│   ├── llm_client.py                 # Клиент OpenRouter API
│   └── main.py                       # CLI интерфейс
│
├── data/                             # Папка для входных данных
│   ├── README.md                     # Документация по формату данных
│   ├── .gitkeep                      # Для отслеживания папки в git
│   ├── result.md                     # (создаётся пользователем)
│   ├── annotation.json               # (создаётся пользователем)
│   ├── page_XXX_full.jpg             # (создаётся пользователем)
│   └── viewports/                    # (создаётся автоматически)
│
├── scripts/                          # Скрипты установки и запуска
│   ├── setup.bat                     # Установка для Windows
│   ├── setup.sh                      # Установка для Linux/Mac
│   ├── run_example.bat               # Пример запуска для Windows
│   └── run_example.sh                # Пример запуска для Linux/Mac
│
├── .gitignore                        # Игнорируемые git файлы
├── .env                              # Переменные окружения (не в git!)
├── .env.example                      # Пример конфигурации
├── mypy.ini                          # Конфигурация проверки типов
├── requirements.txt                  # Python зависимости
├── setup.py                          # Установочный скрипт
│
├── README.md                         # Основная документация
├── QUICKSTART.md                     # Быстрый старт
├── ARCHITECTURE.md                   # Архитектура приложения
├── USAGE_EXAMPLES.md                 # Примеры использования
├── CONTRIBUTING.md                   # Руководство по разработке
└── PROJECT_STRUCTURE.md              # Этот файл
```

## Описание модулей

### src/config.py

**Назначение:** Централизованная конфигурация

**Основные настройки:**
- OpenRouter API (ключ, URL, модель)
- Параметры обработки изображений (размер viewport, паддинг)
- Пути к данным
- Параметры визуализации (цвет подсветки, толщина линий)
- Уровень логирования

**Источник данных:** Переменные окружения из `.env`

**Использование:**
```python
from src.config import config

api_key = config.OPENROUTER_API_KEY
viewport_size = config.VIEWPORT_SIZE
```

### src/models.py

**Назначение:** Типобезопасные структуры данных

**Основные классы:**

| Класс | Описание |
|-------|----------|
| `Block` | Блок из annotation.json с координатами |
| `Page` | Страница с набором блоков |
| `AnnotationData` | Полные данные всех аннотаций |
| `MarkdownBlock` | Блок текста из result.md |
| `ViewportCrop` | Viewport-кроп изображения |
| `SearchResult` | Результат поиска (текст + изображения) |
| `ComparisonContext` | Контекст для сравнения двух стадий |

**Использование:**
```python
from src.models import Block, Page, SearchResult

block = Block(id="...", coords_px=[x1,y1,x2,y2], ...)
center_x = block.center_x
is_small = block.is_small_annotation(page.width, page.height)
```

### src/annotation_loader.py

**Назначение:** Загрузка и парсинг annotation.json

**Основные функции:**
- `AnnotationLoader.load(path)` — загрузить аннотации
- `AnnotationLoader.find_blocks_by_text(data, text)` — поиск блоков по тексту

**API:**
```python
from src.annotation_loader import AnnotationLoader

loader = AnnotationLoader()
data = loader.load(Path("data/annotation.json"))

page = data.get_page(1)
page, block = data.get_block_by_id("550e8400-...")
```

### src/markdown_parser.py

**Назначение:** Парсинг result.md с извлечением BLOCK_ID

**Основные методы:**
- `MarkdownParser(path)` — конструктор с автоматическим парсингом
- `get_blocks_by_keyword(keyword)` — поиск по ключевым словам
- `get_blocks_in_section(section)` — поиск в секции
- `get_block_by_id(block_id)` — получение блока по ID

**API:**
```python
from src.markdown_parser import MarkdownParser

parser = MarkdownParser(Path("data/result.md"))
blocks = parser.get_blocks_by_keyword("вентиляция")

for block in blocks:
    print(block.text)
    if block.block_id:
        print(f"Block ID: {block.block_id}")
```

### src/image_processor.py

**Назначение:** Создание viewport-кропов

**Основные методы:**
- `create_viewport_crop(page, blocks, ...)` — создать viewport
- `cluster_blocks(blocks, distance_threshold)` — кластеризация
- `create_viewports_for_blocks(page, blocks, ...)` — множественные viewport

**API:**
```python
from src.image_processor import ImageProcessor

processor = ImageProcessor(images_root=Path("data"))
viewport = processor.create_viewport_crop(
    page=page,
    blocks=[block1, block2],
    highlight=True,
    output_path=Path("data/viewports/crop.jpg")
)
```

### src/search_engine.py

**Назначение:** Поиск релевантной информации

**Основные методы:**
- `find_ventilation_equipment(query)` — поиск вентиляционного оборудования
- `search_by_keywords(keywords, ...)` — универсальный поиск
- `prepare_comparison(other_engine, query)` — подготовка сравнения

**API:**
```python
from src.search_engine import SearchEngine

engine = SearchEngine(data_root=Path("data"))
result = engine.find_ventilation_equipment("Найди АОВ8")

print(f"Найдено текстовых блоков: {len(result.text_blocks)}")
print(f"Найдено viewport-кропов: {len(result.viewport_crops)}")
```

### src/llm_client.py

**Назначение:** Взаимодействие с LLM через OpenRouter

**Основные методы:**
- `query(user_query, search_result, ...)` — запрос для одной стадии
- `query_comparison(user_query, stage_p, stage_r, ...)` — запрос сравнения

**API:**
```python
from src.llm_client import LLMClient

client = LLMClient(model="google/gemini-2.0-flash-thinking-exp")
answer = client.query(
    user_query="Найди всё оборудование",
    search_result=result
)
print(answer)
```

### src/main.py

**Назначение:** CLI интерфейс

**Основные функции:**
- `query_single_stage(data_root, query, model)` — запрос по одной стадии
- `query_comparison(stage_p, stage_r, query, model)` — сравнение стадий
- `main()` — точка входа CLI

**Использование:**
```bash
python -m src.main "query" --data-root ./data
python -m src.main "query" --stage-p ./p --stage-r ./r
```

## Файлы конфигурации

### .env (не в git!)

Содержит приватные настройки:

```env
OPENROUTER_API_KEY=sk-or-v1-...
DEFAULT_MODEL=google/gemini-2.0-flash-thinking-exp
VIEWPORT_SIZE=2048
DATA_ROOT=./data
LOG_LEVEL=INFO
```

**ВАЖНО:** Никогда не коммитьте `.env` в git!

### .env.example (в git)

Шаблон для `.env` с документацией и значениями по умолчанию.

### mypy.ini

Конфигурация проверки типов:

```ini
[mypy]
python_version = 3.12
warn_return_any = True

[mypy-cv2.*]
ignore_missing_imports = True
```

### requirements.txt

Python зависимости:

```
Pillow>=10.0.0
opencv-python>=4.8.0
requests>=2.31.0
python-dotenv>=1.0.0
mypy>=1.7.0
black>=23.12.0
```

## Скрипты

### scripts/setup.bat (Windows)

Автоматизирует установку:
1. Проверяет Python
2. Создаёт виртуальное окружение
3. Устанавливает зависимости
4. Создаёт `.env` из `.env.example`
5. Создаёт папки данных

**Использование:**
```cmd
cd aizoomdoc
scripts\setup.bat
```

### scripts/setup.sh (Linux/Mac)

Аналогично setup.bat для Unix-систем.

**Использование:**
```bash
cd aizoomdoc
chmod +x scripts/setup.sh
./scripts/setup.sh
```

### scripts/run_example.bat / .sh

Запускает пример запроса к приложению.

## Документация

### README.md

Основная документация:
- Описание проекта
- Установка
- Конфигурация
- Использование
- Примеры

### QUICKSTART.md

Пошаговое руководство для быстрого старта (20 минут от нуля до первого запроса).

### ARCHITECTURE.md

Детальное описание архитектуры:
- Принципы проектирования
- Описание модулей
- Алгоритмы
- Системный промт
- Расширяемость

### USAGE_EXAMPLES.md

Конкретные примеры использования:
- Базовые запросы
- Сравнение стадий
- Продвинутые сценарии
- Советы по формулированию запросов

### CONTRIBUTING.md

Руководство для разработчиков:
- Настройка окружения разработки
- Стандарты кодирования
- Workflow
- Добавление модулей

### PROJECT_STRUCTURE.md

Этот файл — полное описание структуры проекта.

## Папка данных (data/)

### Входные файлы (создаются пользователем)

**result.md** — Markdown с OCR-текстом:
```markdown
# Раздел ОВ

## Спецификация

| Поз | Наименование | Характеристики |
|-----|--------------|----------------|
| 1   | Вентилятор   | 1000 м³/ч      |

<!-- BLOCK_ID: 550e8400-... -->
АОВ8
<!-- END_BLOCK -->
```

**annotation.json** — Координаты блоков:
```json
{
  "pdf_path": "doc.pdf",
  "pages": [
    {
      "page_number": 1,
      "width": 9932,
      "height": 7015,
      "blocks": [...]
    }
  ]
}
```

**page_XXX_full.jpg** — Полноразмерные изображения страниц

### Выходные файлы (создаются автоматически)

**viewports/** — Viewport-кропы с подсветкой:
- `viewport_page001_00.jpg`
- `viewport_page001_01.jpg`
- и т.д.

## Зависимости проекта

### Основные (runtime)

| Пакет | Назначение |
|-------|------------|
| Pillow | Загрузка и базовая обработка изображений |
| opencv-python | Рисование подсветки, дополнительная обработка |
| requests | HTTP запросы к OpenRouter API |
| python-dotenv | Загрузка переменных окружения из .env |

### Разработка (dev)

| Пакет | Назначение |
|-------|------------|
| mypy | Проверка типов |
| black | Форматирование кода |
| isort | Сортировка импортов |

### Опциональные

| Пакет | Назначение |
|-------|------------|
| Pillow-SIMD | Ускоренная версия Pillow (требует компиляции) |
| fastapi, uvicorn | Для HTTP API в будущих версиях |

## Логирование

### Файлы логов

**aizoomdoc.log** — основной файл логов (создаётся автоматически)

### Уровни логирования

- `DEBUG` — детальная информация для отладки
- `INFO` — информационные сообщения (по умолчанию)
- `WARNING` — предупреждения
- `ERROR` — ошибки

**Настройка:** В `.env` установите `LOG_LEVEL=DEBUG`

### Пример логов

```
2024-12-16 10:00:00 - src.search_engine - INFO - SearchEngine инициализирован для data
2024-12-16 10:00:01 - src.search_engine - INFO - Поиск вентиляционного оборудования: Найди...
2024-12-16 10:00:02 - src.image_processor - INFO - Создан viewport для страницы 1: coords=(100, 200, 2148, 2248), блоков=2
2024-12-16 10:00:03 - src.llm_client - INFO - Отправка запроса к LLM (модель: google/gemini-2.0-flash-thinking-exp)
2024-12-16 10:00:15 - src.llm_client - INFO - Ответ от LLM получен успешно
```

## Потоки данных

### Простой запрос

```
Пользователь
    ↓
main.py (CLI)
    ↓
SearchEngine.find_ventilation_equipment()
    ↓
MarkdownParser.get_blocks_by_keyword()
    ↓
AnnotationLoader.get_block_by_id()
    ↓
ImageProcessor.create_viewport_crop()
    ↓
LLMClient.query()
    ↓
OpenRouter API
    ↓
Ответ пользователю
```

### Сравнение стадий

```
Пользователь (запрос + 2 папки)
    ↓
main.py (CLI)
    ↓
SearchEngine(stage_p) + SearchEngine(stage_r)
    ↓
Поиск в обеих стадиях параллельно
    ↓
LLMClient.query_comparison()
    ↓
Объединённый промт (стадия П + стадия Р)
    ↓
OpenRouter API
    ↓
Сравнительный ответ
```

## Расширяемость

### Добавление нового модуля

1. Создайте `src/new_module.py`
2. Добавьте docstring и type hints
3. Обновите `ARCHITECTURE.md`
4. Напишите примеры в `USAGE_EXAMPLES.md`

### Добавление новой модели LLM

Просто укажите в `.env` или CLI:

```env
DEFAULT_MODEL=anthropic/claude-3.5-sonnet
```

```bash
python -m src.main "query" --model "openai/gpt-4o"
```

### Добавление нового типа поиска

В `src/search_engine.py`:

```python
HEATING_KEYWORDS = ["отопление", "радиатор", "котёл"]

def find_heating_equipment(self, query: str) -> SearchResult:
    return self.search_by_keywords(self.HEATING_KEYWORDS)
```

## Контроль качества

### Проверка типов

```bash
mypy src/
```

### Форматирование

```bash
black src/
isort src/
```

### Проверка импортов

```bash
isort --check-only src/
```

## Размер проекта

Приблизительные размеры (без виртуального окружения и данных):

| Компонент | Размер |
|-----------|--------|
| Исходный код (src/) | ~15-20 KB |
| Документация (*.md) | ~100-150 KB |
| Скрипты (scripts/) | ~5 KB |
| Всего | ~120-175 KB |

**Зависимости (venv/):** ~200-300 MB

**Данные:** зависит от проекта (может быть гигабайты изображений)

## Версионирование

Текущая версия: **1.0.0**

Формат: MAJOR.MINOR.PATCH (семантическое версионирование)

- MAJOR: breaking changes
- MINOR: новые фичи, обратно совместимые
- PATCH: багфиксы

## Лицензия

Проект создан для внутреннего использования.

## Поддержка

- **Issues:** Создавайте issue в репозитории
- **Документация:** См. README.md, ARCHITECTURE.md
- **Примеры:** См. USAGE_EXAMPLES.md, QUICKSTART.md

