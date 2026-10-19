"""Regression tests on real CDSCO PDFs: parsing quality must never drop below the recorded baseline.

The PDFs are not committed (initial_data_ingestion/01_downloads is gitignored); tests skip when a file is
missing. Fetch them with `python -m data_processing_service.tests.regression.fetch_fixtures`.
"""

import pytest

from data_processing_service.tests.regression import harness

DOCUMENTS = harness.load_golden()


def test_golden_set_is_consistent():
    ids = [document["id"] for document in DOCUMENTS]
    assert len(ids) == len(set(ids))
    for document in DOCUMENTS:
        assert document["samples"], document["id"]
        assert document["baseline"]["rows_matched"] <= document["rows_expected"], document["id"]
        assert document["baseline"]["samples_correct"] <= len(document["samples"]), document["id"]
        for sample in document["samples"]:
            # batch or notification, not both; product-only samples are for alerts that name neither (device alerts)
            assert sample["product"] and not ("batch" in sample and "notification" in sample), (document["id"], sample)


@pytest.mark.parametrize(
    "document",
    [pytest.param(document, marks=[pytest.mark.ocr] if document["requires_ocr"] else []) for document in DOCUMENTS],
    ids=[document["id"] for document in DOCUMENTS],
)
def test_real_pdf_does_not_regress(document, monkeypatch):
    reason = harness.fixture_status(document)
    if reason:
        pytest.skip(reason)

    from data_processing_service.extractor import ocr as page_ocr
    from data_processing_service.extractor import run as extractor
    from data_processing_service.parser import run as parser

    if document["requires_ocr"] and not page_ocr.ocr_available():
        pytest.skip("rapidocr is not installed")

    def no_database(*_args, **_kwargs):
        raise AssertionError("regression tests must not touch the scraper database")

    for module, name in (
        (extractor, "get_document_metadata"),
        (extractor, "update_extracted_documents"),
        (parser, "get_document_metadata"),
        (parser, "update_parsed_documents"),
    ):
        monkeypatch.setattr(module, name, no_database)

    result = harness.score(document, harness.run_pipeline(document))
    problems = harness.meets_baseline(result, document["baseline"])
    assert not problems, f"{document['id']} {document['title']}: " + "; ".join(problems)
