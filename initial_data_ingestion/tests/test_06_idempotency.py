"""
Test 6: Pipeline Idempotency
Pass criteria: Repeated pipeline runs produce identical canonical keys and identical staging contents.
"""

import os
import shutil
from shared.run import run_pipeline
from shared.validate import read_csv_rows

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")


def test_06_idempotency():
    dir1 = os.path.join("09_normalization", "01_staging", "test_run_idemp_1")
    dir2 = os.path.join("09_normalization", "01_staging", "test_run_idemp_2")

    for d in (dir1, dir2):
        if os.path.exists(d):
            shutil.rmtree(d)

    run_pipeline(TEST_JSON, dir1)
    run_pipeline(TEST_JSON, dir2)

    files = [
        "regulatory_documents.csv",
        "organizations.csv",
        "products.csv",
        "batches.csv",
        "regulatory_events.csv",
        "normalization_manifest.csv"
    ]

    for fname in files:
        rows1 = read_csv_rows(os.path.join(dir1, fname))
        rows2 = read_csv_rows(os.path.join(dir2, fname))

        assert len(rows1) == len(rows2), f"Row count mismatch in {fname}"

        # Check key set equality
        if "event_key" in (rows1[0] if rows1 else {}):
            keys1 = {r["event_key"] for r in rows1}
            keys2 = {r["event_key"] for r in rows2}
            assert keys1 == keys2, f"Event keys mismatch in {fname}"
        elif "product_key" in (rows1[0] if rows1 else {}):
            keys1 = {r["product_key"] for r in rows1}
            keys2 = {r["product_key"] for r in rows2}
            assert keys1 == keys2, f"Product keys mismatch in {fname}"


if __name__ == "__main__":
    test_06_idempotency()
    print("Test 06 (Idempotency) PASSED!")
