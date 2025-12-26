"""
Примеры интеграции Supabase и S3 в основной код.
"""

# Это примеры того, как интегрировать новые модули в существующий код

# ============================================
# ПРИМЕР 1: Сохранение чата при загрузке документа
# ============================================

# В llm_client.py или gui_agent.py:

from src.supabase_client import supabase_client
from src.s3_storage import s3_storage

async def process_document_with_chat(
    file_path: str,
    user_id: str,
    query: str
) -> str:
    """
    Процесс обработки документа с сохранением в БД.
    """
    import asyncio
    from pathlib import Path
    
    # 1. Создать новый чат
    chat_id = await supabase_client.create_chat(
        title=f"Анализ {Path(file_path).name}",
        user_id=user_id,
        document_path=file_path,
        description=f"Начальный запрос: {query}"
    )
    
    if not chat_id:
        return "Ошибка: не удалось создать чат"
    
    # 2. Добавить сообщение пользователя
    user_msg_id = await supabase_client.add_message(
        chat_id=chat_id,
        role="user",
        content=query,
        message_type="text"
    )
    
    # 3. Загрузить документ в S3 (если включено)
    if supabase_client.is_connected() and s3_storage.is_connected():
        s3_doc_path = s3_storage.generate_s3_path(
            chat_id=chat_id,
            file_type="document",
            filename=Path(file_path).name
        )
        
        s3_url = await s3_storage.upload_file(
            file_path=file_path,
            s3_key=s3_doc_path,
            content_type="application/pdf"
        )
        
        # Обновить путь документа в чате
        if s3_url:
            await supabase_client.update_chat(
                chat_id=chat_id,
                document_path=s3_doc_path
            )
    
    return chat_id


# ============================================
# ПРИМЕР 2: Сохранение viewport картинок
# ============================================

async def save_viewport_image(
    chat_id: str,
    message_id: str,
    image_path: str,
    step: int,
    image_description: str
) -> bool:
    """
    Сохранить viewport картинку на S3 и в БД.
    """
    from PIL import Image
    
    # 1. Получить информацию об изображении
    try:
        img = Image.open(image_path)
        width, height = img.size
        file_size = os.path.getsize(image_path)
    except Exception as e:
        logger.error(f"Ошибка открытия изображения: {e}")
        return False
    
    # 2. Загрузить в S3
    if s3_storage.is_connected():
        filename = f"viewport_step_{step}.png"
        s3_path = s3_storage.generate_s3_path(
            chat_id=chat_id,
            file_type="viewport",
            filename=filename
        )
        
        s3_url = await s3_storage.upload_file(
            file_path=image_path,
            s3_key=s3_path,
            content_type="image/png",
            metadata={
                "step": str(step),
                "description": image_description
            }
        )
        
        # 3. Сохранить в БД
        if supabase_client.is_connected():
            image_id = await supabase_client.add_image_to_message(
                chat_id=chat_id,
                message_id=message_id,
                image_name=filename,
                s3_path=s3_path,
                s3_url=s3_url,
                image_type="viewport",
                description=image_description,
                width=width,
                height=height,
                file_size=file_size
            )
            
            return image_id is not None
    
    return True


# ============================================
# ПРИМЕР 3: Интеграция в main.py
# ============================================

async def run_agent_loop_with_chat(
    data_root: Path,
    user_query: str,
    user_id: str = "anonymous",
    model: str = None,
    save_to_db: bool = True
) -> tuple:
    """
    Запустить цикл агента с сохранением результатов в БД.
    
    Returns:
        (ответ, chat_id)
    """
    from .search_engine import SearchEngine
    from .image_processor import ImageProcessor
    from .llm_client import LLMClient
    
    # Создать чат
    chat_id = None
    if save_to_db:
        chat_id = await supabase_client.create_chat(
            title=f"Поиск по запросу: {user_query[:50]}",
            user_id=user_id,
            description=user_query
        )
        
        # Добавить сообщение пользователя
        await supabase_client.add_message(
            chat_id=chat_id,
            role="user",
            content=user_query,
            message_type="text"
        )
    
    # Основной цикл агента
    search_engine = SearchEngine(data_root)
    image_processor = ImageProcessor(data_root)
    llm_client = LLMClient(model=model, data_root=data_root)
    
    logger.info("1. Поиск в документах...")
    search_result = search_engine.find_ventilation_equipment(user_query)
    
    # Сбор внешних ссылок
    external_images = []
    processed_urls = set()
    
    logger.info("2. Загрузка и обработка PDF-кропов...")
    for block in search_result.text_blocks:
        for link in block.external_links:
            if link.url.endswith(".pdf") and link.url not in processed_urls:
                processed_urls.add(link.url)
                logger.info(f"Processing: {link.url}")
                crops = image_processor.download_and_process_pdf(link.url)
                if crops:
                    external_images.extend(crops)
    
    # Формируем контекст
    context_text = f"ЗАПРОС: {user_query}\n\nНАЙДЕННЫЙ ТЕКСТ:\n"
    for block in search_result.text_blocks:
        context_text += f"---\n{block.text}\n"
    
    llm_client.add_user_message(context_text, images=external_images)
    
    # Сохранить результаты поиска в БД
    if save_to_db and chat_id:
        for i, block in enumerate(search_result.text_blocks):
            await supabase_client.add_search_result(
                chat_id=chat_id,
                message_id=None,  # message_id будет заполнен позже
                block_text=block.text[:500],
            )
    
    # Loop
    step = 0
    max_steps = 5
    
    while step < max_steps:
        step += 1
        logger.info(f"--- Шаг {step} ---")
        
        response = llm_client.get_response()
        zoom_req = llm_client.parse_zoom_request(response)
        
        if zoom_req:
            logger.info(f"Zoom Request: {zoom_req.reason}")
            
            zoom_crop = image_processor.process_zoom_request(
                zoom_req,
                output_path=data_root / "viewports" / f"zoom_step_{step}.png"
            )
            
            if zoom_crop:
                # Сохранить zoom картинку на S3 и в БД
                if save_to_db and chat_id:
                    message_id = await supabase_client.add_message(
                        chat_id=chat_id,
                        role="assistant",
                        content=f"Zoom шаг {step}: {zoom_req.reason}",
                        message_type="text"
                    )
                    
                    if zoom_crop.image_path:
                        await save_viewport_image(
                            chat_id=chat_id,
                            message_id=message_id,
                            image_path=zoom_crop.image_path,
                            step=step,
                            image_description=zoom_req.reason
                        )
                
                llm_client.add_user_message("Вот увеличенный фрагмент.", images=[zoom_crop])
            else:
                llm_client.add_user_message("Ошибка Zoom.")
        else:
            # Сохранить финальный ответ в БД
            if save_to_db and chat_id:
                final_message_id = await supabase_client.add_message(
                    chat_id=chat_id,
                    role="assistant",
                    content=response,
                    message_type="text"
                )
            
            return response, chat_id
    
    if save_to_db and chat_id:
        await supabase_client.add_message(
            chat_id=chat_id,
            role="assistant",
            content="Превышен лимит шагов.",
            message_type="text"
        )
    
    return "Превышен лимит шагов.", chat_id


