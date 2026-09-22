"""Regression tests for document date and type inference."""

import json

from shared.extract import detect_document_type, infer_document_period, load_parsed_json


def test_filename_month_is_converted_to_month_precision_date():
    assert infer_document_period("10785_Drug_Alert_for_the_Month_of_May_2022.json") == (
        "2022-05-01",
        "May 2022",
    )


def test_common_nsq_filenames_are_not_unknown():
    assert detect_document_type("11256_NOT_OF_STANDARD_QUALITY_ALERT_FOR_THE_MONTH_OF_APRIL-2024.json", {}) == "NSQ_STATE"
    assert detect_document_type("10069_Drug_Alert_list_for_month_of_March_2023.json", {}) == "NSQ_STATE"


def test_explicit_metadata_takes_precedence_over_filename(tmp_path):
    path = tmp_path / "alert_March_2023.json"
    path.write_text(json.dumps({
        "publication_date": "2026-09-01",
        "reporting_period": "September 2026",
        "document_type": "NSQ_CDSCO",
        "records": [],
    }), encoding="utf-8")

    header, records = load_parsed_json(str(path))

    assert header["publication_date"] == "2026-09-01"
    assert header["reporting_period"] == "September 2026"
    assert header["document_type"] == "NSQ_CDSCO"
    assert records == []