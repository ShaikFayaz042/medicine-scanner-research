"""
Test 7: Lineage Integrity
Pass criteria: Joining regulatory_event to raw_source_record and regulatory_document
recovers source record ID, page number, filename, source location, and original text.
"""

import os
from shared.run import run_pipeline
from shared.validate import read_csv_rows, validate_content_lineage

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")
STAGING_DIR = os.path.join("09_normalization", "01_staging", "test_run_lineage")


def test_07_lineage_traceability():
    run_pipeline(TEST_JSON, STAGING_DIR)

    docs = {r["source_document_id"]: r for r in read_csv_rows(os.path.join(STAGING_DIR, "regulatory_documents.csv"))}
    raws = {r["source_record_id"]: r for r in read_csv_rows(os.path.join(STAGING_DIR, "raw_source_records.csv"))}
    events = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_events.csv"))

    for ev in events:
        src_rec_id = ev["source_record_id"]
        doc_id = ev["source_document_id"]

        assert src_rec_id in raws, f"Raw record '{src_rec_id}' missing in raw_source_records"
        assert doc_id in docs, f"Document '{doc_id}' missing in regulatory_documents"

        raw_item = raws[src_rec_id]
        doc_item = docs[doc_id]

        assert raw_item["source_document_id"] == doc_id
        assert doc_item["filename"] == "nsq_test.json"
        assert int(raw_item["page_number"]) >= 1
        assert raw_item["source_text"] is not None

    content_valid, content_errors = validate_content_lineage(STAGING_DIR)
    assert content_valid, "Content lineage errors: " + "; ".join(content_errors)


if __name__ == "__main__":
    test_07_lineage_traceability()
    print("Test 07 (Lineage) PASSED!")
