"""Extract manufacturer candidates from events.jsonl."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR, write_jsonl, utcnow_iso,
    normalize_search_name, make_candidate_key, collapse_ws,
)

PREFIXES = ("m/s.", "m/s", "ms.", "ms ")


def clean_manufacturer(raw: str) -> str:
    value = collapse_ws(raw)
    lowered = value.lower()
    for prefix in PREFIXES:
        if lowered.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="events.jsonl")
    args = parser.parse_args()
    events_path = OUTPUT_DIR / args.input
    if not events_path.exists():
        print(f"[error] missing {events_path}; run normalize_events.py first")
        return 1

    by_key: dict[str, dict] = {}
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            slots = event.get("_raw_slots") or {}
            raw = slots.get("manufacturer_name_raw")
            if not raw:
                continue
            name = clean_manufacturer(raw)
            normalized = normalize_search_name(name)
            if not normalized:
                continue
            key = make_candidate_key(normalized)
            row = by_key.setdefault(key, {
                "candidate_key": key,
                "name": name,
                "normalized_name": normalized,
                "address": None,
                "country": None,
                "match_status": "UNREVIEWED",
                "source_record_ids": [],
                "_created_at": utcnow_iso(),
            })
            source_id = event.get("source_record_id")
            if source_id and source_id not in row["source_record_ids"]:
                row["source_record_ids"].append(source_id)

    output = OUTPUT_DIR / "manufacturers.jsonl"
    print(f"[ok] wrote {write_jsonl(by_key.values(), output)} manufacturers -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
