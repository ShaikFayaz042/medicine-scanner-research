"""Profiler output contract: the ONLY thing the extractor reads.

Page numbers are 1-based everywhere. `batches` is what the extractor loops over
(and what a Step Functions Map state will fan out over later).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PageType = Literal["digital", "scanned", "hybrid", "blank"]
Engine = Literal["pymupdf", "rapidocr", "hybrid", "skip"]
# (x0, y0, x1, y1) in the page's VISIBLE space, i.e. ready for
# page.get_pixmap(clip=pymupdf.Rect(*region)), also on rotated pages.
Region = tuple[float, float, float, float]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageProfile(_Model):
    n: int = Field(ge=1)                    # 1-based page number
    type: PageType
    engine: Engine                          # the routing decision
    words: int                              # native words found
    img: float                              # fraction of page covered by images
    garbled: float                          # share of broken glyphs in native text
    table_hint: bool                        # ruled lines found; a hint, not a detection
    rotation: int = 0
    min_dpi: float | None = None            # worst big image on OCR-routed pages
    ocr_regions: list[Region] = []          # hybrid only: run OCR just here
    skipped_regions: list[Region] = []      # decorative/logo/header/footer images intentionally skipped on OCR flow
    flags: list[str] = []                   # ocr_layer, low_dpi, rotated, borderline, decor_skipped, profile_error


class Batch(_Model):
    engine: Engine
    pages: list[int]


class DocProfile(_Model):
    doc_id: str                             # sha256 hex of the file bytes
    file_name: str
    status: Literal["ok", "failed"]
    reason: str | None = None               # set when status == "failed"
    profiler_version: str
    config_hash: str
    total_pages: int = 0
    doc_type: PageType | None = None        # report only; routing is always per page
    page_type_counts: dict[str, int] = {}
    batches: list[Batch] = []
    pages: list[PageProfile] = []