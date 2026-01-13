"""
JSON схемы для строгих ответов модели (Gemini response_schema).

Используются для:
- Flash: планирование, запросы изображений/зумов, сбор контекста
- Pro: финальные ответы с подсчётами и цитатами
"""

# ===== Flash Extractor Response Schema =====
# Используется в режиме flash+pro для сбора контекста

FLASH_EXTRACTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["collecting", "ready"],
            "description": "Статус: collecting (нужно больше данных) или ready (контекст собран)"
        },
        "reasoning": {
            "type": "string",
            "description": "Краткое объяснение хода мыслей"
        },
        "tool_calls": {
            "type": "array",
            "description": "Запросы инструментов (изображения, зумы)",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": ["request_images", "zoom"],
                        "description": "Тип инструмента"
                    },
                    "image_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "ID изображений для request_images"
                    },
                    "image_id": {
                        "type": "string",
                        "description": "ID изображения для zoom"
                    },
                    "coords_norm": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "Нормализованные координаты [x1, y1, x2, y2] для zoom"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Причина запроса"
                    }
                },
                "required": ["tool"]
            }
        },
        "relevant_blocks": {
            "type": "array",
            "description": "Релевантные текстовые блоки (когда status=ready)",
            "items": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["block_id"]
            }
        },
        "relevant_images": {
            "type": "array",
            "description": "Релевантные изображения (когда status=ready)",
            "items": {"type": "string"}
        }
    },
    "required": ["status"]
}


# ===== Pro Answer Response Schema =====
# Используется для финальных ответов Pro модели

PRO_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_markdown": {
            "type": "string",
            "description": "Полный ответ на вопрос пользователя в формате Markdown"
        },
        "summary": {
            "type": "string",
            "description": "Краткое резюме ответа (1-2 предложения)"
        },
        "counts": {
            "type": "array",
            "description": "Подсчёты объектов (если применимо)",
            "items": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "description": "Тип объекта (например, 'пожарный шкаф')"
                    },
                    "count": {
                        "type": "integer",
                        "description": "Количество"
                    },
                    "locations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Где найдены (листы, зоны)"
                    }
                },
                "required": ["object_type", "count"]
            }
        },
        "citations": {
            "type": "array",
            "description": "Ссылки на источники",
            "items": {
                "type": "object",
                "properties": {
                    "image_id": {
                        "type": "string",
                        "description": "ID изображения-источника"
                    },
                    "coords_norm": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "Область на изображении [x1, y1, x2, y2]"
                    },
                    "note": {
                        "type": "string",
                        "description": "Комментарий к цитате"
                    }
                },
                "required": ["image_id"]
            }
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "Уверенность в ответе"
        }
    },
    "required": ["answer_markdown"]
}


# ===== Tool Call Schema (для обычного режима) =====
# Используется когда модель хочет запросить изображения или зум

TOOL_CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "enum": ["request_images", "zoom", "request_documents", "answer"],
            "description": "Тип действия"
        },
        "image_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ID изображений (для request_images)"
        },
        "image_id": {
            "type": "string",
            "description": "ID изображения (для zoom)"
        },
        "coords_norm": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 4,
            "maxItems": 4,
            "description": "Координаты zoom [x1, y1, x2, y2]"
        },
        "documents": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Названия документов (для request_documents)"
        },
        "answer_markdown": {
            "type": "string",
            "description": "Финальный ответ (для tool=answer)"
        },
        "reason": {
            "type": "string",
            "description": "Причина запроса"
        }
    },
    "required": ["tool"]
}


def get_flash_extractor_schema_for_sdk():
    """Возвращает схему в формате для Google GenAI SDK."""
    return FLASH_EXTRACTOR_SCHEMA


def get_pro_answer_schema_for_sdk():
    """Возвращает схему в формате для Google GenAI SDK."""
    return PRO_ANSWER_SCHEMA


def get_tool_call_schema_for_sdk():
    """Возвращает схему в формате для Google GenAI SDK."""
    return TOOL_CALL_SCHEMA

