"""Markdown generation helpers for the extractor's page-level artifacts."""
from __future__ import annotations

from importlib.metadata import version
import re
from threading import RLock
from typing import Any

VERSION = version("pymupdf4llm")
MODE = "legacy"
OPTIONS = {
    "write_images": False,
    "embed_images": False,
    "page_chunks": True,
}
extraction_lock = RLock()
_pymupdf4llm = None
_MARK = re.compile(r"</?mark>", re.IGNORECASE)
_BULLET = re.compile(r"[\u25a0-\u25ff\ue000-\uf8ff]")


def _library():
    global _pymupdf4llm
    if _pymupdf4llm is None:
        import pymupdf4llm

        pymupdf4llm.use_layout(MODE == "layout")
        _pymupdf4llm = pymupdf4llm
    return _pymupdf4llm


def to_markdown(*args, **kwargs):
    return _library().to_markdown(*args, **kwargs)


def _normalize_markdown(text: str) -> str:
    text = _MARK.sub("", text)
    text = _BULLET.sub("-", text)
    return text


def _chunks_by_page(chunks: Any, requested_pages: list[int]) -> dict[int, str]:
    if not isinstance(chunks, list) or len(chunks) != len(requested_pages):
        raise ValueError(
            f"Markdown returned {len(chunks) if isinstance(chunks, list) else 'invalid'} "
            f"chunks for {len(requested_pages)} requested pages"
        )
    expected = set(requested_pages)
    result: dict[int, str] = {}
    for chunk in chunks:
        metadata = chunk.get("metadata") if isinstance(chunk, dict) else None
        page_number = None
        if isinstance(metadata, dict):
            page_number = metadata.get("page_number", metadata.get("page"))
        if isinstance(page_number, bool) or not isinstance(page_number, int):
            raise ValueError("Markdown chunk is missing its integer metadata page number")
        if page_number not in expected or page_number in result:
            raise ValueError(f"Markdown returned an unexpected or duplicate page {page_number}")
        text = chunk.get("text")
        if not isinstance(text, str):
            raise ValueError(f"Markdown chunk for page {page_number} has no text")
        result[page_number] = _normalize_markdown(text)
    if set(result) != expected:
        raise ValueError("Markdown page metadata does not cover the requested pages")
    return result


def batch_markdown(doc, page_numbers: list[int]) -> dict[int, str]:
    """Render a batch and map every chunk by its 1-based metadata page number."""
    if not page_numbers:
        return {}
    with extraction_lock:
        _library()
        rotations = [page.rotation for page in doc]
        for page_number in page_numbers:
            page = doc[page_number - 1]
            if page.rotation:
                page.set_rotation(0)
        try:
            chunks = to_markdown(
                doc, pages=[number - 1 for number in page_numbers], **OPTIONS,
            )
        finally:
            for page, rotation in zip(doc, rotations):
                if page.rotation != rotation:
                    page.set_rotation(rotation)
    return _chunks_by_page(chunks, page_numbers)
