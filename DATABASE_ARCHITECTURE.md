# Database and Storage Architecture

## 1. Обзор системы

### Компоненты:
- **Supabase** (PostgreSQL) - хранение метаданных чатов и сообщений
- **S3 Cloud.ru** - хранение изображений и документов
- **Локальное хранилище** - кэш и временные файлы

---

## 2. Схема БД Supabase

### Таблица: `chats`
Хранит основную информацию о чатах.

```sql
CREATE TABLE chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(255),  -- ID пользователя (можно расширить позже)
    is_archived BOOLEAN DEFAULT FALSE,
    document_path VARCHAR(512),  -- Путь к исходному документу в S3
    metadata JSONB DEFAULT '{}',  -- Дополнительные метаданные
    
    CONSTRAINT chats_title_not_empty CHECK (title != '')
);

CREATE INDEX idx_chats_user_id ON chats(user_id);
CREATE INDEX idx_chats_created_at ON chats(created_at DESC);
```

### Таблица: `chat_messages`
Хранит сообщения в чатах.

```sql
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_type VARCHAR(50) DEFAULT 'text',  -- text, code, search_result
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT chat_messages_content_not_empty CHECK (content != '')
);

CREATE INDEX idx_chat_messages_chat_id ON chat_messages(chat_id);
CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at);
```

### Таблица: `chat_images`
Хранит информацию об изображениях в сообщениях.

```sql
CREATE TABLE chat_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    image_name VARCHAR(512) NOT NULL,
    s3_path VARCHAR(1024) NOT NULL,  -- полный путь в S3 (например: chats/chat_id/images/image_name)
    s3_url VARCHAR(1024),  -- публичная ссылка на S3
    image_type VARCHAR(50),  -- viewport, zoom_crop, original, processed
    description TEXT,
    width INT,
    height INT,
    file_size INT,  -- размер в байтах
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT chat_images_paths_not_empty CHECK (image_name != '' AND s3_path != '')
);

CREATE INDEX idx_chat_images_chat_id ON chat_images(chat_id);
CREATE INDEX idx_chat_images_message_id ON chat_images(message_id);
CREATE INDEX idx_chat_images_s3_path ON chat_images(s3_path);
```

### Таблица: `search_results`
Хранит результаты поиска в документах.

```sql
CREATE TABLE search_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    block_id VARCHAR(255),  -- ID из annotation.json
    page_number INT,
    block_text TEXT,
    coords_norm JSONB,  -- нормализованные координаты [x1, y1, x2, y2]
    coords_px JSONB,    -- координаты в пикселях [x1, y1, x2, y2]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_search_results_chat_id ON search_results(chat_id);
CREATE INDEX idx_search_results_message_id ON search_results(message_id);
```

---

## 3. Структура S3 Cloud.ru

```
cloud-aizoomdoc/
├── chats/
│   ├── {chat_id_1}/
│   │   ├── images/
│   │   │   ├── viewport_step_1.png
│   │   │   ├── viewport_step_2.png
│   │   │   ├── zoom_crop_1.png
│   │   │   └── ...
│   │   └── document_original.pdf
│   ├── {chat_id_2}/
│   │   └── ...
├── uploads/
│   ├── documents/
│   │   └── {uploaded_pdf_files}
│   └── temp/
│       └── {temporary_files}
```

### Правила именования файлов в S3:
- **Viewport изображения**: `chats/{chat_id}/images/viewport_step_{step_number}_{timestamp}.png`
- **Zoom crop**: `chats/{chat_id}/images/zoom_crop_{zoom_id}_{timestamp}.png`
- **Оригинальные документы**: `chats/{chat_id}/document_{timestamp}.pdf`
- **Временные файлы**: `uploads/temp/{chat_id}/{file_type}_{timestamp}`

---

## 4. Переменные окружения (.env)

```ini
# ============================================
# Supabase Configuration
# ============================================
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_PASSWORD=your_postgres_password

# ============================================
# S3 Cloud.ru Configuration
# ============================================
S3_ENDPOINT=https://s3.cloud.ru
S3_ACCESS_KEY=your_access_key
S3_SECRET_KEY=your_secret_key
S3_BUCKET=cloud-aizoomdoc
S3_REGION=ru-1

# ============================================
# Application Settings
# ============================================
USE_DATABASE=true
USE_S3_STORAGE=true
DATABASE_LOG_LEVEL=ERROR  # DEBUG, INFO, ERROR
```

---

## 5. Миграции (Alembic)

Проект будет использовать **Alembic** для управления миграциями БД.

