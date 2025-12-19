-- ==============================================================================
-- AIZOOMDOC DATABASE SCHEMA V2 (Folders & R2 Integration)
-- Запустите этот скрипт в SQL Editor вашего Supabase проекта
-- ==============================================================================

-- 1. Включаем расширение UUID если еще нет
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Таблица ПАПОК (Folders)
CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL, -- Владелец папки
    name VARCHAR(255) NOT NULL,
    parent_id UUID REFERENCES folders(id) ON DELETE CASCADE, -- Для вложенности (на будущее)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_folders_user_id ON folders(user_id);

-- 3. Центральная таблица ФАЙЛОВ (Storage Files)
-- Хранит ссылки на объекты в R2 или внешние ссылки
CREATE TABLE IF NOT EXISTS storage_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255), -- Кто загрузил/создал
    
    -- Тип источника
    source_type VARCHAR(50) NOT NULL, 
    -- 'user_upload' (загружено пользователем в чат/папку)
    -- 'llm_generated' (кроп/зум от LLM)
    -- 'external_link' (ссылка на интернет ресурс)
    
    -- Данные хранения
    storage_path VARCHAR(1024), -- Путь в бакете (ключ S3/R2), NULL если external_link
    external_url TEXT,          -- Прямая ссылка если это ресурс из интернета
    
    -- Метаданные файла
    filename VARCHAR(512),
    mime_type VARCHAR(100),
    size_bytes BIGINT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_storage_files_user_id ON storage_files(user_id);

-- 4. Связь ПАПКА <-> ФАЙЛ (Folder Items)
-- Позволяет файлу находиться в папке
CREATE TABLE IF NOT EXISTS folder_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    folder_id UUID REFERENCES folders(id) ON DELETE CASCADE NOT NULL,
    file_id UUID REFERENCES storage_files(id) ON DELETE CASCADE NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(folder_id, file_id) -- Файл в папке только один раз
);

-- 5. Обновляем таблицу CHATS
-- Удаляем старый document_path, теперь документ чата - это ссылка на storage_files
ALTER TABLE chats 
    ADD COLUMN IF NOT EXISTS document_file_id UUID REFERENCES storage_files(id) ON DELETE SET NULL;

-- (Опционально) Если данные уже есть, можно мигрировать document_path в storage_files вручную,
-- но так как БД чистая, просто удаляем старую колонку.
ALTER TABLE chats DROP COLUMN IF EXISTS document_path;


-- 6. Обновляем таблицу CHAT_IMAGES (картинки в сообщениях)
-- Теперь картинка ссылается на storage_files вместо хранения путей
ALTER TABLE chat_images 
    ADD COLUMN IF NOT EXISTS file_id UUID REFERENCES storage_files(id) ON DELETE CASCADE;

-- Оставляем chat_images для специфичных метаданных (ширина, высота, описание для LLM),
-- но пути (s3_path, s3_url) теперь берем из storage_files.
-- Можно удалить старые колонки:
ALTER TABLE chat_images DROP COLUMN IF EXISTS s3_path;
ALTER TABLE chat_images DROP COLUMN IF EXISTS s3_url;
ALTER TABLE chat_images DROP COLUMN IF EXISTS image_name;
ALTER TABLE chat_images DROP COLUMN IF EXISTS file_size; 
-- file_size переехал в storage_files, но width/height оставим тут как свойства отображения

-- 7. Таблица вложений сообщений (Message Attachments)
-- Для сценария "прикрепить файлы из папки к запросу"
CREATE TABLE IF NOT EXISTS message_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE NOT NULL,
    file_id UUID REFERENCES storage_files(id) ON DELETE CASCADE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_msg_attachments_message_id ON message_attachments(message_id);

-- ==============================================================================
-- VIEWS (Опционально, для удобства просмотра)
-- ==============================================================================

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

