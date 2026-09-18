"""
Test 1: End-to-End Processing
Pass criteria:
- All expected CSVs are created
- Expected non-empty tables are non-empty
- Process completes successfully
"""

import os
import shutil
from shared.run import run_pipeline
from shared.validate import read_csv_rows

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")
STAGING_DIR = os.path.join("09_normalization", "01_staging", "test_run_e2e")


def test_01_end_to_end():
    if os.path.exists(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)

    exit_code = run_pipeline(TEST_JSON, STAGING_DIR, load_db_flag=False)
    assert exit_code == 0, "Pipeline run_pipeline exit code should be 0"

    expected_csvs = [
        "regulatory_documents.csv",
        "raw_source_records.csv",
        "organizations.csv",
        "ingredients.csv",
        "products.csv",
        "product_ingredients.csv",
        "product_organizations.csv",
        "batches.csv",
        "regulatory_events.csv",
        "normalization_manifest.csv"
    ]

    for csv_file in expected_csvs:
        p = os.path.join(STAGING_DIR, csv_file)
        assert os.path.exists(p), f"Staging CSV missing: {csv_file}"

    # Verify non-empty files
    docs = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_documents.csv"))
    assert len(docs) == 1, "Should have 1 regulatory document row"

    raw = read_csv_rows(os.path.join(STAGING_DIR, "raw_source_records.csv"))
    assert len(raw) == 3, "Should have 3 raw source records"

    events = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_events.csv"))
    assert len(events) == 3, "Should have 3 regulatory event rows"

    manifest = read_csv_rows(os.path.join(STAGING_DIR, "normalization_manifest.csv"))
    assert len(manifest) == 3, "Should have 3 manifest rows"


if __name__ == "__main__":
    test_01_end_to_end()
    print("Test 01 (End-to-End) PASSED!")
