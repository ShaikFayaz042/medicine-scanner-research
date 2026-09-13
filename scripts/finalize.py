#!/usr/bin/env python3
"""
Finalize the raw extraction dataset.

Phases:
    4. Master manifest + unified exports
         structured_raw/_master.json          — index of all types
         structured_raw/_all_documents.json   — every doc, unified
         structured_raw/_all_records.ndjson   — every record, streamable

    5. Validation
         structured_raw/_validation.json       — coverage + integrity
         structured_raw/_validation.txt        — human-readable report

    6. Freeze
         structured_raw/_VERSION.json          — version, counts, checksums
         structured_raw/README.md              — dataset overview

Usage:
    python scripts/finalize.py
    python scripts/finalize.py --version 0.1.0
"""

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
REPO_ROOT = SCRIPTS_DIR.parent
STRUCTURED = REPO_ROOT / "structured_raw"
DOWNLOADS = REPO_ROOT / "downloads"
ANALYSIS_CSV = DOWNLOADS / "_analysis" / "pdf_analysis.csv"

# Type folder → record_type
TYPE_FOLDERS = [
    "nsq", "spurious", "drug_alert",
    "fdc_prohibited", "fdc_notification",
    "gazette_legal", "pvpi_safety",
    "theft_recall", "medical_device",
    "ivd_alert", "circular", "guideline",
    "other",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Load all structured outputs
# ---------------------------------------------------------------------------
def load_all_docs() -> tuple[list[dict], dict[str, dict]]:
    """Return (all_docs, per_type_summary)."""
    all_docs: list[dict] = []
    per_type: dict[str, dict] = {}

    for type_name in TYPE_FOLDERS:
        type_dir = STRUCTURED / type_name
        if not type_dir.is_dir():
            per_type[type_name] = {"count": 0, "records": 0, "files": []}
            continue

        manifest_path = type_dir / "_manifest.json"
        if not manifest_path.exists():
            per_type[type_name] = {"count": 0, "records": 0, "files": []}
            continue

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        docs_meta = manifest.get("documents", [])

        type_count = 0
        type_records = 0
        files_loaded = []

        for meta in docs_meta:
            if meta.get("status") not in ("SUCCESS", "skipped", "EMPTY"):
                continue
            doc_id = meta.get("document_id")
            filename = meta.get("filename")
            if not doc_id or not filename:
                continue
            stem = Path(filename).stem
            doc_path = type_dir / f"{stem}.json"
            if not doc_path.exists():
                continue
            try:
                data = json.loads(doc_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            doc_entry = {
                "type": type_name,
                "document_id": doc_id,
                "source_file": filename,
                "content_type": data.get("document", {}).get("content_type"),
                "text_origin": data.get("document", {}).get("text_origin"),
                "sources": data.get("document", {}).get("sources", []),
                "pdf_paths": data.get("document", {}).get("pdf_paths", []),
                "extraction_method": data.get("extraction", {}).get("extraction_method"),
                "records_count": len(data.get("records", [])),
                "extraction_path": str(doc_path.relative_to(REPO_ROOT)),
                "sha256": hashlib.sha256(
                    doc_path.read_bytes()
                ).hexdigest()[:16],
            }
            all_docs.append(doc_entry)
            type_count += 1
            type_records += doc_entry["records_count"]
            files_loaded.append(doc_entry)

        per_type[type_name] = {
            "count": type_count,
            "records": type_records,
            "files": files_loaded,
        }

    return all_docs, per_type


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def load_analysis_csv():
    rows = []
    with ANALYSIS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        import csv
        reader = csv.DictReader(fh)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        for r in reader:
            rows.append(r)
    return rows


def run_validation(all_docs, per_type):
    """Cross-cutting checks."""
    report = {
        "generated_at": utcnow(),
        "coverage": {},
        "duplicates": {},
        "schema": {},
        "totals": {},
    }

    # --- Coverage: every important PDF in analysis CSV has an output? ---
    analysis = load_analysis_csv()
    important_pdfs = [
        r for r in analysis
        if (r.get("status") or "").upper() in ("TEXT", "SCANNED", "MIXED")
    ]
    # unique by filename
    seen_filenames = set()
    unique_important = []
    for r in important_pdfs:
        fn = (r.get("filename") or "").strip()
        if not fn or fn in seen_filenames:
            continue
        seen_filenames.add(fn)
        unique_important.append(fn)

    output_filenames = {d["source_file"] for d in all_docs}
    missing = sorted(set(unique_important) - output_filenames)
    covered = len(unique_important) - len(missing)

    report["coverage"] = {
        "important_pdfs_total": len(unique_important),
        "covered": covered,
        "missing": len(missing),
        "coverage_pct": round(100.0 * covered / max(1, len(unique_important)), 2),
        "missing_files": missing[:50],
    }

    # --- Duplicates across types ---
    by_stem: dict[str, list[str]] = defaultdict(list)
    for d in all_docs:
        stem = Path(d["source_file"]).stem
        by_stem[stem].append(d["type"])
    cross_type_dupes = {
        k: v for k, v in by_stem.items() if len(v) > 1
    }
    report["duplicates"] = {
        "cross_type_count": len(cross_type_dupes),
        "sample": dict(list(cross_type_dupes.items())[:10]),
    }

    # --- Schema consistency: every doc has the wrapper keys ---
    bad_schema = []
    for d in all_docs:
        path = REPO_ROOT / d["extraction_path"]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            bad_schema.append({"path": d["extraction_path"], "reason": "unreadable"})
            continue
        for key in ("document", "extraction", "validation", "records"):
            if key not in data:
                bad_schema.append({
                    "path": d["extraction_path"],
                    "reason": f"missing key '{key}'",
                })
                break
    report["schema"] = {
        "checked": len(all_docs),
        "bad_count": len(bad_schema),
        "bad": bad_schema[:20],
    }

    # --- Totals ---
    report["totals"] = {
        "types": len(per_type),
        "documents": len(all_docs),
        "records": sum(d["records_count"] for d in all_docs),
        "per_type": {
            k: {"docs": v["count"], "records": v["records"]}
            for k, v in per_type.items()
        },
    }

    return report


def write_validation_report(report, out_dir: Path):
    # JSON
    (out_dir / "_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Text
    lines = []
    lines.append("=" * 78)
    lines.append("RAW EXTRACTION DATASET — VALIDATION REPORT")
    lines.append("=" * 78)
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")
    lines.append("COVERAGE")
    lines.append("-" * 78)
    c = report["coverage"]
    lines.append(f"  Important PDFs (unique)  : {c['important_pdfs_total']}")
    lines.append(f"  Covered by extraction    : {c['covered']}")
    lines.append(f"  Missing                  : {c['missing']}")
    lines.append(f"  Coverage %               : {c['coverage_pct']}%")
    if c["missing_files"]:
        lines.append(f"  First missing files:")
        for f in c["missing_files"][:10]:
            lines.append(f"    - {f}")
    lines.append("")
    lines.append("DUPLICATES (same filename, multiple types)")
    lines.append("-" * 78)
    lines.append(f"  Count: {report['duplicates']['cross_type_count']}")
    lines.append("")
    lines.append("SCHEMA CONSISTENCY")
    lines.append("-" * 78)
    s = report["schema"]
    lines.append(f"  Documents checked: {s['checked']}")
    lines.append(f"  Malformed        : {s['bad_count']}")
    lines.append("")
    lines.append("TOTALS")
    lines.append("-" * 78)
    lines.append(f"  Types    : {report['totals']['types']}")
    lines.append(f"  Documents: {report['totals']['documents']}")
    lines.append(f"  Records  : {report['totals']['records']}")
    lines.append("")
    lines.append(f"  {'TYPE':<20} {'DOCS':>6} {'RECORDS':>10}")
    lines.append("  " + "-" * 40)
    for t, stats in sorted(report["totals"]["per_type"].items()):
        lines.append(f"  {t:<20} {stats['docs']:>6} {stats['records']:>10}")
    lines.append("=" * 78)
    (out_dir / "_validation.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Unified exports
# ---------------------------------------------------------------------------
def build_unified_exports(all_docs, per_type, out_dir: Path):
    master = {
        "generated_at": utcnow(),
        "types": {
            t: {
                "docs": s["count"],
                "records": s["records"],
            }
            for t, s in per_type.items()
        },
        "total_docs": len(all_docs),
        "total_records": sum(d["records_count"] for d in all_docs),
    }
    (out_dir / "_master.json").write_text(
        json.dumps(master, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # All docs, unified index
    (out_dir / "_all_documents.json").write_text(
        json.dumps(all_docs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # NDJSON of every record across all types (streamable)
    ndjson_path = out_dir / "_all_records.ndjson"
    count = 0
    with ndjson_path.open("w", encoding="utf-8") as fh:
        for d in all_docs:
            path = REPO_ROOT / d["extraction_path"]
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for rec in data.get("records", []):
                flat = {
                    "_type": d["type"],
                    "_doc_id": d["document_id"],
                    "_source_file": d["source_file"],
                    "record": rec,
                }
                fh.write(json.dumps(flat, ensure_ascii=False) + "\n")
                count += 1
    return count


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------
def freeze(out_dir: Path, all_docs, validation, version: str):
    """Write VERSION.json + README.md with checksums."""
    # Compute checksums of key files
    files_to_hash = [
        "_master.json",
        "_all_documents.json",
        "_all_records.ndjson",
        "_validation.json",
    ]
    hashes = {}
    for name in files_to_hash:
        p = out_dir / name
        if p.exists():
            hashes[name] = {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }

    version_data = {
        "dataset_version": version,
        "frozen_at": utcnow(),
        "total_docs": len(all_docs),
        "total_records": validation["totals"]["records"],
        "per_type": validation["totals"]["per_type"],
        "checksums": hashes,
    }
    (out_dir / "_VERSION.json").write_text(
        json.dumps(version_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # README
    readme = []
    readme.append(f"# Structured Raw Dataset — v{version}")
    readme.append("")
    readme.append(f"**Frozen:** {version_data['frozen_at']}")
    readme.append(f"**Docs:** {len(all_docs)}  **Records:** {validation['totals']['records']}")
    readme.append("")
    readme.append("## Folders")
    readme.append("")
    for t, stats in sorted(validation["totals"]["per_type"].items()):
        readme.append(f"- `{t}/` — {stats['docs']} docs, {stats['records']} records")
    readme.append("")
    readme.append("## Files")
    readme.append("")
    readme.append("| File | Purpose |")
    readme.append("|---|---|")
    readme.append("| `_master.json` | Type-level summary |")
    readme.append("| `_all_documents.json` | Flat index of every document |")
    readme.append("| `_all_records.ndjson` | Every record as NDJSON (streamable) |")
    readme.append("| `_validation.json` | Coverage + integrity report |")
    readme.append("| `_VERSION.json` | Dataset version + checksums |")
    readme.append("")
    readme.append("## Schema")
    readme.append("")
    readme.append("Every document JSON follows:")
    readme.append("```")
    readme.append("{")
    readme.append('  "document":   { document_id, source_file, document_type, ... },')
    readme.append('  "extraction": { extraction_method, status, raw_stats },')
    readme.append('  "validation": { records_extracted, ... },')
    readme.append('  "records":    [ { record_type, raw_data, canonical }, ... ]')
    readme.append("}")
    readme.append("```")
    readme.append("")
    readme.append("**RAW — no normalization.** All dates, names, and values are as-is from source.")

    (out_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Finalize structured_raw dataset.")
    ap.add_argument("--version", default="0.1.0",
                    help="Dataset version label (default 0.1.0)")
    args = ap.parse_args()

    if not STRUCTURED.is_dir():
        print(f"[!] Not found: {STRUCTURED}")
        return

    started = time.time()
    print(f"[*] Scanning {STRUCTURED} ...")

    all_docs, per_type = load_all_docs()
    print(f"[*] Loaded {len(all_docs)} document outputs")
    for t, s in per_type.items():
        print(f"    {t:<20} docs={s['count']:>4}  records={s['records']:>5}")

    print()
    print("[*] Running validation ...")
    validation = run_validation(all_docs, per_type)
    write_validation_report(validation, STRUCTURED)

    print("[*] Building unified exports ...")
    ndjson_count = build_unified_exports(all_docs, per_type, STRUCTURED)
    print(f"    NDJSON records: {ndjson_count}")

    print("[*] Freezing dataset ...")
    freeze(STRUCTURED, all_docs, validation, args.version)

    elapsed = time.time() - started

    # Summary
    print()
    print("=" * 78)
    print(f"FINALIZE COMPLETE  ({elapsed:.1f}s)")
    print("=" * 78)
    print(f"  Types      : {validation['totals']['types']}")
    print(f"  Documents  : {validation['totals']['documents']}")
    print(f"  Records    : {validation['totals']['records']}")
    print(f"  Coverage   : {validation['coverage']['coverage_pct']}%")
    print(f"  Missing    : {validation['coverage']['missing']}")
    print(f"  Version    : {args.version}")
    print()
    print(f"[+] Master    : {STRUCTURED}/_master.json")
    print(f"[+] Validation: {STRUCTURED}/_validation.json")
    print(f"[+] Version   : {STRUCTURED}/_VERSION.json")
    print(f"[+] README    : {STRUCTURED}/README.md")


if __name__ == "__main__":
    main()