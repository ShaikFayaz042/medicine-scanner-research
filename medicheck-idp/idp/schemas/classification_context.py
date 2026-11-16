"""Lightweight classifier-only context; never the reconstruction source of truth."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from idp.schemas.common import BBox, StrictModel

SCHEMA_VERSION = "1.1"


def _validate_bbox(bbox: BBox | None) -> BBox | None:
    if bbox is not None and (
        not all(math.isfinite(value) for value in bbox)
        or bbox[0] >= bbox[2]
        or bbox[1] >= bbox[3]
    ):
        raise ValueError("bbox must contain finite coordinates and have positive area")
    return bbox


class SourceReference(StrictModel):
    page: int = Field(ge=1)
    artifact: str
    item_id: str | None = None
    method: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    bbox: BBox | None = None
    parent_item_id: str | None = None

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, bbox: BBox | None) -> BBox | None:
        return _validate_bbox(bbox)

    @model_validator(mode="after")
    def _check_line_range(self) -> "SourceReference":
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("start_line and end_line must be provided together")
        if self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class ParagraphContext(StrictModel):
    id: str
    pages: list[int] = Field(min_length=1)
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)
    bbox: BBox | None = None
    source_refs: list[SourceReference] = Field(min_length=1)
    is_heading: bool = False
    is_header_footer: bool = False
    date_candidates: list[str] = Field(default_factory=list)
    file_no_candidates: list[str] = Field(default_factory=list)
    parent_item_id: str | None = None

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages) or pages != sorted(set(pages)):
            raise ValueError("pages must be unique, ascending, 1-based page numbers")
        return pages

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, bbox: BBox | None) -> BBox | None:
        return _validate_bbox(bbox)

    @model_validator(mode="after")
    def _check_sources(self) -> "ParagraphContext":
        if not set(self.pages).issubset({reference.page for reference in self.source_refs}):
            raise ValueError("each paragraph page must have a source reference")
        return self


class TableContext(StrictModel):
    id: str
    pages: list[int] = Field(min_length=1)
    headers: list[str] = Field(default_factory=list)
    sample_rows: list[list[str]] = Field(default_factory=list, max_length=3)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=1)
    bbox: BBox | None = None
    source_refs: list[SourceReference] = Field(min_length=1)
    header_external: bool = False
    continuation_of: str | None = None

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages) or pages != sorted(set(pages)):
            raise ValueError("pages must be unique, ascending, 1-based page numbers")
        return pages

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, bbox: BBox | None) -> BBox | None:
        return _validate_bbox(bbox)

    @model_validator(mode="after")
    def _check_dimensions_and_sources(self) -> "TableContext":
        if any(len(row) != self.column_count for row in self.sample_rows):
            raise ValueError("each sample row must match column_count")
        if not set(self.pages).issubset({reference.page for reference in self.source_refs}):
            raise ValueError("each table page must have a source reference")
        return self


class DocumentProfile(StrictModel):
    document_type: Literal["digital", "scanned", "hybrid", "blank"]
    digital_pages: int = Field(ge=0)
    scanned_pages: int = Field(ge=0)
    hybrid_pages: int = Field(ge=0)
    blank_pages: int = Field(ge=0)


class DocumentAnchor(StrictModel):
    value: str
    paragraph_ids: list[str] = Field(min_length=1)
    evidence: str


class DocumentAnchors(StrictModel):
    date: DocumentAnchor | None = None
    file_no: DocumentAnchor | None = None
    authority: DocumentAnchor | None = None
    subject: DocumentAnchor | None = None
    product: DocumentAnchor | None = None


class ContextQuality(StrictModel):
    has_classifiable_content: bool
    warnings: list[str] = Field(default_factory=list)
    failed_pages: list[int] = Field(default_factory=list)

    @field_validator("failed_pages")
    @classmethod
    def _check_failed_pages(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages) or pages != sorted(set(pages)):
            raise ValueError("failed_pages must be unique, ascending, 1-based page numbers")
        return pages


class ClassificationContext(StrictModel):
    schema_version: Literal["1.1"] = SCHEMA_VERSION
    document_id: str
    document_sha256: str
    source_metadata: dict[str, str] = Field(default_factory=dict)
    total_pages: int = Field(ge=1)
    builder_version: str
    extraction_fingerprint: str
    document_profile: DocumentProfile | None = None
    quality: ContextQuality
    paragraphs: list[ParagraphContext] = Field(default_factory=list)
    tables: list[TableContext] = Field(default_factory=list)
    document_anchors: DocumentAnchors | None = None

    @model_validator(mode="after")
    def _check_quality(self) -> "ClassificationContext":
        has_content = bool(self.paragraphs or self.tables)
        if self.quality.has_classifiable_content != has_content:
            raise ValueError("quality.has_classifiable_content must reflect paragraphs and tables")
        if any(page > self.total_pages for page in self.quality.failed_pages):
            raise ValueError("quality.failed_pages contains a page outside the document")
        if self.document_profile is not None:
            page_count = sum((
                self.document_profile.digital_pages,
                self.document_profile.scanned_pages,
                self.document_profile.hybrid_pages,
                self.document_profile.blank_pages,
            ))
            if page_count != self.total_pages:
                raise ValueError("document_profile page counts must sum to total_pages")
        if any(
            page > self.total_pages
            for record in [*self.paragraphs, *self.tables]
            for page in record.pages
        ):
            raise ValueError("context record contains a page outside the document")
        if any(
            paragraph.is_header_footer
            and paragraph.section_path not in ([], ["<header_footer>"])
            for paragraph in self.paragraphs
        ):
            raise ValueError("header/footer paragraphs cannot resolve to a document section")
        tables_by_id = {table.id: table for table in self.tables}
        for table in self.tables:
            if table.continuation_of is None:
                continue
            header_table = tables_by_id.get(table.continuation_of)
            if header_table is None:
                raise ValueError(
                    f"table {table.id} continuation_of references an unknown table"
                )
            if not header_table.headers:
                raise ValueError(
                    f"table {table.id} continuation target must have non-empty headers"
                )
        return self


__all__ = [
    "ClassificationContext",
    "ContextQuality",
    "DocumentAnchor",
    "DocumentAnchors",
    "DocumentProfile",
    "ParagraphContext",
    "SourceReference",
    "TableContext",
]
