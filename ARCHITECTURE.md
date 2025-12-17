# Архитектура AIZoomDoc

## Обзор

AIZoomDoc — модульное Python-приложение для анализа строительной документации с использованием RAG (Retrieval-Augmented Generation) и мультимодальных LLM.

## Ключевые принципы проектирования

### 1. Детерминизм и точность

- **Приоритет координатам:** Используем точные координаты из `annotation.json` вместо эвристик
- **Явная связь текст-геометрия:** Через BLOCK_ID между `result.md` и `annotation.json`
- **Консервативность:** Лучше сказать "данных нет", чем сделать неверное предположение

### 2. Модульность

Каждый модуль отвечает за одну ответственность:

```
config.py          → Конфигурация
models.py          → Структуры данных
annotation_loader  → Загрузка аннотаций
markdown_parser    → Парсинг Markdown
image_processor    → Обработка изображений
search_engine      → Поисковая логика
llm_client         → Взаимодействие с LLM
main.py            → Оркестрация
```

### 3. Разделение текста и изображений

**Текстовый контекст:**
- Спецификации оборудования
- Таблицы характеристик
- Пояснительные записки
- Большие блоки с OCR-текстом

**Визуальный контекст:**
- Надписи на чертежах (короткие, < 20% размера страницы)
- Размерные линии
- Марки оборудования
- Осевые обозначения

## Модули

### config.py

**Назначение:** Централизованная конфигурация

**Ключевые параметры:**
- API ключи и URL
- Размеры viewport и паддинга
- Пути к данным
- Параметры визуализации

**Источник:** Переменные окружения из `.env`

### models.py

**Назначение:** Типобезопасные структуры данных

**Основные классы:**

```python
Block          # Блок из annotation.json с координатами
Page           # Страница с набором блоков
AnnotationData # Полные данные аннотаций
MarkdownBlock  # Блок текста из result.md
ViewportCrop   # Viewport-кроп изображения
SearchResult   # Результат поиска
```

**Особенности:**
- Используем `dataclasses` для простоты
- Type hints для всех полей
- Методы-свойства для вычисляемых значений (center_x, width, etc.)

### annotation_loader.py

**Назначение:** Загрузка и парсинг `annotation.json`

**API:**

```python
loader = AnnotationLoader()
data = loader.load(path)

# Поиск
page = data.get_page(page_number)
page, block = data.get_block_by_id(block_id)
results = loader.find_blocks_by_text(data, "АОВ8")
```

**Особенности:**
- Проверка существования файла
- Валидация JSON-структуры
- Преобразование строковых enum в типы Python

### markdown_parser.py

**Назначение:** Парсинг `result.md` с извлечением BLOCK_ID

**API:**

```python
parser = MarkdownParser(markdown_path)

# Поиск
blocks = parser.get_blocks_by_keyword("вентиляция")
blocks = parser.get_blocks_in_section("Спецификация")
block = parser.get_block_by_id(block_id)
```

**Алгоритм парсинга:**

1. Построчное чтение
2. Отслеживание иерархии заголовков (context)
3. Извлечение HTML-комментариев с BLOCK_ID
4. Группировка текста в блоки

**Формат BLOCK_ID:**

```markdown
<!-- BLOCK_ID: a4fb8613-da50-4751-a937-74791cf8fd47 -->
Текст блока
<!-- END_BLOCK -->
```

### image_processor.py

**Назначение:** Динамический контекстный кроп (Viewport Strategy)

**Ключевые методы:**

```python
processor = ImageProcessor(images_root)

# Создание одного viewport
viewport = processor.create_viewport_crop(
    page=page,
    blocks=[block1, block2],
    highlight=True
)

# Кластеризация и создание нескольких viewport
clusters = processor.cluster_blocks(blocks)
viewports = processor.create_viewports_for_blocks(page, blocks)
```

**Алгоритм viewport:**

1. Вычисление центра блока(ов): `(cx, cy)`
2. Определение размера viewport с учётом паддинга
3. Обрезка по границам страницы
4. Опционально: подсветка целевых блоков красными рамками
5. Сохранение кропа

**Кластеризация:**

```python
# Жадная кластеризация по расстоянию
for each block:
    find nearby blocks (distance < threshold)
    group into cluster
```

### search_engine.py

**Назначение:** Поиск релевантной информации

**API:**

```python
engine = SearchEngine(data_root)

# Поиск оборудования
result = engine.find_ventilation_equipment(query)

# Универсальный поиск
result = engine.search_by_keywords(["вентилятор", "АОВ"])

# Сравнение стадий
context = engine.prepare_comparison(other_engine, query)
```

