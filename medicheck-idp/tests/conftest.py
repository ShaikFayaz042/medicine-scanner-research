"""Shared fixtures: the real rule files, a structured-document builder and a fake LLM provider."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from idp.models.llm import LLMError, LLMRequest, LLMResponse
from idp.schemas.structured import StructuredDocument
from idp.stages.classifier.service import Classifier
from idp.stages.classifier.taxonomy import load_taxonomy


@pytest.fixture(scope="session")
def taxonomy():
    return load_taxonomy()


def build_document(
    paragraphs: Optional[List[Any]] = None,
    tables: Optional[List[Dict[str, Any]]] = None,
    title: Optional[str] = "Test document",
    pages: int = 2,
) -> StructuredDocument:
    """paragraphs: strings (paragraph blocks), or dicts with block fields (type, text, level, language, page)."""
    page_blocks: Dict[int, list] = {number: [] for number in range(1, pages + 1)}
    for index, item in enumerate(paragraphs or [], start=1):
        block = {"type": "paragraph", "text": item} if isinstance(item, str) else dict(item)
        page = block.pop("page", 1)
        block.setdefault("block_id", f"b{index}")
        page_blocks[page].append(block)
    for table in tables or []:
        page_blocks[table.get("pages", [1])[0]].append({"block_id": f"ref-{table['table_id']}", "type": "table_ref", "table_id": table["table_id"]})
    return StructuredDocument.model_validate({
        "document": {"document_id": "test/doc.pdf", "sha256": "0" * 64, "page_count": pages, "title": title},
        "pages": [{"page_number": n, "profile": {"kind": "digital"}, "blocks": blocks} for n, blocks in page_blocks.items()],
        "tables": [
            {
                **{key: value for key, value in table.items() if key != "rows"},
                "pages": table.get("pages", [1]),
                "rows": [{"cells": row, "page": table.get("pages", [1])[0]} for row in table.get("rows", [])],
            }
            for table in (tables or [])
        ],
    })


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


__all__ = ["build_document", "FakeProvider", "LLMError"]
