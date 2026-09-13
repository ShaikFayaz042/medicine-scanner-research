#!/usr/bin/env python3
"""
CSV exports for:
    1. Every structured_raw/<type>/  → structured_raw/csv/<type>.csv
    2. NSQ API JSON (downloads/nsq_json/)  → downloads/nsq_json/csv/*.csv

Each CSV is a flat table where columns are the union of canonical keys
across all records of that type. Missing keys get empty cells.
"""

import csv
import json
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
REPO_ROOT = SCRIPTS_DIR.parent
STRUCTURED = REPO_ROOT / "structured_raw"
CSV_OUT_DIR = STRUCTURED / "csv"
API_JSON_DIR = REPO_ROOT / "downloads" / "nsq_json"
API_CSV_DIR = API_JSON_DIR / "csv"


# ---------------------------------------------------------------------------
# Part 1 — structured_raw → CSV (one per type)
# ---------------------------------------------------------------------------
def export_structured_type(type_dir: Path) -> dict:
    """Returns {"type": ..., "rows": N, "columns": M, "output": path}."""
    type_name = type_dir.name
    manifest_path = type_dir / "_manifest.json"
    if not manifest_path.exists():
        return {"type": type_name, "rows": 0, "columns": 0, "output": None}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs_meta = manifest.get("documents", [])

    # Collect all records
    rows: list[dict] = []
    for meta in docs_meta:
        if meta.get("status") not in ("SUCCESS", "skipped"):
            continue
        filename = meta.get("filename")
        if not filename:
            continue
        stem = Path(filename).stem
        doc_path = type_dir / f"{stem}.json"
        if not doc_path.exists():
            continue
        try:
            data = json.loads(doc_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        doc_id = data.get("document", {}).get("document_id")
        for i, rec in enumerate(data.get("records", [])):
            # Flatten canonical into columns, prefix with metadata
            flat = {
                "_type": type_name,
                "_doc_id": doc_id,
                "_source_file": filename,
                "_record_index": i,
                "_record_type": rec.get("record_type", ""),
                "_is_prose": bool(rec.get("prose")),
                "_section": rec.get("section", ""),
            }
            canonical = rec.get("canonical", {}) or {}
            for k, v in canonical.items():
                flat[k] = v
            rows.append(flat)

    if not rows:
        return {"type": type_name, "rows": 0, "columns": 0, "output": None}

    # Union of all keys, preserving order of first appearance
    seen_keys: list[str] = []
    seen_set: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_set:
                seen_keys.append(k)
                seen_set.add(k)

    CSV_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CSV_OUT_DIR / f"{type_name}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=seen_keys,
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    return {
        "type": type_name,
        "rows": len(rows),
        "columns": len(seen_keys),
        "output": str(out_path.relative_to(REPO_ROOT)),
    }


# ---------------------------------------------------------------------------
# Part 2 — NSQ API JSON → CSV
# ---------------------------------------------------------------------------
def export_api_json():
    """Convert the NSQ API JSON files to CSV."""
    results = []

    if not API_JSON_DIR.is_dir():
        print(f"[!] API JSON dir not found: {API_JSON_DIR}")
        return results

    API_CSV_DIR.mkdir(parents=True, exist_ok=True)

    for json_file in sorted(API_JSON_DIR.glob("*.json")):
        if json_file.name.startswith("_"):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[!] {json_file.name}: parse failed: {exc}")
            continue

        # Expecting list of dicts
        if not isinstance(data, list):
            print(f"[!] {json_file.name}: not a list — skipping")
            continue

        if not data:
            print(f"[*] {json_file.name}: empty")
            continue

        # Union of keys
        seen_keys: list[str] = []
        seen_set: set[str] = set()
        for r in data:
            if not isinstance(r, dict):
                continue
            for k in r.keys():
                if k not in seen_set:
                    seen_keys.append(k)
                    seen_set.add(k)

        out_path = API_CSV_DIR / f"{json_file.stem}.csv"
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=seen_keys,
                               extrasaction="ignore")
            w.writeheader()
            for r in data:
                if isinstance(r, dict):
                    w.writerow(r)

        results.append({
            "source_json": json_file.name,
            "rows": len(data),
            "columns": len(seen_keys),
            "output": str(out_path.relative_to(REPO_ROOT)),
        })

    return results


# ---------------------------------------------------------------------------
def main():
    print(f"[*] Exporting structured_raw types → CSV")
    print(f"[*] Output: {CSV_OUT_DIR}")
    print()

    struct_results = []
    for type_dir in sorted(STRUCTURED.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("_"):
            continue
        if type_dir.name == "csv":
            continue
        r = export_structured_type(type_dir)
        struct_results.append(r)
        if r["rows"]:
            print(f"    {r['type']:<20} rows={r['rows']:>5} "
                  f"cols={r['columns']:>3}  {r['output']}")

    print()
    print(f"[*] Exporting NSQ API JSON → CSV")
    print(f"[*] Output: {API_CSV_DIR}")
    print()
    api_results = export_api_json()
    for r in api_results:
        print(f"    {r['source_json']:<45} rows={r['rows']:>6} "
              f"cols={r['columns']:>3}")

    print()
    print("=" * 82)
    print("CSV EXPORT COMPLETE")
    print("=" * 82)
    total_struct = sum(r["rows"] for r in struct_results)
    total_api = sum(r["rows"] for r in api_results)
    print(f"  Structured types   : {len(struct_results)}")
    print(f"  Structured rows    : {total_struct}")
    print(f"  API JSON files     : {len(api_results)}")
    print(f"  API rows           : {total_api}")
    print()
    print(f"  Structured CSVs    : {CSV_OUT_DIR}/<type>.csv")
    print(f"  API CSVs           : {API_CSV_DIR}/<name>.csv")


if __name__ == "__main__":
    main()