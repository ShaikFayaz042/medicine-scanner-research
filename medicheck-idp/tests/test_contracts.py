"""The stage-4 input contract rejects malformed documents; the stage-5 output is valid JSON."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from conftest import build_document
from idp.schemas.classified import ClassifiedDocument
from idp.schemas.structured import StructuredDocument


def _base() -> dict:
    return build_document(["A paragraph."], tables=[{"table_id": "t1", "header_rows": [["S.No", "Name"]], "rows": [["1", "X"]]}]).model_dump()


def test_valid_document_round_trips_through_json():
    data = _base()
    assert StructuredDocument.model_validate(json.loads(json.dumps(data))).tables[0].table_id == "t1"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["pages"][0]["blocks"].append({"block_id": "x", "type": "table_ref", "table_id": "missing"}), "unknown tables"),
        (lambda d: d["pages"][0]["blocks"].append(dict(d["pages"][0]["blocks"][0])), "block_id values must be unique"),
        (lambda d: d["tables"][0].update(pages=[9]), "not in pages"),
        (lambda d: d["pages"][0]["blocks"][0].update(colour="red"), "colour"),
        (lambda d: d["pages"][0]["blocks"][0].update(type="table_ref"), "table_ref blocks need table_id"),
        (lambda d: d.update(schema_version="2.0"), "schema_version"),
    ],
)
def test_malformed_documents_are_rejected(mutate, message):
    data = _base()
    mutate(data)

    with pytest.raises(ValidationError, match=message):
        StructuredDocument.model_validate(data)


def test_classified_output_validates_against_its_own_contract(classifier):
    result = classifier.classify(StructuredDocument.model_validate(_base()))

    reloaded = ClassifiedDocument.model_validate(json.loads(result.model_dump_json()))
    assert reloaded.versions.taxonomy == "2.1.0"
    assert reloaded.created_at == "2026-10-29T00:00:00Z"
