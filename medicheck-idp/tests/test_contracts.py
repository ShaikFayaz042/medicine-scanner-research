"""The context input and classifier output contracts reject malformed JSON."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from conftest import build_context
from idp.schemas.classified import ClassifiedDocument
from idp.schemas.classification_context import ClassificationContext


def _base() -> dict:
    return build_context(
        ["A paragraph."],
        tables=[{
            "header_rows": [["S.No", "Name"]],
            "rows": [["1", "X"]],
        }],
    ).model_dump(mode="json")


def test_valid_context_round_trips_through_json():
    data = _base()

    context = ClassificationContext.model_validate(json.loads(json.dumps(data)))

    assert context.tables[0].id == "T0001"
    assert context.paragraphs[0].content == "A paragraph."


def test_context_contract_supports_multi_page_records_and_page_scoped_sources():
    data = _base()
    data["paragraphs"][0]["pages"] = [1, 2]
    data["paragraphs"][0]["source_refs"].append({
        "page": 2,
        "artifact": "02_extraction/markdown/p002.md",
        "item_id": "P0001",
        "method": "pymupdf4llm",
    })
    data["tables"][0]["pages"] = [1, 2]
    data["tables"][0]["bbox"] = None
    data["tables"][0]["source_refs"].append({
        "page": 2,
        "artifact": "02_extraction/batches/b0001",
        "item_id": "table-continued",
        "method": "native_table",
        "bbox": [10, 20, 200, 300],
    })

    context = ClassificationContext.model_validate(data)

    assert context.paragraphs[0].pages == [1, 2]
    assert context.tables[0].pages == [1, 2]
    assert context.tables[0].source_refs[1].bbox == (10, 20, 200, 300)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["paragraphs"][0].update(content=""), "at least 1 character"),
        (lambda d: d["tables"][0].update(pages=[0]), "1-based page numbers"),
        (lambda d: d["tables"][0].update(sample_rows=[["a"], ["b"], ["c"], ["d"]]), "at most 3 items"),
        (lambda d: d["paragraphs"][0].update(unexpected="value"), "Extra inputs are not permitted"),
        (lambda d: d["tables"][0].update(sample_rows=[["one"]]), "each sample row must match column_count"),
        (lambda d: d.update(schema_version="2.0"), "Input should be '1.1'"),
    ],
)
def test_malformed_contexts_are_rejected(mutate, message):
    data = _base()
    mutate(data)

    with pytest.raises(ValidationError, match=message):
        ClassificationContext.model_validate(data)


def test_classified_output_validates_against_its_own_contract(classifier):
    result = classifier.classify(ClassificationContext.model_validate(_base()))

    reloaded = ClassifiedDocument.model_validate(json.loads(result.model_dump_json()))
    assert reloaded.schema_version == "2.0"
    assert reloaded.versions.taxonomy == "2.1.1"
    assert reloaded.created_at == "2026-10-29T00:00:00Z"


def test_classifier_rejects_context_without_classifiable_content(classifier):
    data = _base()
    data["paragraphs"] = []
    data["tables"] = []
    data["quality"]["has_classifiable_content"] = False
    data["quality"]["warnings"] = ["no_classifiable_content"]

    context = ClassificationContext.model_validate(data)

    with pytest.raises(ValueError, match="no classifiable paragraphs or tables"):
        classifier.classify(context)


def test_classifier_rejects_context_with_failed_pages(classifier):
    data = _base()
    data["quality"]["failed_pages"] = [2]
    data["quality"]["warnings"] = ["extraction_failed_pages"]
    context = ClassificationContext.model_validate(data)

    with pytest.raises(ValueError, match="classification context is incomplete"):
        classifier.classify(context)
