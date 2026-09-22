"""Regression tests for conservative CAS number extraction."""

from shared.extract import extract_record_lineage


def test_explicit_valid_cas_number_is_preserved_on_single_ingredient():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Paracetamol Tablets 500mg",
        "batch_number": "B-1",
        "cas_number": "103-90-2",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert extracted["ingredients"] == [
        {"name": "Paracetamol", "strength": "500mg", "cas_number": "103-90-2"}
    ]


def test_invalid_cas_number_is_not_invented():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Paracetamol Tablets 500mg",
        "batch_number": "B-1",
        "cas_number": "unknown",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert "cas_number" not in extracted["ingredients"][0]