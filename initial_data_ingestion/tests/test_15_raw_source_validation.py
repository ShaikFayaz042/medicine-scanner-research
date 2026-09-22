"""Regression tests for raw-source completeness and JSON validation."""

import csv

from shared.validate import validate_raw_source_records


def _write_raw(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source_document_id",
                "source_record_id",
                "page_number",
                "source_location",
                "extraction_method",
                "source_text",
                "raw_json",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_raw_source_records_accept_complete_json(tmp_path):
    _write_raw(tmp_path / "raw_source_records.csv", [{
        "source_document_id": "DOC001",
        "source_record_id": "DOC001:P01:T01:abc:01",
        "page_number": "1",
        "source_location": "Page 1, Row 1",
        "extraction_method": "TEXT",
        "source_text": '{"product_name": "Test"}',
        "raw_json": '{"product_name": "Test"}',
    }])

    valid, errors = validate_raw_source_records(str(tmp_path))

    assert valid
    assert errors == []


def test_raw_source_records_reject_invalid_json_and_empty_source(tmp_path):
    _write_raw(tmp_path / "raw_source_records.csv", [{
        "source_document_id": "DOC001",
        "source_record_id": "DOC001:P01:T01:abc:01",
        "page_number": "1",
        "source_location": "Page 1, Row 1",
        "extraction_method": "TEXT",
        "source_text": "",
        "raw_json": "not-json",
    }])

    valid, errors = validate_raw_source_records(str(tmp_path))

    assert not valid
    assert any("empty source_text" in error for error in errors)
    assert any("invalid raw_json" in error for error in errors)