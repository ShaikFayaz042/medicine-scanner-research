from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server.routes.medicines import MedicineSearchRequest
from server.services.medicine_service import _build_assessment, _serialize, _serialize_match


def _event(**overrides):
    event = {
        "event_type": "QUALITY_FAILURE",
        "scope": "BATCH",
        "batch_number": "B-123",
        "status": "NOT_OF_STANDARD_QUALITY",
        "legal_status": None,
        "reason": "Dissolution",
    }
    event.update(overrides)
    return event


def test_search_request_requires_at_least_one_non_empty_search_field():
    with pytest.raises(ValidationError):
        MedicineSearchRequest(limit=20)

    request = MedicineSearchRequest(batch_number=" B-123 ", limit=20)
    assert request.batch_number == " B-123 "


def test_batch_quality_event_is_yellow_not_red():
    assessment = _build_assessment([_event()])

    assert assessment["indicator"] == "YELLOW"
    assert assessment["template_id"] == "BATCH_QUALITY_ALERT"
    assert "B-123" in assessment["summary"]


def test_only_explicit_prohibition_or_restriction_is_red():
    assessment = _build_assessment([_event(legal_status="PROHIBITED")])

    assert assessment["indicator"] == "RED"
    assert assessment["template_id"] == "LEGAL_RESTRICTION"


def test_unknown_scope_is_not_assessed_as_green_or_red():
    assessment = _build_assessment([_event(scope="UNMAPPED")])

    assert assessment["indicator"] == "UNKNOWN"


def test_no_events_returns_caveated_green_assessment():
    assessment = _build_assessment([])

    assert assessment["indicator"] == "GREEN"
    assert "does not guarantee" in assessment["summary"]


def test_batch_search_excludes_other_batch_events_and_sources():
    matching_batch = SimpleNamespace(id=1, batch_number="B-123")
    unrelated_batch = SimpleNamespace(id=2, batch_number="B-456")

    def regulatory_event(batch):
        document = SimpleNamespace(
            id=batch.id + 100,
            title=f"Alert {batch.batch_number}",
            document_type="REGULATORY_ALERT",
            publication_date=None,
            source_url=f"https://example.test/{batch.batch_number}.pdf",
            pdf_filename=f"{batch.batch_number}.pdf",
        )
        return SimpleNamespace(
            id=batch.id,
            source_record_id=f"source-{batch.id}",
            event_type="QUALITY_FAILURE",
            scope="BATCH",
            batch_id=batch.id,
            batch=batch,
            status="NOT_OF_STANDARD_QUALITY",
            legal_status=None,
            reason="Dissolution",
            effective_date=None,
            document=document,
        )

    product = SimpleNamespace(
        id=9,
        product_name="Paracetamol Tablet",
        normalized_search_name="paracetamol tablet",
        brand_name=None,
        generic_name="Paracetamol",
        dosage_form="Tablet",
        route="Oral",
        manufacturer=None,
        ingredients=[],
        batches=[matching_batch, unrelated_batch],
        regulatory_events=[regulatory_event(matching_batch), regulatory_event(unrelated_batch)],
    )

    result = _serialize_match(
        product,
        100,
        "EXACT",
        {"name": "paracetamol", "batch_number": "B-123"},
    )

    assert result["matched_by"] == ["product_name", "batch_number"]
    assert [event["batch_number"] for event in result["regulatory_events"]] == ["B-123"]
    assert [source["source_record_id"] for source in result["source_references"]] == ["source-1"]
    assert result["assessment"]["indicator"] == "YELLOW"


def test_serialize_product_detail_includes_product_and_assessment_fields():
    product = SimpleNamespace(
        id=9,
        product_name="Paracetamol Tablet",
        normalized_search_name="paracetamol tablet",
        brand_name="Panadol",
        generic_name="Paracetamol",
        dosage_form="Tablet",
        route="Oral",
        manufacturer=SimpleNamespace(name="Acme Labs"),
        ingredients=[
            SimpleNamespace(
                ingredient=SimpleNamespace(name="Paracetamol", normalized_name="paracetamol"),
                strength=500,
                strength_text="500 mg",
                unit="mg",
            )
        ],
        batches=[],
        regulatory_events=[],
    )

    result = _serialize(product, {})

    assert result["id"] == 9
    assert result["product"]["manufacturer"] == "Acme Labs"
    assert result["product"]["name"] == "Paracetamol Tablet"
    assert result["assessment"]["indicator"] == "GREEN"