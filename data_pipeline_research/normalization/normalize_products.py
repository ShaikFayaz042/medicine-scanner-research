"""Extract commercial product candidates from events.jsonl.

FDC composition-only records remain COMBINATION events and never become products.
"""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR, write_jsonl, utcnow_iso,
    split_product_and_composition, detect_dosage_form,
    normalize_search_name, make_candidate_key, collapse_ws,
)

PRODUCT_SLOT_KEYS = ("product_name_raw",)
FDC_TYPES = {"FDC_PROHIBITED", "FDC_NOTIFICATION"}
NOISE_PREFIXES = (
    "sample does not conform",
    "sample not conform",
    "does not conform to label",
    "label claim",
    "reason:",
    "remark:",
    "not of standard",
    "does not conform",
    "does not comply",
    "sample does not confirm",
    "the sample does not",
    "it fails the test",
    "the content of",
)


def load_source_to_key(path: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    if not path.exists():
        return output
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            for source_id in row.get("source_record_ids", []):
                output[source_id] = row.get("candidate_key")
    return output


def classify_composition(raw_product: str, composition: str | None) -> tuple[str, str]:
    if not composition:
        return "NONE", "NONE"
    if "(" in raw_product and ")" in raw_product:
        return "INFERRED_FROM_PRODUCT_NAME", "MEDIUM"
    return "EXPLICIT", "HIGH"


def is_noise(name: str) -> bool:
    value = (name or "").lower().strip()
    return len(value) < 3 or any(value.startswith(prefix) for prefix in NOISE_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="events.jsonl")
    parser.add_argument("--manufacturers", default="manufacturers.jsonl")
    args = parser.parse_args()
    events_path = OUTPUT_DIR / args.input
    if not events_path.exists():
        print(f"[error] missing {events_path}; run normalize_events.py first")
        return 1

    by_key: dict[str, dict] = {}
    filtered_noise: list[dict] = []
    source_to_manufacturer = load_source_to_key(OUTPUT_DIR / args.manufacturers)
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            if event.get("document_type") in FDC_TYPES:
                continue
            slots = event.get("_raw_slots") or {}
            raw = next((slots[key] for key in PRODUCT_SLOT_KEYS if slots.get(key)), None)
            if not raw:
                continue
            if is_noise(raw):
                filtered_noise.append({
                    "raw": raw,
                    "source_record_id": event.get("source_record_id"),
                    "document_type": event.get("document_type"),
                })
                continue
            name, composition = split_product_and_composition(raw)
            if not name:
                continue
            dosage = detect_dosage_form(name) or detect_dosage_form(raw)
            normalized = normalize_search_name(name)
            if not normalized:
                continue
            manufacturer_key = source_to_manufacturer.get(event.get("source_record_id"))
            key = make_candidate_key(normalized, manufacturer_key or "", dosage or "")
            composition_source, composition_confidence = classify_composition(raw, composition)
            row = by_key.setdefault(key, {
                "candidate_key": key,
                "product_name": name,
                "product_name_raw": collapse_ws(raw),
                "brand_name": None,
                "generic_name": None,
                "dosage_form": dosage,
                "route": None,
                "raw_composition": composition,
                "composition_source": composition_source,
                "composition_confidence": composition_confidence,
                "normalized_search_name": normalized,
                "manufacturer_candidate_key": manufacturer_key,
                "origin": "PRODUCT_NAME",
                "match_status": "UNREVIEWED",
                "source_record_ids": [],
                "_created_at": utcnow_iso(),
            })
            source_id = event.get("source_record_id")
            if source_id and source_id not in row["source_record_ids"]:
                row["source_record_ids"].append(source_id)
            if not row["raw_composition"] and composition:
                row["raw_composition"] = composition
                row["composition_source"] = composition_source
                row["composition_confidence"] = composition_confidence

    rows = list(by_key.values())
    output = OUTPUT_DIR / "products.jsonl"
    print(f"[ok] wrote {write_jsonl(rows, output)} products -> {output}")
    noise_output = OUTPUT_DIR / "filtered_products.jsonl"
    print(f"[ok] wrote {write_jsonl(filtered_noise, noise_output)} filtered-noise rows -> {noise_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