### Структура:
```
migrations/
├── versions/
│   ├── 001_initial_schema.py
│   ├── 002_add_indexes.py
│   └── ...
└── alembic.ini
```

---

## 6. Поток данных (примеры сценариев)

### Сценарий 1: Пользователь создает новый чат
1. Создается запись в `chats` (title, user_id, document_path)
2. Документ/URL загружаются в S3: `chats/{chat_id}/documents/`
3. Записывается путь в `chats.document_path`

### Сценарий 2: Пользователь отправляет сообщение
1. Сообщение создается в `chat_messages` (role='user', content)
2. Если есть картинки:
   - Загружаются в S3: `chats/{chat_id}/images/`
   - Создаются записи в `chat_images` со ссылками на S3
3. Выполняется поиск в документе
4. Результаты сохраняются в `search_results`

### Сценарий 3: LLM отправляет ответ с картинками
1. Ответ LLM создается в `chat_messages` (role='assistant')
2. Viewport и zoom crops загружаются в S3
3. Создаются записи в `chat_images` для каждого изображения
4. Ссылки на S3 встраиваются в контент сообщения

---

## 7. Примеры SQL запросов для частых операций

### Получить чат со всеми сообщениями и картинками
```sql
SELECT 
    c.id, c.title, c.created_at,
    m.id as message_id, m.role, m.content, m.created_at,
    img.id as image_id, img.s3_url, img.image_type
FROM chats c
LEFT JOIN chat_messages m ON c.id = m.chat_id
LEFT JOIN chat_images img ON m.id = img.message_id
WHERE c.id = $1
ORDER BY m.created_at ASC, img.uploaded_at ASC;
```

### Получить последние чаты пользователя
```sql
SELECT id, title, created_at, updated_at
FROM chats
WHERE user_id = $1
ORDER BY updated_at DESC
LIMIT 20;
```

### Удалить чат (каскадное удаление)
```sql
DELETE FROM chats WHERE id = $1;
-- Автоматически удалятся:
-- - все сообщения (chat_messages)
-- - все картинки (chat_images)
-- - все результаты поиска (search_results)
```

---

## 8. Безопасность и оптимизация

### Безопасность:
- RLS (Row Level Security) в Supabase для изоляции данных пользователей
- Подписанные S3 URLs с ограничением времени жизни
- Резервное копирование БД (встроенное в Supabase)

### Оптимизация:
- Индексы на часто используемых полях
- Кэширование списка чатов (Redis опционально)
- Лимиты и пагинация для больших результатов
- Soft delete для архивирования чатов

---

## 9. Обработка ошибок

- Если S3 недоступен → использовать локальное хранилище как fallback
- Если БД недоступна → режим offline с синхронизацией позже
- Retry логика для загрузок на S3 (3 попытки)

---

## 10. Примеры Python классов (API)

```python
# Pseudo code для демонстрации

class ChatDatabase:
    """Работа с БД чатов"""
    
    async def create_chat(self, title: str, user_id: str) -> str:
        # Создать чат, вернуть chat_id
        pass
    
    async def add_message(self, chat_id: str, role: str, content: str):
        # Добавить сообщение в чат
        pass
    
    async def add_image_to_message(self, message_id: str, image_path: str):
        # Загрузить картинку в S3, создать запись в БД
        pass
    
    async def get_chat_history(self, chat_id: str):
        # Получить весь чат с сообщениями и картинками
        pass

class S3Storage:
    """Работа с S3 Cloud.ru"""
    
    async def upload_file(self, chat_id: str, file_path: str, file_type: str) -> str:
        # Загрузить файл, вернуть S3 URL
        pass
    
    async def get_signed_url(self, s3_path: str, expires_in: int = 3600) -> str:
        # Получить подписанный URL
        pass
    
    async def delete_file(self, s3_path: str):
        # Удалить файл из S3
        pass
```

---

## 11. План реализации (этапы)

1. **Этап 1**: Настройка Supabase и S3
   - Создать проект Supabase
   - Создать бакет в S3 Cloud.ru
   - Получить credentials

2. **Этап 2**: Миграции БД
   - Установить Alembic
   - Написать 001_initial_schema.py миграцию
   - Применить миграции

3. **Этап 3**: Python клиенты
   - `supabase_client.py` - работа с БД
   - `s3_storage.py` - работа с S3

4. **Этап 4**: Интеграция в код
   - Обновить `config.py` с новыми параметрами
   - Добавить сохранение/загрузку чатов
   - Интегрировать картинки в S3

5. **Этап 5**: Тестирование и оптимизация
   - Unit тесты для БД операций
   - Integration тесты
   - Проверка производительности


