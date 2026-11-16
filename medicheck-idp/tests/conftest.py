"""Shared fixtures: real rule files, a context builder and a fake LLM provider."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from idp.models.llm import LLMError, LLMRequest, LLMResponse
from idp.schemas.classification_context import (
    ClassificationContext,
    ParagraphContext,
    SourceReference,
    TableContext,
)
from idp.stages.classifier.service import Classifier
from idp.stages.classifier.taxonomy import load_taxonomy


@pytest.fixture(scope="session")
def taxonomy():
    return load_taxonomy()


def build_context(
    paragraphs: Optional[List[Any]] = None,
    tables: Optional[List[Dict[str, Any]]] = None,
    title: Optional[str] = "Test document",
    pages: int = 2,
) -> ClassificationContext:
    """Build the same page-level context shape emitted by the context builder."""
    paragraph_contexts = []
    section_path: list[tuple[int, str]] = []
    for item in paragraphs or []:
        paragraph = {"type": "paragraph", "text": item} if isinstance(item, str) else dict(item)
        page = paragraph.pop("page", 1)
        block_type = paragraph.get("type", "paragraph")
        text = str(paragraph.get("text", "")).strip()
        if block_type == "heading":
            level = paragraph.get("level") or 1
            section_path = [(depth, heading) for depth, heading in section_path if depth < level]
            section_path.append((level, text))
            continue
        if block_type in ("header", "footer", "table_ref") or not text:
            continue
        paragraph_index = len(paragraph_contexts) + 1
        paragraph_contexts.append(ParagraphContext(
            id=f"P{paragraph_index:04d}",
            pages=[page],
            section=section_path[-1][1] if section_path else None,
            section_path=[heading for _, heading in section_path],
            content=text,
            source_refs=[SourceReference(
                page=page,
                artifact=f"02_extraction/markdown/p{page:03d}.md",
                method="pymupdf4llm",
            )],
        ))

    table_contexts = []
    for table_index, table_data in enumerate(tables or [], start=1):
        headers = []
        for header_row in table_data.get("header_rows", []):
            for column, cell in enumerate(header_row):
                if len(headers) <= column:
                    headers.append([])
                if cell and cell not in headers[column]:
                    headers[column].append(cell)
        merged_headers = [" ".join(parts) for parts in headers]
        rows = table_data.get("rows", [])
        pages_for_table = table_data.get("pages", [1])
        column_count = max([len(merged_headers), *(len(row) for row in rows), 1])
        sample_rows = [
            [*row, *("" for _ in range(column_count - len(row)))]
            for row in rows[:3]
        ]
        for page in pages_for_table:
            table_contexts.append(TableContext(
                id=f"T{len(table_contexts) + 1:04d}",
                pages=[page],
                headers=merged_headers,
                sample_rows=sample_rows,
                row_count=len(rows),
                column_count=column_count,
                source_refs=[SourceReference(
                    page=page,
                    artifact=f"02_extraction/batches/b{table_index - 1:04d}",
                    item_id=f"table-{table_index}",
                    method="native_table",
                )],
            ))

    source_metadata = {"file_name": "fixture.pdf"}
    if title is not None:
        source_metadata["title"] = title
    return ClassificationContext(
        document_id="test/doc.pdf",
        document_sha256="0" * 64,
        source_metadata=source_metadata,
        total_pages=max(pages, *(page for paragraph in paragraph_contexts for page in paragraph.pages), 1),
        builder_version="1.0.0",
        extraction_fingerprint="fixture-fingerprint",
        quality={
            "has_classifiable_content": bool(paragraph_contexts or table_contexts),
            "warnings": [],
            "failed_pages": [],
        },
        paragraphs=paragraph_contexts,
        tables=table_contexts,
    )


class FakeProvider:
    """Returns queued replies (dicts) or raises queued LLMErrors; records every request."""

    name = "fake"

    def __init__(self, replies: Optional[List[Any]] = None, model: str = "fake-model") -> None:
        self.model = model
        self.replies = list(replies or [])
        self.requests: List[LLMRequest] = []

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        reply = self.replies.pop(0) if self.replies else {"is_record": True, "labels": []}
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(data=reply, raw_text=str(reply), provider=self.name, model=self.model, schema_enforced=True)


@pytest.fixture
def classifier(taxonomy):
    return Classifier(taxonomy, provider=None, clock=lambda: "2026-10-29T00:00:00Z")


@pytest.fixture
def make_classifier(taxonomy):
    def factory(replies=None, cache=None):
        provider = FakeProvider(replies)
        return Classifier(taxonomy, provider=provider, cache=cache, clock=lambda: "2026-10-29T00:00:00Z"), provider
    return factory


__all__ = ["build_context", "FakeProvider", "LLMError"]
