"""
Test 8: Mutation Isolation
Pass criteria:
Mutating only batch number:
- batch_key CHANGES
- product_key does NOT change
- organization_key does NOT change
- event_key does NOT change (when source record ID is held constant)
"""

from shared.resolve import resolve_record


def test_08_mutation_isolation():
    baseline_raw = {
        "source_record_id": "DOC001:P01:T01:8a91c2f3:01",
        "page_number": 1,
        "source_location": "Page 1, Row 1",
        "extraction_method": "TEXT",
        "source_text": "Sample text",
        "raw_json": {},
        "product_name": "Paracetamol 500mg",
        "batch_number": "BATCH-100",
        "manufacturer_name": "Acme Pharma",
        "manufacturer_state": "Delhi",
        "reporting_organization_name": "CDL Kolkata",
        "event_date": "2026-09-01"
    }

    mutated_raw = dict(baseline_raw)
    mutated_raw["batch_number"] = "BATCH-101"  # Only batch number mutated

    baseline = resolve_record("DOC001", "NSQ_STATE", baseline_raw)
    mutated = resolve_record("DOC001", "NSQ_STATE", mutated_raw)

    assert mutated["batch_key"] != baseline["batch_key"], "Batch key SHOULD change when batch number changes"
    assert mutated["product_key"] == baseline["product_key"], "Product key should NOT change when batch number mutates"
    assert mutated["manufacturer_organization_key"] == baseline["manufacturer_organization_key"], "Organization key should NOT change"
    assert mutated["event_key"] == baseline["event_key"], "Event key should NOT change when source record ID & event parameters remain constant"


if __name__ == "__main__":
    test_08_mutation_isolation()
    print("Test 08 (Mutation Isolation) PASSED!")
