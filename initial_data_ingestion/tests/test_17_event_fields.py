"""Regression tests for regulatory event date and action handling."""

from shared.resolve import resolve_record


def _record(**values):
    record = {
        "source_record_id": "DOC001:P01:T01:event:01",
        "product_name": "Test product",
        "batch_number": "B-1",
        "event_date": "2026-09-01",
        "event_type": "NSQ",
        "scope": "BATCH",
        "status": "NSQ",
        "additional_data": {},
    }
    record.update(values)
    return record


def test_explicit_action_and_date_are_preserved_with_sources():
    resolved = resolve_record(
        "DOC001",
        "NSQ_CDSCO",
        _record(action="Recall affected batches"),
    )

    assert resolved["event_date"] == "2026-09-01"
    assert resolved["action"] == "Recall affected batches"
    assert resolved["additional_data"]["_pipeline"]["event_date_source"] == "EXTRACTED"
    assert resolved["additional_data"]["_pipeline"]["action_source"] == "EXTRACTED"


def test_missing_action_gets_controlled_inference():
    resolved = resolve_record("DOC001", "NSQ_CDSCO", _record(event_date=None))

    assert resolved["action"] == "QUALITY_ALERT"
    assert resolved["additional_data"]["_pipeline"]["action_source"] == "INFERRED"