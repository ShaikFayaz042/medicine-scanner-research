"""Extract batch candidates from events.jsonl."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR, write_jsonl, utcnow_iso,
    normalize_search_name, make_candidate_key, safe_str,
    parse_drug_alert_batch_field, parse_date_with_precision,
)


def load_source_to_key(path: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    if not path.exists():
        return output
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            for source_id in row.get("source_record_ids", []):
                output[source_id] = row["candidate_key"]
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="events.jsonl")
    parser.add_argument("--products", default="products.jsonl")
    parser.add_argument("--manufacturers", default="manufacturers.jsonl")
    args = parser.parse_args()
    events_path = OUTPUT_DIR / args.input
    if not events_path.exists():
        print(f"[error] missing {events_path}; run normalize_events.py first")
        return 1
    source_to_product = load_source_to_key(OUTPUT_DIR / args.products)
    source_to_manufacturer = load_source_to_key(OUTPUT_DIR / args.manufacturers)
    by_key: dict[str, dict] = {}

    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            slots = event.get("_raw_slots") or {}
            document_type = event.get("document_type")
            source_id = event.get("source_record_id")
            batch_raw = slots.get("batch_number_raw")
            mfg_raw = slots.get("mfg_date_raw")
            expiry_raw = slots.get("expiry_date_raw")
            manufacturer_raw = slots.get("manufacturer_name_raw")
            if document_type == "DRUG_ALERT" and batch_raw and any(
                token in batch_raw for token in ("Mfg dt", "Mfg.", "Exp dt", "Mfd by")
            ):
                parsed = parse_drug_alert_batch_field(batch_raw)
                batch_raw = parsed["batch_number"] or batch_raw
                mfg_raw = mfg_raw or parsed["mfg_date_raw"]
                expiry_raw = expiry_raw or parsed["expiry_date_raw"]
                manufacturer_raw = manufacturer_raw or parsed["manufacturer_name_raw"]
            if not batch_raw:
                continue
            product_key = source_to_product.get(source_id)
            if not product_key:
                continue
            manufacturer_key = source_to_manufacturer.get(source_id)
            batch_number = safe_str(batch_raw)
            if not batch_number:
                continue
            normalized = normalize_search_name(batch_number)
            key = make_candidate_key(product_key, manufacturer_key or "", normalized)
            mfg_date, mfg_precision = parse_date_with_precision(mfg_raw)
            expiry_date, expiry_precision = parse_date_with_precision(expiry_raw)
            row = by_key.setdefault(key, {
                "candidate_key": key,
                "product_candidate_key": product_key,
                "manufacturer_candidate_key": manufacturer_key,
                "batch_number": batch_number,
                "batch_number_normalized": normalized,
                "mfg_date": mfg_date.isoformat() if mfg_date else None,
                "mfg_date_raw": safe_str(mfg_raw),
                "mfg_date_precision": mfg_precision,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
                "expiry_date_raw": safe_str(expiry_raw),
                "expiry_date_precision": expiry_precision,
                "match_status": "UNREVIEWED",
                "source_record_ids": [],
                "_created_at": utcnow_iso(),
            })
            if source_id and source_id not in row["source_record_ids"]:
                row["source_record_ids"].append(source_id)

    output = OUTPUT_DIR / "batches.jsonl"
    print(f"[ok] wrote {write_jsonl(by_key.values(), output)} batches -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
