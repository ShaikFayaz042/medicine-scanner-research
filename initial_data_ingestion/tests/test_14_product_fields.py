"""Regression tests for product field extraction and validation."""

from shared.extract import extract_record_lineage
from shared.resolve import resolve_record


def test_brand_is_not_filled_from_product_name():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Paracetamol Tablets 500mg",
        "batch_number": "B-1",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert extracted["brand_name"] == ""


def test_explicit_brand_and_valid_product_fields_are_preserved():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Paracetamol Tablets 500mg",
        "brand_name": "Calpol",
        "dosage_form": "Tablet",
        "strength": "500mg",
        "product_category": "DRUG",
        "batch_number": "B-1",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]
    resolved = resolve_record("DOC001", "NSQ_STATE", extracted)

    assert resolved["brand_name"] == "Calpol"
    assert resolved["dosage_form"] == "Tablet"
    assert resolved["strength"] == "500mg"
    assert resolved["product_category"] == "DRUG"


def test_invalid_product_category_falls_back_to_drug():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Unclassified product",
        "product_category": "INVALID",
        "batch_number": "B-1",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]
    resolved = resolve_record("DOC001", "NSQ_STATE", extracted)

    assert resolved["product_category"] == "DRUG"