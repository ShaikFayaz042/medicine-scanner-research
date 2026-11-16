"""Extraction output contract for lightweight context and detailed reconstruction.

One schema for every engine. PyMuPDF and RapidOCR both emit `Item`s; only `source`,
`confidence` and `segments` differ. Page numbers are 1-based. All bboxes are
NORMALIZED (0..1) in the page's VISIBLE space (after /Rotate), origin top-left:
(x0, y0, x1, y1). Multiply by `width`/`height` (points) to get page coordinates.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from idp.schemas.profile import Engine, PageType

BBox = tuple[float, float, float, float]
PageStatus = Literal["success", "skipped", "failed"]
ItemType = Literal["text_line", "table", "image"]
MarkdownSource = Literal["pymupdf4llm", "ocr_lines", "mixed", "none"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Model):
    engine: Literal["pymupdf", "rapidocr"]
    method: Literal["native_text", "native_table", "ocr", "region_crop"]


class Segment(_Model):
    """One style run of a native line (a PyMuPDF span). OCR lines have none."""
    text: str
    size: float = Field(gt=0)
    font: str
    bold: bool = False
    italic: bool = False


class Table(_Model):
    """Raw find_tables() result. Not fully interpreted until detailed reconstruction."""
    rows: list[list[str | None]]
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    header_names: list[str] = Field(default_factory=list)
    header_external: bool = False
    columns: list[tuple[float, float]] = Field(default_factory=list)
    continuation_of: str | None = None
    continuation_confidence: float | None = Field(default=None, ge=0, le=1)
    n_data_rows: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_dimensions(self) -> "Table":
        if len(self.rows) != self.n_rows:
            raise ValueError("table n_rows does not match rows")
        if any(len(row) != self.n_cols for row in self.rows):
            raise ValueError("each table row must have n_cols cells")
        if self.columns:
            if len(self.columns) != self.n_cols:
                raise ValueError("table columns must match n_cols")
            if any(not 0 <= x0 < x1 <= 1 for x0, x1 in self.columns):
                raise ValueError("table column bounds must be normalized and ordered")
        return self


class Item(_Model):
    item_id: str
    type: ItemType
    bbox: BBox
    source: Source
    role: Literal["body", "page_number", "header", "footer"] = "body"
    text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    block: int | None = Field(default=None, ge=0)
    segments: list[Segment] = Field(default_factory=list)
    table: Table | None = None
    parent: str | None = None
    image_ref: str | None = None

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, bbox: BBox) -> BBox:
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in bbox):
            raise ValueError("item bbox coordinates must be finite and normalized to 0..1")
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError("item bbox must have positive width and height")
        return bbox

    @model_validator(mode="after")
    def _check_shape(self) -> "Item":
        methods = {
            "text_line": {"native_text", "ocr"},
            "table": {"native_table"},
            "image": {"region_crop"},
        }
        engines = {
            "native_text": "pymupdf",
            "native_table": "pymupdf",
            "ocr": "rapidocr",
            "region_crop": "pymupdf",
        }
        if self.source.method not in methods[self.type]:
            raise ValueError(f"{self.type} item cannot use source method {self.source.method}")
        if self.source.engine != engines[self.source.method]:
            raise ValueError(f"source method {self.source.method} requires engine {engines[self.source.method]}")
        if self.type == "text_line" and not self.text:
            raise ValueError("text_line items require non-empty text")
        if self.type == "table" and self.table is None:
            raise ValueError("table items require table data")
        if self.type != "table" and self.table is not None:
            raise ValueError("only table items may carry table data")
        if self.type == "image" and not self.image_ref:
            raise ValueError("image items require image_ref")
        if self.type != "image" and self.image_ref is not None:
            raise ValueError("only image items may carry image_ref")
        if self.type != "text_line" and (self.text is not None or self.segments or self.block is not None):
            raise ValueError("only text_line items may carry text, segments, or block")
        return self


class PageExtraction(_Model):
    doc_id: str
    page_number: int = Field(ge=1)
    status: PageStatus
    page_mode: PageType
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    rotation: int = Field(default=0, ge=0, le=270)
    items: list[Item] = Field(default_factory=list)
    tables_checked: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    markdown_ref: str | None = None
    markdown_source: MarkdownSource = "none"
    markdown_error: str | None = None

    @model_validator(mode="after")
    def _check_status(self) -> "PageExtraction":
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be a multiple of 90 degrees")
        if self.status == "failed" and not self.error:
            raise ValueError("failed pages require an error")
        if self.status != "failed" and (self.error or self.width <= 0 or self.height <= 0):
            raise ValueError("successful and skipped pages require dimensions and no error")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("item_id values must be unique within the page")
        if self.status == "skipped" and self.items:
            raise ValueError("skipped pages cannot contain extracted items")
        return self


class TableGroup(_Model):
    group_id: str
    member_table_ids: list[str] = Field(min_length=1)
    header_source: str | None = None
    pages: list[int] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ExtractionBatch(_Model):
    doc_id: str
    batch_index: int
    engine: Engine
    extractor_version: str
    config_hash: str
    profile_key: str
    pages: list[PageExtraction]
    table_groups: list[TableGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_pages(self) -> "ExtractionBatch":
        if any(page.doc_id != self.doc_id for page in self.pages):
            raise ValueError("all batch pages must belong to the batch document")
        page_numbers = [page.page_number for page in self.pages]
        if len(page_numbers) != len(set(page_numbers)):
            raise ValueError("page_number values must be unique within a batch")
        item_ids = {item.item_id for page in self.pages for item in page.items}
        for group in self.table_groups:
            missing_ids = set(group.member_table_ids) - item_ids
            if missing_ids:
                raise ValueError(
                    f"table group {group.group_id} references unknown item_id values: "
                    f"{sorted(missing_ids)}"
                )
            if group.header_source is not None and group.header_source not in group.member_table_ids:
                raise ValueError(
                    f"table group {group.group_id} header_source must be a member_table_id"
                )
        return self


class BatchRef(_Model):
    index: int
    engine: Engine
    pages: list[int] = Field(min_length=1)
    artifact: str


class ExtractionIndex(_Model):
    doc_id: str
    extractor_version: str
    config_hash: str
    profile_key: str
    total_pages: int = Field(ge=0)
    batches: list[BatchRef] = Field(default_factory=list)
    failed_pages: list[int] = Field(default_factory=list)
    markdown_failed_pages: list[int] = Field(default_factory=list)
    complete: bool = True

    @model_validator(mode="after")
    def _check_coverage(self) -> "ExtractionIndex":
        pages = [page for batch in self.batches for page in batch.pages]
        if len(pages) != len(set(pages)):
            raise ValueError("each page may appear in only one extraction batch")
        if sorted(pages) != list(range(1, self.total_pages + 1)):
            raise ValueError("extraction batches must cover every document page exactly once")
        if len(self.failed_pages) != len(set(self.failed_pages)):
            raise ValueError("failed_pages must not contain duplicates")
        if any(page < 1 or page > self.total_pages for page in self.failed_pages):
            raise ValueError("failed_pages contains a page outside the document")
        if len(self.markdown_failed_pages) != len(set(self.markdown_failed_pages)):
            raise ValueError("markdown_failed_pages must not contain duplicates")
        if any(page < 1 or page > self.total_pages for page in self.markdown_failed_pages):
            raise ValueError("markdown_failed_pages contains a page outside the document")
        if self.failed_pages or self.markdown_failed_pages:
            self.complete = False
        return self