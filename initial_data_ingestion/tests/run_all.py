"""
Test Suite Runner: Executes all 8 validation tests
"""

import sys
import os

from tests.test_01_e2e import test_01_end_to_end
from tests.test_02_reconciliation import test_02_reconciliation
from tests.test_03_duplicates import test_03_duplicate_keys
from tests.test_04_orphans import test_04_orphan_relationships
from tests.test_05_db_load import test_05_db_load_structure
from tests.test_06_idempotency import test_06_idempotency
from tests.test_07_lineage import test_07_lineage_traceability
from tests.test_08_mutation import test_08_mutation_isolation


def run_all_tests():
    print("=" * 60)
    print("Running Medicine Regulatory ETL Validation Suite")
    print("=" * 60)

    tests = [
        ("Test 01: End-to-End Processing", test_01_end_to_end),
        ("Test 02: Reconciliation Invariant", test_02_reconciliation),
        ("Test 03: Duplicate Keys Isolation", test_03_duplicate_keys),
        ("Test 04: Orphan Relationships", test_04_orphan_relationships),
        ("Test 05: Database Load Structure", test_05_db_load_structure),
        ("Test 06: Pipeline Idempotency", test_06_idempotency),
        ("Test 07: Lineage Traceability", test_07_lineage_traceability),
        ("Test 08: Mutation Isolation", test_08_mutation_isolation),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"Running {name}...", end=" ")
            test_func()
            print("PASSED")
            passed += 1
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1

    print("=" * 60)
    print(f"Summary: {passed} PASSED, {failed} FAILED out of {len(tests)} tests")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
