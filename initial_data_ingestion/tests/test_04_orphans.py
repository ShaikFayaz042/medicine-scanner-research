"""
Test 4: Orphan Relationships
Pass criteria: Zero orphan relationship references in staging files before DB load.
"""

import os
from shared.run import run_pipeline
from shared.validate import read_csv_rows

TEST_JSON = os.path.join("tests", "fixtures", "parsed_json", "nsq_test.json")
STAGING_DIR = os.path.join("09_normalization", "01_staging", "test_run_orphans")


def test_04_orphan_relationships():
    run_pipeline(TEST_JSON, STAGING_DIR)

    events_rows = read_csv_rows(os.path.join(STAGING_DIR, "regulatory_events.csv"))
    orgs_rows = read_csv_rows(os.path.join(STAGING_DIR, "organizations.csv"))
    prods_rows = read_csv_rows(os.path.join(STAGING_DIR, "products.csv"))
    batches_rows = read_csv_rows(os.path.join(STAGING_DIR, "batches.csv"))
    prod_orgs_rows = read_csv_rows(os.path.join(STAGING_DIR, "product_organizations.csv"))

    known_orgs = {r["organization_key"] for r in orgs_rows if r.get("organization_key")}
    known_prods = {r["product_key"] for r in prods_rows if r.get("product_key")}
    known_batches = {r["batch_key"] for r in batches_rows if r.get("batch_key")}

    for r in events_rows:
        pk = r.get("product_key")
        if pk:
            assert pk in known_prods, f"Orphan product_key '{pk}' in event '{r['event_key']}'"

        m_org = r.get("manufacturer_organization_key")
        if m_org:
            assert m_org in known_orgs, f"Orphan manufacturer_org '{m_org}' in event '{r['event_key']}'"

        r_org = r.get("reporting_organization_key")
        if r_org:
            assert r_org in known_orgs, f"Orphan reporting_org '{r_org}' in event '{r['event_key']}'"

        bk = r.get("batch_key")
        if bk:
            assert bk in known_batches, f"Orphan batch_key '{bk}' in event '{r['event_key']}'"

    for r in batches_rows:
        pk = r.get("product_key")
        if pk:
            assert pk in known_prods, f"Orphan product_key '{pk}' in batch '{r['batch_key']}'"
        ok = r.get("organization_key")
        if ok:
            assert ok in known_orgs, f"Orphan organization_key '{ok}' in batch '{r['batch_key']}'"

    for r in prod_orgs_rows:
        assert r["product_key"] in known_prods, f"Orphan product_key '{r['product_key']}' in product_organizations"
        assert r["organization_key"] in known_orgs, f"Orphan organization_key '{r['organization_key']}' in product_organizations"


if __name__ == "__main__":
    test_04_orphan_relationships()
    print("Test 04 (Orphans) PASSED!")
