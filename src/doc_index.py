"""
Индексирование result.md:
- извлечение JSON-блоков с изображениями (doc_metadata.page + image.uri + описания)
- выделение "чистого" текста (без JSON)
- простой retrieval по ключевым словам для длинных диалогов
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


@dataclass
class ImageCatalogEntry:
    """Метаданные об одном изображении/кропе из result.md."""

    image_id: str
    page: Optional[int]
    uri: str
    content_summary: str = ""
    detailed_description: str = ""
    clean_ocr_text: str = ""
    key_entities: List[str] = field(default_factory=list)
    sheet_name: str = ""  # Наименование листа из штампа чертежа
    local_path: str = ""  # Локальный путь к файлу (crops/ID.pdf)

    def searchable_text(self) -> str:
        parts = [
            self.content_summary,
            self.detailed_description,
            self.clean_ocr_text,
            " ".join(self.key_entities or []),
            f"page {self.page}" if self.page is not None else "",
            self.image_id,
        ]
        return "\n".join([p for p in parts if p])


@dataclass
class DocumentIndex:
    """
    Лёгкий индекс документа для работы в длинном диалоге.
    """

    # image_id -> ImageCatalogEntry
    images: Dict[str, ImageCatalogEntry] = field(default_factory=dict)
    # список (chunk_id, text)
    text_chunks: List[Tuple[str, str]] = field(default_factory=list)


_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _safe_int(value) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _extract_image_id_from_uri(uri: str) -> str:
    """
    Делаем короткий и стабильный ID, чтобы LLM могла ссылаться без длинных URL.
    По умолчанию берём stem файла из URL: .../image_<uuid>.pdf -> image_<uuid>
    """
    try:
        path = urlparse(uri).path
        stem = Path(path).stem
        return stem or uri
    except Exception:
        return uri


def extract_image_catalog(markdown_text: str) -> Dict[str, ImageCatalogEntry]:
    """
    Извлекает все JSON-блоки изображений из result.md.
    """
    images: Dict[str, ImageCatalogEntry] = {}

    for match in _JSON_FENCE_RE.finditer(markdown_text):
        raw = match.group(1).strip()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            # Иногда OCR-пайплайн может породить мусор — пропускаем.
            continue

        if not isinstance(data, dict):
            continue

        uri = (data.get("image") or {}).get("uri")
        if not isinstance(uri, str) or not uri:
            continue

        meta = data.get("doc_metadata") or {}
        page = _safe_int(meta.get("page"))

        analysis_outer = data.get("analysis") or {}
        analysis = analysis_outer.get("analysis") if isinstance(analysis_outer, dict) else {}
        if not isinstance(analysis, dict):
            analysis = {}

        image_id = _extract_image_id_from_uri(uri)
        entry = ImageCatalogEntry(
            image_id=image_id,
            page=page,
            uri=uri,
            content_summary=str(analysis.get("content_summary") or ""),
            detailed_description=str(analysis.get("detailed_description") or ""),
            clean_ocr_text=str(analysis.get("clean_ocr_text") or ""),
            key_entities=list(analysis.get("key_entities") or []),
        )
        images[image_id] = entry

    return images


def strip_json_blocks(markdown_text: str) -> str:
    """
    Убирает JSON-блоки изображений из текста, чтобы они не раздували контекст.
    """
    return _JSON_FENCE_RE.sub("", markdown_text)


_TOKEN_RE = re.compile(r"[0-9a-zа-яё]{3,}", re.IGNORECASE)


def tokenize_query(query: str) -> List[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(query or "")]
    # лёгкая дедупликация с сохранением порядка
    out: List[str] = []
    seen = set()
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _score_text(text: str, tokens: List[str]) -> int:
    if not text or not tokens:
        return 0
    t = text.lower()
    score = 0
    for tok in tokens:
        if tok in t:
            # простая эвристика: 3 балла за наличие + 1 за частоту (ограничим)
            score += 3
            score += min(10, t.count(tok))
    return score


def chunk_text(text: str, max_chars: int = 1800) -> List[Tuple[str, str]]:
    """
    Простая нарезка текста на чанки по пустым строкам с ограничением размера.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: List[Tuple[str, str]] = []

    buf: List[str] = []
    cur_len = 0
    idx = 0

    def flush():
        nonlocal idx, buf, cur_len
        if not buf:
            return
        idx += 1
        chunk = "\n\n".join(buf).strip()
        chunks.append((f"t{idx:03d}", chunk))
        buf = []
        cur_len = 0

    for p in paragraphs:
        if cur_len + len(p) + 2 > max_chars and buf:
            flush()
        buf.append(p)
        cur_len += len(p) + 2

    flush()
    return chunks


def build_index(markdown_text: str) -> DocumentIndex:
    images = extract_image_catalog(markdown_text)
    clean_text = strip_json_blocks(markdown_text)
    chunks = chunk_text(clean_text)
    return DocumentIndex(images=images, text_chunks=chunks)


def retrieve_text_chunks(
    index: DocumentIndex,
    query: str,
    top_k: int = 8,
) -> List[Tuple[str, str]]:
    tokens = tokenize_query(query)
    scored: List[Tuple[int, Tuple[str, str]]] = []
    for chunk_id, text in index.text_chunks:
        s = _score_text(text, tokens)
        if s > 0:
            scored.append((s, (chunk_id, text)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[: max(1, int(top_k))]]


def retrieve_image_candidates(
    index: DocumentIndex,
    query: str,
    top_k: int = 20,
) -> List[ImageCatalogEntry]:
    tokens = tokenize_query(query)
    scored: List[Tuple[int, ImageCatalogEntry]] = []
    for entry in index.images.values():
        s = _score_text(entry.searchable_text(), tokens)
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[: max(1, int(top_k))]]


