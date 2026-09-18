"""
Test 2: Manifest Reconciliation
Pass criteria: Total source records == COMPLETE + NEEDS_REVIEW + IGNORED + FAILED
"""

import os
from shared.run import run_pipeline
from shared.validate import read_csv_rows

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")
STAGING_DIR = os.path.join("09_normalization", "01_staging", "test_run_reconciliation")


def test_02_reconciliation():
    run_pipeline(TEST_JSON, STAGING_DIR)

    manifest_rows = read_csv_rows(os.path.join(STAGING_DIR, "normalization_manifest.csv"))
    total_records = len(manifest_rows)

    status_counts = {'COMPLETE': 0, 'NEEDS_REVIEW': 0, 'IGNORED': 0, 'FAILED': 0}
    for r in manifest_rows:
        ns = r["normalization_status"]
        assert ns in status_counts, f"Unrecognized normalization status '{ns}'"
        status_counts[ns] += 1

    sum_counts = sum(status_counts.values())
    assert total_records == sum_counts, f"Reconciliation failure: Total records {total_records} != sum {sum_counts}"
    assert status_counts['COMPLETE'] == 2, "Expected 2 COMPLETE records"
    assert status_counts['NEEDS_REVIEW'] == 1, "Expected 1 NEEDS_REVIEW record (missing product name)"


if __name__ == "__main__":
    test_02_reconciliation()
    print("Test 02 (Reconciliation) PASSED!")
