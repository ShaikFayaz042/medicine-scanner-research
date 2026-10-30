"""Stage 4 output contract: one structured document (JSON) per PDF.

Written by the structurer, read by the classifier. A document holds:

- `pages[].blocks`: the page content in reading order (headings, paragraphs, list items, captions,
  running headers/footers) with a `table_ref` block marking where each table sits in the flow;
- `tables`: LOGICAL tables. A table that continues over several pages is ONE entry whose `segments`
  record where each part sits. Header rows are delivered separately from body rows.

Every block and row keeps its page, bounding box, origin (text layer or OCR) and confidence so later
stages can verify extracted values against the source page.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field, model_validator

from idp.schemas.common import BBox, ContentOrigin, StrictModel

SCHEMA_VERSION = "1.0"

BlockType = Literal["heading", "paragraph", "list_item", "caption", "header", "footer", "table_ref", "other"]


class ExtractionInfo(StrictModel):
    tools: dict[str, str] = Field(default_factory=dict, description="Tool name -> version used to extract")
    created_at: Optional[str] = Field(default=None, description="ISO-8601 timestamp")


class DocumentInfo(StrictModel):
    document_id: str = Field(description="Stable id, e.g. '<source folder>/<pdf file name>'")
    sha256: str
    page_count: int = Field(ge=1)
    s3_key: Optional[str] = None
    title: Optional[str] = Field(default=None, description="Title from the scraper listing; treated as document content")
    source: Optional[str] = Field(default=None, description="Source listing, e.g. cdsco_alerts")
    release_date: Optional[str] = None
    extraction: ExtractionInfo = Field(default_factory=ExtractionInfo)


class PageProfile(StrictModel):
    kind: Literal["digital", "scanned", "hybrid"]
    ocr_used: bool = False
    languages: List[str] = Field(default_factory=list, description="ISO 639-1 codes detected on the page")
    image_cover: Optional[float] = Field(default=None, ge=0, le=1)


class Block(StrictModel):
    block_id: str = Field(description="Unique within the document, e.g. 'p3-b12'")
    type: BlockType
    text: str = ""
    level: Optional[int] = Field(default=None, ge=1, le=6, description="Heading level, headings only")
    table_id: Optional[str] = Field(default=None, description="Referenced table, table_ref blocks only")
    bbox: Optional[BBox] = None
    origin: ContentOrigin = "text_layer"
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    language: Optional[str] = None

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "Block":
        if self.type == "table_ref" and not self.table_id:
            raise ValueError(f"block {self.block_id}: table_ref blocks need table_id")
        if self.type != "table_ref" and self.table_id:
            raise ValueError(f"block {self.block_id}: only table_ref blocks carry table_id")
        if self.level is not None and self.type != "heading":
            raise ValueError(f"block {self.block_id}: only headings carry level")
        return self


class Page(StrictModel):
    page_number: int = Field(ge=1)
    width: Optional[float] = None
    height: Optional[float] = None
    profile: PageProfile
    blocks: List[Block] = Field(default_factory=list)


class TableSegment(StrictModel):
    page: int = Field(ge=1)
    bbox: Optional[BBox] = None


class TableRow(StrictModel):
    cells: List[str]
    page: int = Field(ge=1)
    origin: ContentOrigin = "text_layer"


class Table(StrictModel):
    table_id: str
    pages: List[int] = Field(min_length=1)
    segments: List[TableSegment] = Field(default_factory=list)
    caption: Optional[str] = None
    heading_path: List[str] = Field(default_factory=list, description="Headings above the table, outermost first")
    header_rows: List[List[str]] = Field(default_factory=list, description="Header rows only, top to bottom")
    rows: List[TableRow] = Field(default_factory=list, description="Body rows across all pages, in order")
    method: Optional[str] = Field(default=None, description="How the table was extracted, e.g. pdfplumber_lines, ocr_grid")
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class StructuredDocument(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    document: DocumentInfo
    pages: List[Page]
    tables: List[Table] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> "StructuredDocument":
        page_numbers = [page.page_number for page in self.pages]
        if len(set(page_numbers)) != len(page_numbers):
            raise ValueError("page_number values must be unique")
        if any(number > self.document.page_count for number in page_numbers):
            raise ValueError("a page_number exceeds document.page_count")
        block_ids = [block.block_id for page in self.pages for block in page.blocks]
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("block_id values must be unique within the document")
        table_ids = [table.table_id for table in self.tables]
        if len(set(table_ids)) != len(table_ids):
            raise ValueError("table_id values must be unique")
        referenced = {block.table_id for page in self.pages for block in page.blocks if block.type == "table_ref"}
        unknown = referenced - set(table_ids)
        if unknown:
            raise ValueError(f"table_ref blocks point at unknown tables: {sorted(unknown)}")
        for table in self.tables:
            if any(number not in page_numbers for number in table.pages):
                raise ValueError(f"table {table.table_id} spans a page that is not in pages[]")
        return self
