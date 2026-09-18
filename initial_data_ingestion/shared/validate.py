"""
Validation Module: Performs pre-database loading data integrity,
reconciliation, duplicate key, orphan relationship, and manifest taxonomy checks.
"""

import os
import csv
import re
from typing import Dict, Any, List, Set, Tuple


VALID_NORMALIZATION_STATUSES = {'COMPLETE', 'NEEDS_REVIEW', 'IGNORED', 'FAILED'}
VALID_VALIDATION_STATUSES = {'PENDING', 'VALID', 'INVALID'}
VALID_REVIEW_REASONS = {
    'missing_product_name',
    'missing_batch_number',
    'nsq_without_batch',
    'ambiguous_organization',
    'ambiguous_product',
    'invalid_date_format',
    'unparseable_row',
    'duplicate_fingerprint',
    'excluded_document_type',
    ''
}


def read_csv_rows(filepath: str) -> List[Dict[str, str]]:
    """Helper to read CSV into list of dicts."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        return list(reader)



def _content_tokens(value: str) -> Set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", (value or "").lower())}


def validate_content_lineage(staging_dir: str) -> Tuple[bool, List[str]]:
    """Check that extracted event values are represented in their raw source record."""
    events = read_csv_rows(os.path.join(staging_dir, "regulatory_events.csv"))
    raws = {
        row["source_record_id"]: row
        for row in read_csv_rows(os.path.join(staging_dir, "raw_source_records.csv"))
    }
    errors = []
    for event in events:
        raw = raws.get(event.get("source_record_id"))
        if not raw:
            errors.append(f"Missing raw source for event {event.get('event_key')}")
            continue
        source_tokens = _content_tokens(raw.get("source_text", ""))
        value = event.get("reason", "")
        if value and not (_content_tokens(value) & source_tokens):
            errors.append(f"Event {event.get('event_key')} reason is absent from source_text")
    return not errors, errors


def validate_staging_dir(staging_dir: str) -> Tuple[bool, List[str]]:
    """
    Validate all staging CSV files in staging_dir.
    Returns:
      (is_valid, list_of_error_messages)
    """
    errors = []

    manifest_path = os.path.join(staging_dir, "normalization_manifest.csv")
    events_path = os.path.join(staging_dir, "regulatory_events.csv")
    orgs_path = os.path.join(staging_dir, "organizations.csv")
    prods_path = os.path.join(staging_dir, "products.csv")
    batches_path = os.path.join(staging_dir, "batches.csv")
    prod_orgs_path = os.path.join(staging_dir, "product_organizations.csv")
    raw_path = os.path.join(staging_dir, "raw_source_records.csv")

    manifest_rows = read_csv_rows(manifest_path)
    events_rows = read_csv_rows(events_path)
    orgs_rows = read_csv_rows(orgs_path)
    prods_rows = read_csv_rows(prods_path)
    batches_rows = read_csv_rows(batches_path)
    prod_orgs_rows = read_csv_rows(prod_orgs_path)
    raw_rows = read_csv_rows(raw_path)

    # 1. Reconciliation Invariant
    total_records = len(manifest_rows)
    counts = {'COMPLETE': 0, 'NEEDS_REVIEW': 0, 'IGNORED': 0, 'FAILED': 0}
    
    for r in manifest_rows:
        ns = r.get("normalization_status")
        if ns in counts:
            counts[ns] += 1
        else:
            errors.append(f"Invalid normalization_status '{ns}' in manifest for record {r.get('source_record_id')}")

        vs = r.get("validation_status")
        if vs not in VALID_VALIDATION_STATUSES:
            errors.append(f"Invalid validation_status '{vs}' in manifest for record {r.get('source_record_id')}")

        rr = r.get("review_reason") or ""
        if rr and rr not in VALID_REVIEW_REASONS:
            errors.append(f"Invalid review_reason '{rr}' in manifest for record {r.get('source_record_id')}")

    sum_status = sum(counts.values())
    if total_records != sum_status:
        errors.append(f"Reconciliation failure: Total source records ({total_records}) != sum of status counts ({sum_status})")

    # 2. Duplicate Key Checks
    def check_unique_key(rows: List[Dict[str, str]], key_col: str, file_label: str):
        seen = set()
        for r in rows:
            val = r.get(key_col)
            if val:
                if val in seen:
                    errors.append(f"Duplicate key '{val}' found in {file_label} (column {key_col})")
                seen.add(val)

    check_unique_key(manifest_rows, "source_record_id", "normalization_manifest.csv")
    check_unique_key(events_rows, "event_key", "regulatory_events.csv")
    check_unique_key(orgs_rows, "organization_key", "organizations.csv")
    check_unique_key(prods_rows, "product_key", "products.csv")
    check_unique_key(batches_rows, "batch_key", "batches.csv")

    # 3. Orphan Relationship Checks
    known_org_keys: Set[str] = {r["organization_key"] for r in orgs_rows if r.get("organization_key")}
    known_prod_keys: Set[str] = {r["product_key"] for r in prods_rows if r.get("product_key")}
    known_batch_keys: Set[str] = {r["batch_key"] for r in batches_rows if r.get("batch_key")}

    # Check Regulatory Events foreign keys
    for r in events_rows:
        pk = r.get("product_key")
        if pk and pk not in known_prod_keys:
            errors.append(f"Orphan product_key '{pk}' in regulatory_events.csv (event_key {r.get('event_key')})")

        m_org = r.get("manufacturer_organization_key")
        if m_org and m_org not in known_org_keys:
            errors.append(f"Orphan manufacturer_organization_key '{m_org}' in regulatory_events.csv (event_key {r.get('event_key')})")

        r_org = r.get("reporting_organization_key")
        if r_org and r_org not in known_org_keys:
            errors.append(f"Orphan reporting_organization_key '{r_org}' in regulatory_events.csv (event_key {r.get('event_key')})")

        bk = r.get("batch_key")
        if bk and bk not in known_batch_keys:
            errors.append(f"Orphan batch_key '{bk}' in regulatory_events.csv (event_key {r.get('event_key')})")

    # Check Batches foreign keys
    for r in batches_rows:
        pk = r.get("product_key")
        if pk and pk not in known_prod_keys:
            errors.append(f"Orphan product_key '{pk}' in batches.csv (batch_key {r.get('batch_key')})")
        ok = r.get("organization_key")
        if ok and ok not in known_org_keys:
            errors.append(f"Orphan organization_key '{ok}' in batches.csv (batch_key {r.get('batch_key')})")

    # Check Product-Organizations foreign keys
    for r in prod_orgs_rows:
        pk = r.get("product_key")
        if pk and pk not in known_prod_keys:
            errors.append(f"Orphan product_key '{pk}' in product_organizations.csv")
        ok = r.get("organization_key")
        if ok and ok not in known_org_keys:
            errors.append(f"Orphan organization_key '{ok}' in product_organizations.csv")

    is_valid = len(errors) == 0

    # Update manifest validation status in file
    if manifest_rows:
        new_status = "VALID" if is_valid else "INVALID"
        fieldnames = list(manifest_rows[0].keys())
        for r in manifest_rows:
            r["validation_status"] = new_status

        with open(manifest_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manifest_rows)

    return is_valid, errors
