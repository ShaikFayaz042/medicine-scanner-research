"""Local PDF structure profiling for the PDF ingestion system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf


def _page_type(text: str, has_images: bool) -> str:
    if text:
        return "text"
    if has_images:
        return "image"
    return "empty"


def _primary_type(text_pages: int, image_pages: int, empty_pages: int) -> str:
    if text_pages and image_pages:
        return "mixed"
    if text_pages:
        return "text"
    if image_pages:
        return "scanned"
    if empty_pages:
        return "empty"
    return "unknown"


def profile_pdf(pdf_path: Path, source_name: str = "") -> dict[str, Any]:
    """Return the structure metrics consumed by the profiler CSV writer."""
    del source_name
    document = pymupdf.open(pdf_path)
    page_profile: list[dict[str, Any]] = []
    text_pages = 0
    image_pages = 0
    empty_pages = 0
    entity_total = 0

    try:
        for page_number, page in enumerate(document, start=1):
            text = (page.get_text("text") or "").strip()
            has_images = bool(page.get_images(full=True))
            page_type = _page_type(text, has_images)
            text_pages += page_type == "text"
            image_pages += page_type == "image"
            empty_pages += page_type == "empty"
            entity_total += len(text.split())
            page_profile.append({
                "page": page_number,
                "type": page_type,
                "has_table": False,
            })

        with pdfplumber.open(pdf_path) as plumber_document:
            for page_number, plumber_page in enumerate(plumber_document.pages, start=1):
                if page_number <= len(page_profile):
                    page_profile[page_number - 1]["has_table"] = bool(
                        plumber_page.extract_tables()
                    )
    finally:
        document.close()

    return {
        "total_pages": len(page_profile),
        "page_profile": page_profile,
        "structure": {
            "primary_type": _primary_type(text_pages, image_pages, empty_pages),
            "text_pages": text_pages,
            "image_pages": image_pages,
            "empty_pages": empty_pages,
            "has_tables": any(page["has_table"] for page in page_profile),
            "entity_total": entity_total,
        },
    }