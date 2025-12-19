# Интеграция Supabase и S3 Cloud.ru

## Быстрый старт

### 1. Установка зависимостей

```bash
# Установить новые зависимости
pip install -r requirements.txt
```

### 2. Настройка переменных окружения

Скопируйте `env.example` в `.env` и заполните новые параметры:

```bash
cp env.example .env
```

Откройте `.env` и добавьте значения для:
- `SUPABASE_URL` - URL вашего проекта Supabase
- `SUPABASE_ANON_KEY` - анонимный ключ Supabase
- `SUPABASE_SERVICE_KEY` - сервис ключ для администратора
- `DATABASE_URL` - строка подключения PostgreSQL
- `S3_ACCESS_KEY` - ключ доступа cloud.ru
- `S3_SECRET_KEY` - секретный ключ cloud.ru
- `S3_BUCKET` - имя бакета в S3
- `USE_DATABASE=true` - включить сохранение в БД
- `USE_S3_STORAGE=true` - включить хранилище S3

### 3. Инициализация БД (выполнить миграции)

```bash
# Инициализировать БД
python scripts/manage_db.py init

# Или используя Alembic напрямую
alembic upgrade head
```

---

## Структура файлов

```
src/
├── config.py              # Конфигурация (обновлена с БД и S3 параметрами)
├── supabase_client.py     # Клиент для работы с Supabase
├── s3_storage.py          # Клиент для работы с S3 cloud.ru
├── models.py              # Модели данных
├── llm_client.py          # Клиент LLM
└── ...

migrations/
├── alembic.ini            # Конфигурация Alembic
├── env.py                 # Окружение для миграций
└── versions/
    └── 001_initial_schema.py  # Начальная миграция
```

---

## Примеры использования

### Работа с чатами

```python
from src.supabase_client import supabase_client
from src.s3_storage import s3_storage

# Создать новый чат
chat_id = await supabase_client.create_chat(
    title="Анализ документа XYZ",
    user_id="user_123",
    description="Поиск информации о вентиляции"
)

# Получить информацию о чате
chat = await supabase_client.get_chat(chat_id)
print(chat["title"])  # "Анализ документа XYZ"

# Получить список чатов пользователя
chats = await supabase_client.get_chats("user_123", limit=10)
for chat in chats:
    print(f"- {chat['title']} ({chat['created_at']})")

# Архивировать чат
await supabase_client.archive_chat(chat_id)
```

### Добавление сообщений

```python
# Добавить сообщение пользователя
message_id = await supabase_client.add_message(
    chat_id=chat_id,
    role="user",
    content="Найди информацию о системах вентиляции",
    message_type="text"
)

# Добавить ответ LLM
assistant_message_id = await supabase_client.add_message(
    chat_id=chat_id,
    role="assistant",
    content="Обнаружил информацию о вентиляции на странице 5...",
    message_type="text"
)

# Получить все сообщения чата
messages = await supabase_client.get_chat_messages(chat_id)
for msg in messages:
    print(f"[{msg['role']}] {msg['content']}")
```

### Работа с изображениями

```python
# Загрузить картинку на S3
local_image = "/path/to/viewport_step_1.png"
s3_path = s3_storage.generate_s3_path(
    chat_id=chat_id,
    file_type="viewport",
    filename="viewport_step_1.png"
)

s3_url = await s3_storage.upload_file(
    file_path=local_image,
    s3_key=s3_path,
    content_type="image/png",
    metadata={"description": "First zoom viewport"}
)

# Добавить картинку к сообщению в БД
image_id = await supabase_client.add_image_to_message(
    chat_id=chat_id,
    message_id=message_id,
    image_name="viewport_step_1.png",
    s3_path=s3_path,
    s3_url=s3_url,
    image_type="viewport",
    description="First zoom viewport",
    width=2048,
    height=1024,
    file_size=1024000
)

# Получить все картинки сообщения
images = await supabase_client.get_message_images(message_id)
for img in images:
    print(f"- {img['image_name']} ({img['image_type']})")
    print(f"  URL: {img['s3_url']}")
```

### Получить подписанный URL

```python
# Подписанный URL (с ограничением времени жизни)
signed_url = s3_storage.get_signed_url(
    s3_key=s3_path,
    expires_in=3600  # 1 час
)

print(f"Скачать: {signed_url}")
```