**Алгоритм поиска:**

```
1. Поиск в секциях спецификаций
   ↓
2. Поиск по ключевым словам в тексте
   ↓
3. Извлечение block_id из найденных блоков
   ↓
4. Получение координат из annotation.json
   ↓
5. Фильтрация: маленькие блоки → изображения
   ↓
6. Создание viewport-кропов
   ↓
7. Формирование SearchResult
```

**Ключевые слова (V1):**

```python
VENTILATION_KEYWORDS = [
    "вентиляция", "вентилятор", "аов",
    "приточ", "вытяж", "воздух", ...
]

SPECIFICATION_SECTION_KEYWORDS = [
    "спецификация", "ведомость",
    "экспликация", "перечень", ...
]
```

### llm_client.py

**Назначение:** Взаимодействие с OpenRouter API

**API:**

```python
client = LLMClient(model="google/gemini-2.0-flash-thinking-exp")

# Запрос к одной стадии
answer = client.query(user_query, search_result)

# Сравнение стадий
answer = client.query_comparison(
    user_query,
    stage_p_result,
    stage_r_result
)
```

**Формат мультимодального промта:**

```json
{
  "model": "...",
  "messages": [
    {
      "role": "system",
      "content": "Ты — инженер-проектировщик..."
    },
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "ЗАПРОС: ...\nТЕКСТОВЫЙ КОНТЕКСТ: ...\n..."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
      ]
    }
  ]
}
```

**Системный промт:**

Определяет персону инженера-проектировщика с акцентом на:
- Точность и консерватизм
- Явное указание неопределённости
- Ссылки на источники
- Структурированность

### main.py

**Назначение:** CLI интерфейс и оркестрация

**Режимы работы:**

1. **Одна стадия:**
   ```bash
   python -m src.main "query" --data-root ./data
   ```

2. **Сравнение:**
   ```bash
   python -m src.main "query" --stage-p ./p --stage-r ./r
   ```

**Поток выполнения:**

```
CLI args → Validation
    ↓
Load config
    ↓
SearchEngine init
    ↓
Search
    ↓
LLMClient init
    ↓
Query LLM
    ↓
Format & Output
```

## Поток данных

### Входные данные

```
data/
├── result.md           ← OCR-текст, структурированный Markdown
├── annotation.json     ← Координаты блоков
└── page_XXX_full.jpg   ← Полноразмерные изображения страниц
```

### Обработка

```
result.md → MarkdownParser → MarkdownBlock[]
                                    ↓
                                BLOCK_ID
                                    ↓
annotation.json → AnnotationLoader → Block[] with coords
                                    ↓
page_XXX.jpg → ImageProcessor → ViewportCrop[]
```

### Вывод

```
SearchResult {
    text_blocks: MarkdownBlock[]
    viewport_crops: ViewportCrop[]
    relevant_pages: int[]
}
    ↓
LLMClient.query()
    ↓
Multimodal Prompt (text + images base64)
    ↓
OpenRouter API
    ↓
LLM Response (structured text)
```

## Стратегия Viewport

### Проблема статической сетки

❌ **Naive Grid Tiling:**
```
┌───┬───┬───┐
│ 1 │ 2 │ 3 │  Фиксированная сетка
├───┼───┼───┤  Не учитывает контекст
│ 4 │ 5 │ 6 │  Может разрезать важные элементы
└───┴───┴───┘
```

### Решение: Динамический viewport

✅ **Context-Aware Viewport:**
```
         ┌─────────────┐
         │   padding   │
         │  ┌───────┐  │
         │  │target │  │  Viewport центрирован на целевом блоке
         │  │ block │  │  Достаточный контекст вокруг
         │  └───────┘  │
         │   padding   │
         └─────────────┘
```

**Алгоритм:**

1. Целевой блок: `coords_px = [x1, y1, x2, y2]`
2. Центр: `cx = (x1+x2)/2, cy = (y1+y2)/2`
3. Viewport: `[cx-w/2, cy-h/2, cx+w/2, cy+h/2]`
4. Паддинг: гарантирует контекст вокруг
5. Clipping: обрезка по границам страницы

**Кластеризация близких блоков:**

```python
if distance(block1, block2) < THRESHOLD:
    viewport = cover_both(block1, block2)
else:
    viewport1 = create_for(block1)
    viewport2 = create_for(block2)
```

## Системный промт

### Цель

Настроить LLM на роль инженера-проектировщика с консервативным подходом.

### Ключевые директивы

1. **ТОЧНОСТЬ И КОНСЕРВАТИЗМ**
   - Избегать догадок
   - Опираться только на предоставленные данные

