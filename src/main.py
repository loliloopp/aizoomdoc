"""
Главный модуль (Агент).
"""

import argparse
import logging
import sys
from pathlib import Path

from .config import config
from .llm_client import LLMClient
from .search_engine import SearchEngine
from .image_processor import ImageProcessor
from .models import ZoomRequest

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def run_agent_loop(data_root: Path, user_query: str, model: str = None) -> str:
    search_engine = SearchEngine(data_root)
    image_processor = ImageProcessor(data_root)
    llm_client = LLMClient(model=model, data_root=data_root)
    
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
        
    llm_client.add_user_message(context_text, images=external_images)
    
    # Loop
    step = 0
    max_steps = 5
    
    while step < max_steps:
        step += 1
        logger.info(f"--- Шаг {step} ---")
        
        response = llm_client.get_response()
        zoom_req = llm_client.parse_zoom_request(response)
        
        if zoom_req:
            logger.info(f"Zoom Request: {zoom_req.reason} (ImageID: {zoom_req.image_id})")
            
            zoom_crop = image_processor.process_zoom_request(
                zoom_req,
                output_path=data_root / "viewports" / f"zoom_step_{step}.png"
            )
            
            if zoom_crop:
                llm_client.add_user_message("Вот увеличенный фрагмент.", images=[zoom_crop])
            else:
                llm_client.add_user_message("Ошибка Zoom: невозможно выполнить для этого ID или координат.")
        else:
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