### Сохранение результатов поиска

```python
# Добавить результат поиска
result_id = await supabase_client.add_search_result(
    chat_id=chat_id,
    message_id=message_id,
    block_id="block_123",
    page_number=5,
    block_text="Система вентиляции состоит из...",
    coords_norm=[0.1, 0.2, 0.8, 0.5],
    coords_px=[100, 200, 800, 500]
)

# Получить все результаты поиска для чата
search_results = await supabase_client.get_search_results(chat_id)
for result in search_results:
    print(f"Page {result['page_number']}: {result['block_text'][:50]}...")
```

---

## Скрипты управления БД

### Инициализация

```bash
# Создать все таблицы
python scripts/manage_db.py init
```

### Просмотр статуса

```bash
# Текущая версия БД
python scripts/manage_db.py current

# История миграций
python scripts/manage_db.py history
```

### Обновление схемы

```bash
# Выполнить миграции до последней версии
python scripts/manage_db.py upgrade

# Выполнить до конкретной версии
python scripts/manage_db.py upgrade 001_initial_schema
```

### Откат изменений

```bash
# Откатить на одну версию назад
python scripts/manage_db.py downgrade -1
```

---

## Архитектура потока данных

### Сценарий: Пользователь отправляет запрос

```
1. User Input (GUI)
   ↓
2. Create Chat in Supabase
   ↓
3. Add User Message to Supabase
   ↓
4. Process Image (if any)
   ↓
5. Upload Image to S3
   ↓
6. Add Image Record to Supabase
   ↓
7. Search Documents
   ↓
8. Store Search Results in Supabase
   ↓
9. Generate Zoom Viewports
   ↓
10. Upload Viewports to S3
    ↓
11. Create Image Records for Viewports
    ↓
12. LLM processes and returns answer
    ↓
13. Add Assistant Message to Supabase
    ↓
14. Display Chat History from Supabase
```

---

## Обработка ошибок

### Если БД недоступна:
- Сообщения будут логироваться как предупреждения
- Приложение продолжит работу в локальном режиме
- Данные сохранятся локально

### Если S3 недоступно:
- Картинки сохранятся локально
- Ссылки на S3 не будут созданы
- Локальные пути будут использованы вместо S3 URLs

### Проверка подключения:

```python
# Проверить подключение к БД
if supabase_client.is_connected():
    print("✅ БД подключена")
else:
    print("❌ БД недоступна")

# Проверить подключение к S3
if s3_storage.is_connected():
    print("✅ S3 подключен")
else:
    print("❌ S3 недоступен")
```

---

## Security Notes

1. **Никогда** не коммитьте `.env` файл с реальными ключами
2. Используйте переменные окружения для production
3. Включите RLS (Row Level Security) в Supabase для изоляции данных пользователей
4. Используйте подписанные URLs для временного доступа к файлам S3
5. Регулярно ротируйте S3 ключи доступа

---

## Troubleshooting

### Ошибка подключения к Supabase:
```
ValueError: DATABASE_URL не установлена
```
**Решение**: Проверьте, что `DATABASE_URL` установлена в `.env`

### Ошибка подключения к S3:
```
NoCredentialsError: Unable to locate credentials
```
**Решение**: Проверьте `S3_ACCESS_KEY` и `S3_SECRET_KEY` в `.env`

### Ошибка при загрузке файла на S3:
```
Size of file exceeds limit
```
**Решение**: Увеличьте `MAX_FILE_SIZE_MB` в `.env` или уменьшите размер файла

### Ошибка миграции БД:
```
ERROR [alembic] Error creating migration script
```
**Решение**: 
```bash
# Проверьте логирование
python scripts/manage_db.py history

# Перезагрузитесь с чистого листа
python scripts/manage_db.py downgrade base
python scripts/manage_db.py upgrade
```

---

## Дальнейшие улучшения

1. **Кэширование**: Добавить Redis для кэширования часто используемых данных
2. **Синхронизация**: Реализовать sync между локальным хранилищем и облаком
3. **WebSocket**: Добавить real-time обновления чатов
4. **Backup**: Автоматическое резервное копирование S3 на другой сервис
5. **Analytics**: Отслеживание использования и статистика чатов

