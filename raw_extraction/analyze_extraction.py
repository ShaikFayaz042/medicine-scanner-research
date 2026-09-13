#!/usr/bin/env python3
"""
Diagnostic analysis of text extraction results.

Reads:
    raw_extraction/text/<source>/_manifest.json      (from extract_text.py)
    raw_extraction/text/<source>/<name>.txt
    raw_extraction/text/<source>/<name>.tables.json

Produces:
    raw_extraction/_analysis/extraction_report.txt   (human-readable)
    raw_extraction/_analysis/extraction_metrics.csv  (per-PDF metrics)
    raw_extraction/_analysis/extraction_anomalies.csv (flagged PDFs)

Flags per PDF:
    EMPTY_TXT        chars/page  < 100   → suspicious, probably failed extract
    DENSE_TXT        chars/page  > 10000 → possible duplication
    TABLE_SPAM       tables/page > 5     → probable false-positive tables
    TABLE_DROUGHT    >=5 pages and 0 tables → possible missed tables
    REPEATED_LINES   > 30% of non-empty lines are duplicates
    TINY_TABLE_MEAN  avg table rows < 2  → useless / header-only tables

Usage:
    python raw_extraction/analyze_extraction.py
    python raw_extraction/analyze_extraction.py --sample 5
    python raw_extraction/analyze_extraction.py --show-samples
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

THIS = Path(__file__).resolve()
RAW_ROOT = THIS.parent
TEXT_ROOT = RAW_ROOT / "text"
OUT_DIR = RAW_ROOT / "_analysis"

# --- Thresholds (tune here) ---
MIN_CHARS_PER_PAGE = 100
MAX_CHARS_PER_PAGE = 10_000
MAX_TABLES_PER_PAGE = 5
REPEAT_LINE_RATIO = 0.30
MIN_AVG_TABLE_ROWS = 2

NONEMPTY_LINE = re.compile(r"\S")


# ---------------------------------------------------------------------------
def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_manifests() -> list[dict]:
    entries = []
    for mf in sorted(TEXT_ROOT.glob("*/_manifest.json")):
        source = mf.parent.name
        data = json.loads(mf.read_text(encoding="utf-8"))
        for f in data.get("files", []):
            if f.get("status") not in ("ok", "skipped"):
                continue
            entries.append({"source": source, **f})
    return entries


def read_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_tables(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def repeated_line_ratio(text: str) -> float:
    """Fraction of non-empty lines that are duplicates of earlier lines."""
    lines = [ln.strip() for ln in text.splitlines()]
    nonempty = [ln for ln in lines if ln and not ln.startswith("===== PAGE")]
    if len(nonempty) < 5:
        return 0.0
    counts = Counter(nonempty)
    repeats = sum(c - 1 for c in counts.values() if c > 1)
    return repeats / len(nonempty)


def analyse_one(entry: dict) -> dict:
    source = entry["source"]
    txt_rel = entry.get("txt", "")
    tbl_rel = entry.get("tables_json", "")
    txt_path = TEXT_ROOT / txt_rel if txt_rel else None
    tbl_path = TEXT_ROOT / tbl_rel if tbl_rel else None

    text = read_txt(txt_path) if txt_path else ""
    tables = read_tables(tbl_path) if tbl_path else []

    pages = entry.get("pages") or 1
    chars = len(text)
    n_tables = len(tables)
    table_rows = [t.get("n_rows", 0) for t in tables if isinstance(t, dict)]
    avg_rows = (sum(table_rows) / len(table_rows)) if table_rows else 0.0

    chars_per_page = chars / pages if pages else 0.0
    tables_per_page = n_tables / pages if pages else 0.0
    repeat_ratio = repeated_line_ratio(text)

    flags = []
    if chars_per_page < MIN_CHARS_PER_PAGE:
        flags.append("EMPTY_TXT")
    if chars_per_page > MAX_CHARS_PER_PAGE:
        flags.append("DENSE_TXT")
    if tables_per_page > MAX_TABLES_PER_PAGE:
        flags.append("TABLE_SPAM")
    if pages >= 5 and n_tables == 0:
        flags.append("TABLE_DROUGHT")
    if repeat_ratio > REPEAT_LINE_RATIO:
        flags.append("REPEATED_LINES")
    if n_tables > 0 and avg_rows < MIN_AVG_TABLE_ROWS:
        flags.append("TINY_TABLE_MEAN")

    return {
        "source": source,
        "pdf": entry["pdf"],
        "pages": pages,
        "chars": chars,
        "tables": n_tables,
        "avg_table_rows": round(avg_rows, 2),
        "chars_per_page": round(chars_per_page, 1),
        "tables_per_page": round(tables_per_page, 2),
        "repeat_ratio": round(repeat_ratio, 3),
        "flags": ",".join(flags),
        "txt_rel": txt_rel,
        "tbl_rel": tbl_rel,
    }


# ---------------------------------------------------------------------------
def print_summary(metrics: list[dict]) -> None:
    print("=" * 92)
    print("TEXT EXTRACTION DIAGNOSTIC")
    print("=" * 92)
    print(f"Generated : {utcnow()}")
    print(f"PDFs      : {len(metrics)}")
    print()

    by_source: dict[str, list[dict]] = defaultdict(list)
    for m in metrics:
        by_source[m["source"]].append(m)

    hdr = (
        f"{'SOURCE':<18} {'N':>4} {'PAGES':>7} {'CHARS':>10} "
        f"{'CHAR/PG':>8} {'TBL':>5} {'TBL/PG':>7} {'FLAGGED':>8}"
    )
    print(hdr)
    print("-" * len(hdr))

    for source in sorted(by_source):
        rows = by_source[source]
        n = len(rows)
        pages = sum(r["pages"] for r in rows)
        chars = sum(r["chars"] for r in rows)
        tables = sum(r["tables"] for r in rows)
        cpp = chars / pages if pages else 0
        tpp = tables / pages if pages else 0
        flagged = sum(1 for r in rows if r["flags"])
        print(
            f"{source:<18} {n:>4} {pages:>7} {chars:>10} "
            f"{cpp:>8.0f} {tables:>5} {tpp:>7.2f} {flagged:>8}"
        )

    print("-" * len(hdr))

    # Flag tally
    flag_counts = Counter()
    for m in metrics:
        for f in m["flags"].split(",") if m["flags"] else []:
            flag_counts[f] += 1

    if flag_counts:
        print()
        print("FLAG TALLY")
        print("-" * 40)
        for flag, count in flag_counts.most_common():
            print(f"  {flag:<20} {count:>5}")
    else:
        print("\n✅ No anomalies detected.")


def print_samples(metrics: list[dict], n: int) -> None:
    print()
    print("=" * 92)
    print(f"SAMPLES ({n} random PDFs)")
    print("=" * 92)

    sample = random.sample(metrics, min(n, len(metrics)))
    for m in sample:
        txt_path = TEXT_ROOT / m["txt_rel"]
        text = read_txt(txt_path)
        head = "\n".join(text.splitlines()[:25])

        print()
        print(f"── {m['source']} / {m['pdf']}")
        print(
            f"   pages={m['pages']} chars={m['chars']} "
            f"tables={m['tables']} char/pg={m['chars_per_page']}"
        )
        if m["flags"]:
            print(f"   ⚠ flags: {m['flags']}")
        print("   " + "-" * 72)
        for line in head.splitlines():
            print(f"   | {line}")
        print("   " + "-" * 72)


def write_csv(metrics: list[dict], path: Path) -> None:
    fields = [
        "source", "pdf", "pages", "chars", "tables", "avg_table_rows",
        "chars_per_page", "tables_per_page", "repeat_ratio", "flags",
        "txt_rel", "tbl_rel",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for m in metrics:
            w.writerow({k: m.get(k, "") for k in fields})


def write_anomalies(metrics: list[dict], path: Path) -> None:
    flagged = [m for m in metrics if m["flags"]]
    fields = [
        "source", "pdf", "pages", "chars", "tables", "avg_table_rows",
        "chars_per_page", "tables_per_page", "repeat_ratio", "flags",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for m in sorted(flagged, key=lambda x: (x["source"], x["pdf"])):
            w.writerow({k: m.get(k, "") for k in fields})


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=3,
                    help="How many random PDFs to print snippets for.")
    ap.add_argument("--show-samples", action="store_true",
                    help="Print random samples (default: yes).")
    ap.add_argument("--no-samples", action="store_true",
                    help="Skip sample printing.")
    args = ap.parse_args()

    if not TEXT_ROOT.is_dir():
        print(f"[!] Not found: {TEXT_ROOT}")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    entries = load_manifests()
    if not entries:
        print("[!] No manifest entries found.")
        sys.exit(1)

    print(f"[*] Analysing {len(entries)} manifest entries...")

    metrics = [analyse_one(e) for e in entries]

    print_summary(metrics)

    if not args.no_samples:
        print_samples(metrics, args.sample)

    # Save outputs
    write_csv(metrics, OUT_DIR / "extraction_metrics.csv")
    write_anomalies(metrics, OUT_DIR / "extraction_anomalies.csv")

    print()
    print(f"[+] Full metrics  : {OUT_DIR / 'extraction_metrics.csv'}")
    print(f"[+] Anomalies     : {OUT_DIR / 'extraction_anomalies.csv'}")


if __name__ == "__main__":
    main()