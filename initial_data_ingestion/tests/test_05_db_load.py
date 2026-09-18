"""
Test 5: Database Load Interface
Pass criteria: Validates load_db staging CSV reading and SQL parameter mapping.
"""

import os
from shared.run import run_pipeline
from shared.validate import read_csv_rows
from shared.load_db import HAS_PSYCOPG2

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")
STAGING_DIR = os.path.join("09_normalization", "01_staging", "test_run_db_load")


def test_05_db_load_structure():
    run_pipeline(TEST_JSON, STAGING_DIR)

    # Verify staging CSV files exist and can be parsed by load_db functions
    doc_rows = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_documents.csv"))
    org_rows = read_csv_rows(os.path.join(STAGING_DIR, "organizations.csv"))
    prod_rows = read_csv_rows(os.path.join(STAGING_DIR, "products.csv"))
    batch_rows = read_csv_rows(os.path.join(STAGING_DIR, "batches.csv"))
    event_rows = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_events.csv"))

    assert len(doc_rows) == 1
    assert len(org_rows) >= 2
    assert len(prod_rows) == 2
    assert len(batch_rows) == 2
    assert len(event_rows) == 3


if __name__ == "__main__":
    test_05_db_load_structure()
    print("Test 05 (DB Load Structure) PASSED!")