2. **ЯВНОЕ УКАЗАНИЕ НЕОПРЕДЕЛЁННОСТИ**
   - "Информация отсутствует" лучше, чем неверный ответ

3. **ССЫЛКИ НА ИСТОЧНИКИ**
   - Номер листа
   - Раздел спецификации
   - Block ID (опционально)

4. **СТРУКТУРИРОВАННОСТЬ**
   - Резюме
   - Детальная информация
   - Источники
   - Ограничения

5. **ТЕРМИНОЛОГИЯ**
   - Профессиональная инженерная лексика
   - Правильные единицы измерения

### Полный текст

См. `src/llm_client.py`, константа `SYSTEM_PROMPT`

## Ограничения V1

### Текущие ограничения

1. **Поиск:** Только ключевые слова (без эмбеддингов)
2. **Хранение:** Всё в памяти (без БД)
3. **Кэш:** Нет кэширования результатов
4. **Область:** Жёстко заданные ключевые слова для вентиляции
5. **Масштабируемость:** Не оптимизировано для больших проектов (сотни листов)

### Почему это приемлемо

- Фокус на точности, а не на скорости
- Детерминизм важнее "умного" поиска
- V1 = proof-of-concept
- Векторный поиск можно добавить в V2

## Расширяемость (V2+)

### Векторный поиск

```python
# Эмбеддинги для семантического поиска
embeddings = OpenAIEmbeddings()
vectorstore = FAISS.from_documents(blocks, embeddings)
```

### Кэширование

```python
# Redis для кэширования viewport
cache.set(f"viewport:{page}:{block_id}", crop_image)
```

### HTTP API

```python
# FastAPI эндпоинты
@app.post("/api/query")
async def query(request: QueryRequest):
    ...

@app.post("/api/compare")
async def compare(request: CompareRequest):
    ...
```

### Расширенная кластеризация

```python
# DBSCAN или HDBSCAN вместо жадного алгоритма
clustering = DBSCAN(eps=500, min_samples=2)
labels = clustering.fit_predict(block_centers)
```

### Мультипроцессинг

```python
# Параллельная обработка страниц
with ProcessPoolExecutor() as executor:
    viewports = executor.map(create_viewport, pages)
```

## Тестирование (TODO)

### Unit Tests

```python
# test_annotation_loader.py
def test_load_annotation():
    data = AnnotationLoader.load("test.json")
    assert len(data.pages) > 0

# test_viewport.py
def test_viewport_creation():
    viewport = processor.create_viewport_crop(...)
    assert viewport is not None
```

### Integration Tests

```python
# test_search_engine.py
def test_find_equipment():
    engine = SearchEngine("test_data")
    result = engine.find_ventilation_equipment("АОВ")
    assert len(result.text_blocks) > 0
```

### End-to-End Tests

```python
# test_e2e.py
def test_full_pipeline():
    answer = query_single_stage("test_data", "Найди АОВ8")
    assert "АОВ8" in answer
```

## Безопасность

### API Keys

- Хранение в `.env` (не коммитим в git)
- Валидация при старте приложения

### Изображения

- Кодирование в base64 перед отправкой
- Ограничение размера изображений

### Логирование

- Не логируем API ключи
- Sanitize user queries перед логированием

## Производительность

### Оптимизации V1

- Кэширование загруженных изображений страниц в памяти
- Кластеризация блоков для уменьшения количества viewport
- Фильтрация: только маленькие блоки → изображения

### Метрики (TODO)

- Время поиска
- Время создания viewport
- Время запроса к LLM
- Размер промта (токены)

## Документация кода

### Docstrings

Формат Google Style:

```python
def create_viewport_crop(
    self,
    page: Page,
    blocks: List[Block],
    viewport_size: int = None
) -> Optional[ViewportCrop]:
    """
    Создаёт viewport-кроп вокруг блоков.
    
    Args:
        page: Страница документа
        blocks: Список блоков для viewport
        viewport_size: Размер viewport в пикселях
    
    Returns:
        ViewportCrop объект или None при ошибке
    """
```

### Type Hints

Обязательны для всех публичных API:

```python
def query(
    self,
    user_query: str,
    search_result: SearchResult,
    temperature: float = 0.1
) -> str:
    ...
```

## Заключение

AIZoomDoc построен на принципах:
- **Детерминизм** над эвристиками
- **Точность** над креативностью
- **Модульность** для расширяемости
- **Type Safety** для надёжности

Архитектура позволяет легко добавлять новые возможности (векторный поиск, HTTP API, другие разделы документации) без изменения core-логики.

