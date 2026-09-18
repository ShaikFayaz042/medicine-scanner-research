"""
Test 3: Duplicate Canonical Keys
Pass criteria: Zero duplicate canonical keys across entity and event staging files.
"""

import os
from shared.run import run_pipeline
from shared.validate import read_csv_rows

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")
STAGING_DIR = os.path.join("09_normalization", "01_staging", "test_run_duplicates")


def assert_unique_column(rows, col_name, file_label):
    seen = set()
    for r in rows:
        val = r.get(col_name)
        if val:
            assert val not in seen, f"Duplicate {col_name} '{val}' in {file_label}"
            seen.add(val)


def test_03_duplicate_keys():
    run_pipeline(TEST_JSON, STAGING_DIR)

    manifest_rows = read_csv_rows(os.path.join(STAGING_DIR, "normalization_manifest.csv"))
    events_rows = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_events.csv"))
    orgs_rows = read_csv_rows(os.path.join(STAGING_DIR, "organizations.csv"))
    prods_rows = read_csv_rows(os.path.join(STAGING_DIR, "products.csv"))
    batches_rows = read_csv_rows(os.path.join(STAGING_DIR, "batches.csv"))

    assert_unique_column(manifest_rows, "source_record_id", "normalization_manifest.csv")
    assert_unique_column(events_rows, "event_key", "regulatory_events.csv")
    assert_unique_column(orgs_rows, "organization_key", "organizations.csv")
    assert_unique_column(prods_rows, "product_key", "products.csv")
    assert_unique_column(batches_rows, "batch_key", "batches.csv")


if __name__ == "__main__":
    test_03_duplicate_keys()
    print("Test 03 (Duplicate Keys) PASSED!")