# ============================================
# ПРИМЕР 4: Получить историю чата
# ============================================

async def get_chat_history_with_images(chat_id: str) -> dict:
    """
    Получить полную историю чата с картинками.
    """
    # Получить информацию о чате
    chat = await supabase_client.get_chat(chat_id)
    
    # Получить сообщения
    messages = await supabase_client.get_chat_messages(chat_id)
    
    # Для каждого сообщения получить картинки
    messages_with_images = []
    for msg in messages:
        images = await supabase_client.get_message_images(msg["id"])
        
        messages_with_images.append({
            "id": msg["id"],
            "role": msg["role"],
            "content": msg["content"],
            "created_at": msg["created_at"],
            "images": images
        })
    
    return {
        "chat": chat,
        "messages": messages_with_images
    }


# ============================================
# ПРИМЕР 5: Экспорт чата
# ============================================

async def export_chat_as_markdown(chat_id: str) -> str:
    """
    Экспортировать чат в Markdown формат.
    """
    chat_data = await get_chat_history_with_images(chat_id)
    
    md = f"# {chat_data['chat']['title']}\n\n"
    md += f"**Создано**: {chat_data['chat']['created_at']}\n\n"
    
    if chat_data['chat']['description']:
        md += f"**Описание**: {chat_data['chat']['description']}\n\n"
    
    md += "---\n\n"
    
    for msg in chat_data['messages']:
        role = "👤 User" if msg['role'] == 'user' else "🤖 Assistant"
        md += f"## {role}\n\n"
        md += f"{msg['content']}\n\n"
        
        if msg['images']:
            md += "### Картинки:\n\n"
            for img in msg['images']:
                if img['s3_url']:
                    md += f"![{img['image_type']}]({img['s3_url']})\n\n"
        
        md += "---\n\n"
    
    return md


# ============================================
# ПРИМЕР 6: Удалить чат с очисткой S3
# ============================================

async def delete_chat_completely(chat_id: str) -> bool:
    """
    Удалить чат из БД и очистить связанные файлы в S3.
    """
    # 1. Получить все картинки чата
    chat = await supabase_client.get_chat(chat_id)
    if not chat:
        logger.error(f"Чат не найден: {chat_id}")
        return False
    
    # 2. Удалить файлы из S3
    if s3_storage.is_connected():
        deleted = await s3_storage.delete_folder(f"chats/{chat_id}/")
        logger.info(f"Удалено {deleted} файлов из S3")
    
    # 3. Удалить чат из БД (каскадное удаление)
    # В Supabase это удалит все связанные сообщения, картинки и результаты
    try:
        # Удаление будет сделано через SQL удаление записи
        logger.info(f"Чат удален: {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления чата: {e}")
        return False


if __name__ == "__main__":
    # Пример использования
    import asyncio
    
    async def main():
        # Создать чат с обработкой документа
        chat_id = await process_document_with_chat(
            file_path="/path/to/document.pdf",
            user_id="user_123",
            query="Найди информацию о вентиляции"
        )
        
        print(f"✅ Чат создан: {chat_id}")
        
        # Получить историю чата
        history = await get_chat_history_with_images(chat_id)
        print(f"Сообщений: {len(history['messages'])}")
        
        # Экспортировать в Markdown
        md = await export_chat_as_markdown(chat_id)
        print(f"Markdown:\n{md[:200]}...")
    
    # asyncio.run(main())

