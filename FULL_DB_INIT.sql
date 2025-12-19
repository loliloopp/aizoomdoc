-- ==============================================================================
-- FULL DATABASE INITIALIZATION SCRIPT
-- Запускать в Supabase SQL Editor
-- ==============================================================================

-- 1. Включаем расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Таблица ПАПОК (Создается первой, так как нет зависимостей)
CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    parent_id UUID REFERENCES folders(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Таблица ФАЙЛОВ (Central Storage Registry)
CREATE TABLE IF NOT EXISTS storage_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255),
    source_type VARCHAR(50) NOT NULL, -- 'user_upload', 'llm_generated', 'external_link'
    storage_path VARCHAR(1024), -- Путь в R2/S3
    external_url TEXT,          -- Внешняя ссылка
    filename VARCHAR(512),
    mime_type VARCHAR(100),
    size_bytes BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. Связь ФАЙЛОВ с ПАПКАМИ
CREATE TABLE IF NOT EXISTS folder_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    folder_id UUID REFERENCES folders(id) ON DELETE CASCADE NOT NULL,
    file_id UUID REFERENCES storage_files(id) ON DELETE CASCADE NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(folder_id, file_id)
);

-- 5. Таблица ЧАТОВ (Ссылается на storage_files)
CREATE TABLE IF NOT EXISTS chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    user_id VARCHAR(255),
    is_archived BOOLEAN DEFAULT FALSE,
    document_file_id UUID REFERENCES storage_files(id) ON DELETE SET NULL, -- Ссылка на файл
    document_path VARCHAR(512), -- Legacy поле (можно игнорировать)
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    CONSTRAINT chats_title_not_empty CHECK (title != '')
);

-- 6. Таблица СООБЩЕНИЙ
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_type VARCHAR(50) DEFAULT 'text',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    CONSTRAINT chat_messages_content_not_empty CHECK (content != '')
);

-- 7. Таблица КАРТИНОК В ЧАТЕ (Ссылается на storage_files)
CREATE TABLE IF NOT EXISTS chat_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE NOT NULL,
    message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE NOT NULL,
    file_id UUID REFERENCES storage_files(id) ON DELETE CASCADE, -- Ссылка на файл
    image_type VARCHAR(50),
    description TEXT,
    width INTEGER,
    height INTEGER,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 8. Вложения ФАЙЛОВ в СООБЩЕНИЯ (Attachment)
CREATE TABLE IF NOT EXISTS message_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE NOT NULL,
    file_id UUID REFERENCES storage_files(id) ON DELETE CASCADE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 9. РЕЗУЛЬТАТЫ ПОИСКА
CREATE TABLE IF NOT EXISTS search_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE NOT NULL,
    message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE NOT NULL,
    block_id VARCHAR(255),
    page_number INTEGER,
    block_text TEXT,
    coords_norm JSONB,
    coords_px JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 10. Индексы для производительности
CREATE INDEX IF NOT EXISTS idx_folders_user_id ON folders(user_id);
CREATE INDEX IF NOT EXISTS idx_storage_files_user_id ON storage_files(user_id);
CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_chat_images_message_id ON chat_images(message_id);
CREATE INDEX IF NOT EXISTS idx_search_results_chat_id ON search_results(chat_id);

-- 11. View для удобства (Опционально)
CREATE OR REPLACE VIEW view_folder_contents AS
SELECT 
    f.id as folder_id,
    f.name as folder_name,
    sf.id as file_id,
    sf.filename,
    sf.source_type,
    sf.storage_path,
    sf.external_url,
    sf.created_at
FROM folders f
JOIN folder_items fi ON f.id = fi.folder_id
JOIN storage_files sf ON fi.file_id = sf.id;

