"""Regression tests for product-to-ingredient strength propagation."""

from shared.extract import extract_record_lineage


def test_explicit_strength_populates_single_ingredient_link():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Gabapentin Tablets I.P.",
        "strength": "300 mg",
        "batch_number": "B-1",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert extracted["ingredients"] == [{"name": "Gabapentin", "strength": "300 mg"}]


def test_combination_strength_is_not_assigned_to_every_ingredient():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Drug A + Drug B",
        "strength": "10 mg + 20 mg",
        "batch_number": "B-1",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert [item["strength"] for item in extracted["ingredients"]] == ["", ""]