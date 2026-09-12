#!/usr/bin/env python3
"""
Extract raw text + tables from TEXT-type PDFs.

Source of truth for "which PDFs are text":
    downloads/_analysis/pdf_analysis.csv  (status column)

Inputs:
    downloads/<source>/important/<file>.pdf

Outputs:
    raw_extraction/text/<source>/<file>.txt             - page-marked plain text
    raw_extraction/text/<source>/<file>.tables.json     - tables per page
    raw_extraction/text/<source>/_manifest.json         - per-source manifest
    raw_extraction/text/_manifest.json                  - global manifest

Idempotent: a PDF is skipped if both outputs already exist (unless --force).

Usage:
    python raw_extraction/extract_text.py
    python raw_extraction/extract_text.py --statuses TEXT MIXED
    python raw_extraction/extract_text.py --sources alerts fdc
    python raw_extraction/extract_text.py --force
    python raw_extraction/extract_text.py --scan-all        # ignore analysis CSV
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
RAW_ROOT = THIS_FILE.parent                     # raw_extraction/
REPO_ROOT = RAW_ROOT.parent                     # repo root
DOWNLOADS = REPO_ROOT / "downloads"
ANALYSIS_CSV = DOWNLOADS / "_analysis" / "pdf_analysis.csv"
OUTPUT_ROOT = RAW_ROOT / "text"

PAGE_MARKER = "===== PAGE {n} ====="


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Target discovery
# ---------------------------------------------------------------------------
def load_targets_from_csv(
    csv_path: Path,
    allowed_statuses: set[str],
    only_sources: set[str] | None = None,
) -> list[dict]:
    """Parse pdf_analysis.csv → list of {source, filename, status}."""
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    targets: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

        required = {"source", "filename", "status"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"CSV missing required column(s): {sorted(missing)}"
            )

        for row in reader:
            status = (row.get("status") or "").strip().upper()
            if status not in allowed_statuses:
                continue
            source = (row.get("source") or "").strip()
            filename = (row.get("filename") or "").strip()
            if not source or not filename:
                continue
            if only_sources and source not in only_sources:
                continue
            targets.append({
                "source": source,
                "filename": filename,
                "status": status,
            })
    return targets


def discover_all_pdfs(only_sources: set[str] | None = None) -> list[dict]:
    """Fallback: every PDF under downloads/<source>/important/."""
    targets: list[dict] = []
    if not DOWNLOADS.is_dir():
        return targets
    for source_dir in sorted(DOWNLOADS.iterdir()):
        if not source_dir.is_dir() or source_dir.name.startswith("_"):
            continue
        if only_sources and source_dir.name not in only_sources:
            continue
        imp_dir = source_dir / "important"
        if not imp_dir.is_dir():
            continue
        for pdf in sorted(imp_dir.glob("*.pdf")):
            targets.append({
                "source": source_dir.name,
                "filename": pdf.name,
                "status": "UNKNOWN",
            })
    return targets


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def extract_pdf_text(pdf_path: Path) -> tuple[str, int]:
    """Extract text with page markers. Return (text, page_count)."""
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        chunks: list[str] = []
        for i in range(page_count):
            page = doc.load_page(i)
            raw = page.get_text("text") or ""
            # Preserve internal indentation but strip trailing spaces per line
            cleaned = "\n".join(line.rstrip() for line in raw.splitlines())
            chunks.append(PAGE_MARKER.format(n=i + 1))
            chunks.append(cleaned)
            chunks.append("")  # blank line between pages

    text = "\n".join(chunks).rstrip() + "\n"
    return text, page_count


def extract_pdf_tables(pdf_path: Path) -> list[dict]:
    """Extract tables using PyMuPDF's find_tables()."""
    tables_out: list[dict] = []

    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            try:
                finder = page.find_tables()
            except Exception:
                continue

            for tbl in getattr(finder, "tables", []):
                try:
                    rows = tbl.extract()
                except Exception:
                    rows = []

                cleaned: list[list[str]] = []
                for row in rows or []:
                    cleaned.append([
                        (c.strip() if isinstance(c, str) else "")
                        for c in row
                    ])

                tables_out.append({
                    "page": i + 1,
                    "bbox": [round(v, 2) for v in tbl.bbox],
                    "n_rows": len(cleaned),
                    "n_cols": max((len(r) for r in cleaned), default=0),
                    "rows": cleaned,
                })

    return tables_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract raw text + tables from TEXT-type PDFs."
    )
    ap.add_argument(
        "--statuses", nargs="+", default=["TEXT"],
        help="Analysis statuses to process (default: TEXT). "
             "Try: --statuses TEXT MIXED",
    )
    ap.add_argument(
        "--sources", nargs="+", default=None,
        help="Only process these source folders.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Re-extract even if outputs already exist.",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N PDFs (for smoke testing).",
    )
    ap.add_argument(
        "--scan-all", action="store_true",
        help="Ignore pdf_analysis.csv and process every PDF in important/.",
    )
    args = ap.parse_args()

    allowed = {s.upper() for s in args.statuses}
    only_sources = set(args.sources) if args.sources else None

    # --- Build target list ---
    if args.scan_all:
        print("[*] --scan-all: ignoring analysis CSV, walking filesystem")
        targets = discover_all_pdfs(only_sources)
    else:
        if not ANALYSIS_CSV.exists():
            print(f"[!] Analysis CSV not found: {ANALYSIS_CSV}")
            print("    Run analyze_pdfs.py first, or pass --scan-all.")
            sys.exit(1)
        targets = load_targets_from_csv(ANALYSIS_CSV, allowed, only_sources)

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("[!] No matching PDFs found. Nothing to do.")
        sys.exit(0)

    print(f"[*] Repo root        : {REPO_ROOT}")
    print(f"[*] Output root      : {OUTPUT_ROOT}")
    print(f"[*] Statuses         : {sorted(allowed)}")
    print(f"[*] Targets          : {len(targets)} PDFs")
    print()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    per_source_stats: dict[str, dict] = defaultdict(lambda: {
        "total_pdfs": 0,
        "extracted": 0,
        "skipped": 0,
        "errors": 0,
        "total_chars": 0,
        "total_tables": 0,
        "files": [],
    })

    started = time.time()

    for t in tqdm(targets, desc="Extracting", unit="pdf"):
        source = t["source"]
        filename = t["filename"]
        pdf_path = DOWNLOADS / source / "important" / filename

        stats = per_source_stats[source]
        stats["total_pdfs"] += 1

        if not pdf_path.exists():
            stats["errors"] += 1
            stats["files"].append({
                "pdf": filename,
                "status": "missing",
                "err": "PDF not found on disk",
            })
            continue

        stem = pdf_path.stem
        src_out_dir = OUTPUT_ROOT / source
        txt_path = src_out_dir / f"{stem}.txt"
        tbl_path = src_out_dir / f"{stem}.tables.json"

        # ---- Skip if already done ----
        if not args.force and txt_path.exists() and tbl_path.exists():
            try:
                chars = len(txt_path.read_text(encoding="utf-8"))
                n_tables = len(json.loads(
                    tbl_path.read_text(encoding="utf-8")
                ))
            except Exception:
                chars, n_tables = 0, 0

            stats["skipped"] += 1
            stats["total_chars"] += chars
            stats["total_tables"] += n_tables
            stats["files"].append({
                "pdf": filename,
                "status": "skipped",
                "chars": chars,
                "tables": n_tables,
                "txt": str(txt_path.relative_to(OUTPUT_ROOT)),
                "tables_json": str(tbl_path.relative_to(OUTPUT_ROOT)),
            })
            continue

        # ---- Extract ----
        try:
            text, page_count = extract_pdf_text(pdf_path)
            tables = extract_pdf_tables(pdf_path)

            src_out_dir.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(text, encoding="utf-8")
            tbl_path.write_text(
                json.dumps(tables, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            stats["extracted"] += 1
            stats["total_chars"] += len(text)
            stats["total_tables"] += len(tables)
            stats["files"].append({
                "pdf": filename,
                "status": "ok",
                "pages": page_count,
                "chars": len(text),
                "tables": len(tables),
                "txt": str(txt_path.relative_to(OUTPUT_ROOT)),
                "tables_json": str(tbl_path.relative_to(OUTPUT_ROOT)),
                "extracted_at": utcnow_iso(),
            })

        except Exception as exc:
            stats["errors"] += 1
            stats["files"].append({
                "pdf": filename,
                "status": "error",
                "err": str(exc),
            })

    # ---------- Write per-source manifests + global manifest ----------
    generated_at = utcnow_iso()

    global_summary = {
        "generated_at": generated_at,
        "analysis_csv": (
            str(ANALYSIS_CSV.relative_to(REPO_ROOT))
            if ANALYSIS_CSV.exists() else None
        ),
        "statuses_processed": sorted(allowed),
        "scan_all": args.scan_all,
        "sources": {},
        "totals": {
            "total_pdfs": 0,
            "extracted": 0,
            "skipped": 0,
            "errors": 0,
            "total_chars": 0,
            "total_tables": 0,
        },
    }

    for source, stats in sorted(per_source_stats.items()):
        src_dir = OUTPUT_ROOT / source
        src_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "source": source,
            "generated_at": generated_at,
            "total_pdfs": stats["total_pdfs"],
            "extracted": stats["extracted"],
            "skipped": stats["skipped"],
            "errors": stats["errors"],
            "total_chars": stats["total_chars"],
            "total_tables": stats["total_tables"],
            "files": stats["files"],
        }
        (src_dir / "_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        global_summary["sources"][source] = {
            "total_pdfs": stats["total_pdfs"],
            "extracted": stats["extracted"],
            "skipped": stats["skipped"],
            "errors": stats["errors"],
            "total_chars": stats["total_chars"],
            "total_tables": stats["total_tables"],
            "manifest_file": f"{source}/_manifest.json",
        }
        for k in global_summary["totals"]:
            global_summary["totals"][k] += stats.get(k, 0)

    (OUTPUT_ROOT / "_manifest.json").write_text(
        json.dumps(global_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---------- Console summary ----------
    elapsed = time.time() - started
    print()
    print("=" * 82)
    print(f"EXTRACTION COMPLETE   ({elapsed:.1f}s)")
    print("=" * 82)
    print(
        f"{'SOURCE':<18} {'TOTAL':>6} {'OK':>6} {'SKIP':>6} "
        f"{'ERR':>5} {'CHARS':>10} {'TABLES':>7}"
    )
    print("-" * 82)
    for source in sorted(per_source_stats.keys()):
        s = per_source_stats[source]
        print(
            f"{source:<18} {s['total_pdfs']:>6} {s['extracted']:>6} "
            f"{s['skipped']:>6} {s['errors']:>5} "
            f"{s['total_chars']:>10} {s['total_tables']:>7}"
        )
    print("-" * 82)
    t = global_summary["totals"]
    print(
        f"{'TOTAL':<18} {t['total_pdfs']:>6} {t['extracted']:>6} "
        f"{t['skipped']:>6} {t['errors']:>5} "
        f"{t['total_chars']:>10} {t['total_tables']:>7}"
    )
    print()
    print(f"[+] Global manifest : {OUTPUT_ROOT / '_manifest.json'}")
    print(f"[+] Per-source      : {OUTPUT_ROOT}/<source>/_manifest.json")


if __name__ == "__main__":
    main()