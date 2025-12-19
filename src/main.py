"""
Главный модуль (Агент).
"""

import argparse
import logging
import sys
import asyncio
from pathlib import Path

from .config import config
from .llm_client import LLMClient
from .search_engine import SearchEngine
from .image_processor import ImageProcessor
from .models import ZoomRequest
from .supabase_client import supabase_client
from .s3_storage import s3_storage

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def save_to_db(chat_id: str, role: str, content: str, images: list = None):
    """Хелпер для сохранения в БД из CLI."""
    if not config.USE_DATABASE or not chat_id:
        return None
    
    msg_id = await supabase_client.add_message(chat_id, role, content)
    if msg_id and images:
        for img in images:
            if img.image_path and Path(img.image_path).exists():
                img_type = "zoom_crop" if getattr(img, "is_zoom_request", False) else "viewport"
                filename = Path(img.image_path).name
                s3_key = s3_storage.generate_s3_path(chat_id, img_type, filename)
                
                s3_url = await s3_storage.upload_file(img.image_path, s3_key)
                if s3_url:
                    await supabase_client.add_image_to_message(
                        chat_id=chat_id,
                        message_id=msg_id,
                        image_name=filename,
                        s3_path=s3_key,
                        s3_url=s3_url,
                        image_type=img_type,
                        description=img.description
                    )
                    
                    # ПРОВЕРКА: Загружаем также оригинал (full) если это превью
                    if "_preview.png" in img.image_path:
                        full_path = img.image_path.replace("_preview.png", "_full.png")
                        if Path(full_path).exists():
                            s3_full_key = s3_key.replace("_preview.png", "_full.png")
                            await s3_storage.upload_file(full_path, s3_full_key)
                            await supabase_client.register_file(
                                user_id="cli_user",
                                source_type="llm_generated",
                                filename=Path(full_path).name,
                                storage_path=s3_full_key
                            )
    return msg_id

def run_agent_loop(data_root: Path, user_query: str, model: str = None) -> str:
    search_engine = SearchEngine(data_root)
    image_processor = ImageProcessor(data_root)
    llm_client = LLMClient(model=model, data_root=data_root)
    
    db_chat_id = None
    if config.USE_DATABASE:
        db_chat_id = asyncio.run(supabase_client.create_chat(
            title=user_query[:100],
            user_id="cli_user",
            description=user_query
        ))

    logger.info("1. Поиск в документах...")
    search_result = search_engine.find_ventilation_equipment(user_query)
    
    # Сбор внешних ссылок
    external_images = []
    
    logger.info("2. Загрузка и обработка PDF-кропов с S3...")
    processed_urls = set()
    
    for block in search_result.text_blocks:
        for link in block.external_links:
            if link.url.endswith(".pdf") and link.url not in processed_urls:
                processed_urls.add(link.url)
                logger.info(f"Processing: {link.url}")
                crop_info = image_processor.download_and_process_pdf(link.url)
                if crop_info:
                    external_images.append(crop_info)
    
    # Формируем контекст
    context_text = f"ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {user_query}\n\nНАЙДЕННЫЙ ТЕКСТ:\n"
    for block in search_result.text_blocks:
        context_text += f"---\n{block.text}\n"
        
    # Сохраняем первый запрос пользователя
    if db_chat_id:
        asyncio.run(save_to_db(db_chat_id, "user", user_query, images=external_images))

    llm_client.add_user_message(context_text, images=external_images)
    
    # Loop
    step = 0
    max_steps = 5
    
    while step < max_steps:
        step += 1
        logger.info(f"--- Шаг {step} ---")
        
        response = llm_client.get_response()
        zoom_reqs = llm_client.parse_zoom_request(response)
        
        if zoom_reqs:
            zoom_crops = []
            for i, zr in enumerate(zoom_reqs):
                logger.info(f"Zoom Request {i+1}: {zr.reason} (ImageID: {zr.image_id})")
                
                zoom_crop = image_processor.process_zoom_request(
                    zr,
                    output_path=data_root / "viewports" / f"zoom_step_{step}_{i}.png"
                )
                if zoom_crop:
                    zoom_crops.append(zoom_crop)

            # Сохраняем ответ ассистента с зум-запросом
            if db_chat_id:
                asyncio.run(save_to_db(db_chat_id, "assistant", response, images=zoom_crops))

            if zoom_crops:
                llm_client.add_user_message("Вот увеличенные фрагменты.", images=zoom_crops)
            else:
                llm_client.add_user_message("Ошибка Zoom: невозможно выполнить ни для одного из запросов.")
        else:
            # Финальный ответ
            if db_chat_id:
                asyncio.run(save_to_db(db_chat_id, "assistant", response))
            return response
            
    return "Превышен лимит шагов."

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", type=str)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--model", type=str)
    args = parser.parse_args()
    
    try:
        config.validate()
        print(run_agent_loop(args.data_root, args.query, args.model))
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main()
