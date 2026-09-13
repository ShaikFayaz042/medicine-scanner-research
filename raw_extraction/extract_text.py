#!/usr/bin/env python3
"""
Extract raw text + tables from TEXT-type PDFs.

pymupdf_layout integration
--------------------------
If `pymupdf-layout` is installed, PyMuPDF automatically upgrades
`find_tables()` and layout analysis — no code changes needed.
Install once:  pip install pymupdf-layout

This script detects it and logs the status in the banner and manifest.

Source of truth for "which PDFs are text":
    downloads/_analysis/pdf_analysis.csv  (status column)

Inputs:
    downloads/<source>/important/<file>.pdf

Outputs (per PDF):
    raw_extraction/text/<source>/<name>.txt           - plain text, page-marked
    raw_extraction/text/<source>/<name>.tables.json   - structured tables
    raw_extraction/text/<source>/<name>.md            - Markdown (if pymupdf4llm)
    raw_extraction/text/<source>/_manifest.json       - per-source manifest
    raw_extraction/text/_manifest.json                - global manifest

Usage:
    python raw_extraction/extract_text.py
    python raw_extraction/extract_text.py --statuses TEXT MIXED
    python raw_extraction/extract_text.py --sources alerts fdc
    python raw_extraction/extract_text.py --skip-existing
    python raw_extraction/extract_text.py --no-pdfplumber
    python raw_extraction/extract_text.py --no-md
"""

import argparse
import csv
import importlib.util
import json
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import pymupdf4llm
    HAS_PYMUPDF4LLM = True
except ImportError:
    HAS_PYMUPDF4LLM = False

try:
    import pymupdf.layout  # noqa: F401  (PyMuPDF layout namespace from pymupdf-layout)
    HAS_PYMUPDF_LAYOUT = True
except Exception:
    HAS_PYMUPDF_LAYOUT = False

# Check the actual installed package path without assuming a top-level module name.
try:
    import pymupdf  # noqa: F401
    PYMUPDF_LAYOUT_SPEC = importlib.util.find_spec("pymupdf.layout") is not None
except Exception:
    PYMUPDF_LAYOUT_SPEC = False

from tqdm import tqdm


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
RAW_ROOT = THIS_FILE.parent
REPO_ROOT = RAW_ROOT.parent
DOWNLOADS = REPO_ROOT / "downloads"
ANALYSIS_CSV = DOWNLOADS / "_analysis" / "pdf_analysis.csv"
OUTPUT_ROOT = RAW_ROOT / "text"

PAGE_MARKER = "===== PAGE {n} ====="

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
Y_TOLERANCE_RATIO = 0.6
COLUMN_GAP_RATIO = 1.5
MIN_CHARS_FOR_TAB = 3
MIN_AVG_LINE_LEN = 20
MIN_LINES_FOR_CHECK = 15
MIN_TABLE_ROWS = 3
MIN_TABLE_COLS = 2

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


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
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    targets: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

        required = {"source", "filename", "status"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV missing columns: {sorted(missing)}")

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


# ===========================================================================
# TEXT extraction
# ===========================================================================
def _word_reconstruct_page(page) -> str:
    """Rebuild a page's text from words (visual reading order)."""
    try:
        words = page.get_text("words", sort=True)
    except Exception:
        return ""

    words = [w for w in words if w[4].strip()]
    if not words:
        return ""

    heights = sorted((w[3] - w[1]) for w in words if (w[3] - w[1]) > 0)
    median_h = heights[len(heights) // 2] if heights else 10.0
    y_tol = max(1.5, median_h * Y_TOLERANCE_RATIO)

    char_widths = []
    for w in words:
        text_len = max(1, len(w[4]))
        char_widths.append((w[2] - w[0]) / text_len)
    char_widths.sort()
    median_cw = char_widths[len(char_widths) // 2] if char_widths else 5.0
    col_gap_threshold = max(6.0, median_cw * COLUMN_GAP_RATIO * 4)

    lines: list[list] = []
    current: list = []
    current_yc: float | None = None

    for w in words:
        x0, y0, x1, y1, text, *_ = w
        yc = (y0 + y1) / 2.0
        if current_yc is None or abs(yc - current_yc) <= y_tol:
            current.append(w)
            if current_yc is None:
                current_yc = yc
            else:
                current_yc = sum((ww[1] + ww[3]) / 2.0 for ww in current) / len(current)
        else:
            current.sort(key=lambda ww: ww[0])
            lines.append(current)
            current = [w]
            current_yc = yc

    if current:
        current.sort(key=lambda ww: ww[0])
        lines.append(current)

    out_lines: list[str] = []
    for line in lines:
        parts: list[str] = []
        prev_x1: float | None = None
        for w in line:
            x0, y0, x1, y1, text, *_ = w
            if prev_x1 is not None:
                gap = x0 - prev_x1
                if gap >= col_gap_threshold and len(text) >= MIN_CHARS_FOR_TAB:
                    parts.append("\t")
                else:
                    parts.append(" ")
            parts.append(text)
            prev_x1 = x1
        joined = "".join(parts).rstrip()
        if joined:
            out_lines.append(joined)

    return "\n".join(out_lines)


def _page_text_quality(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"n_lines": 0, "avg_line_len": 0.0, "fragmented": True}

    avg_len = sum(len(l) for l in lines) / len(lines)
    fragmented = (avg_len < MIN_AVG_LINE_LEN and len(lines) >= MIN_LINES_FOR_CHECK)
    return {
        "n_lines": len(lines),
        "avg_line_len": round(avg_len, 1),
        "fragmented": fragmented,
    }


def _pdfplumber_page_text(pdf_path: Path, page_no: int) -> str:
    if not HAS_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_no - 1 >= len(pdf.pages):
                return ""
            page = pdf.pages[page_no - 1]
            txt = page.extract_text(layout=True) or ""
            return txt.rstrip()
    except Exception as exc:
        log.debug("pdfplumber text failed on %s p%d: %s",
                  pdf_path.name, page_no, exc)
        return ""


def extract_pdf_text(
    pdf_path: Path,
    use_pdfplumber_fallback: bool = True,
) -> tuple[str, int, dict]:
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        chunks: list[str] = []
        quality = {
            "pages_checked": 0,
            "pages_fragmented": 0,
            "pages_pdfplumber_used": 0,
            "avg_line_len_overall": 0.0,
        }
        total_lines = 0
        total_chars = 0

        for i in range(page_count):
            page_no = i + 1
            page = doc.load_page(i)

            body = _word_reconstruct_page(page)
            q = _page_text_quality(body)
            quality["pages_checked"] += 1

            if use_pdfplumber_fallback and HAS_PDFPLUMBER and q["fragmented"]:
                alt = _pdfplumber_page_text(pdf_path, page_no)
                if alt:
                    alt_q = _page_text_quality(alt)
                    if alt_q["avg_line_len"] > q["avg_line_len"]:
                        body = alt
                        q = alt_q
                        quality["pages_pdfplumber_used"] += 1

            if q["fragmented"]:
                quality["pages_fragmented"] += 1

            total_lines += q["n_lines"]
            total_chars += len(body)

            chunks.append(PAGE_MARKER.format(n=page_no))
            chunks.append(body)
            chunks.append("")

        if total_lines:
            quality["avg_line_len_overall"] = round(total_chars / total_lines, 1)

    text = "\n".join(chunks).rstrip() + "\n"
    return text, page_count, quality


# ===========================================================================
# TABLE extraction
# ===========================================================================
def _clean_rows(rows) -> list[list[str]]:
    cleaned: list[list[str]] = []
    for row in rows or []:
        cleaned.append([
            (c.strip() if isinstance(c, str) else "")
            for c in row
        ])
    return cleaned


def _is_usable(rows: list[list[str]]) -> bool:
    if len(rows) < MIN_TABLE_ROWS:
        return False
    max_cols = max((len(r) for r in rows), default=0)
    return max_cols >= MIN_TABLE_COLS


def _tables_pymupdf(page, page_no: int) -> list[dict]:
    out: list[dict] = []
    try:
        finder = page.find_tables()
    except Exception:
        return out

    for tbl in getattr(finder, "tables", []):
        try:
            rows = tbl.extract()
        except Exception:
            rows = []
        cleaned = _clean_rows(rows)
        if not _is_usable(cleaned):
            continue
        out.append({
            "page": page_no,
            "source": "pymupdf",
            "bbox": [round(v, 2) for v in tbl.bbox],
            "n_rows": len(cleaned),
            "n_cols": max((len(r) for r in cleaned), default=0),
            "rows": cleaned,
        })
    return out


def _tables_pdfplumber(pdf_path: Path, page_no: int) -> list[dict]:
    if not HAS_PDFPLUMBER:
        return []
    out: list[dict] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_no - 1 >= len(pdf.pages):
                return out
            page = pdf.pages[page_no - 1]
            for tbl in page.extract_tables():
                cleaned = _clean_rows(tbl)
                if not _is_usable(cleaned):
                    continue
                out.append({
                    "page": page_no,
                    "source": "pdfplumber",
                    "bbox": None,
                    "n_rows": len(cleaned),
                    "n_cols": max((len(r) for r in cleaned), default=0),
                    "rows": cleaned,
                })
    except Exception as exc:
        log.debug("pdfplumber tables failed on %s p%d: %s",
                  pdf_path.name, page_no, exc)
    return out


def extract_pdf_tables(
    pdf_path: Path,
    use_pdfplumber: bool = True,
) -> list[dict]:
    tables_out: list[dict] = []
    pages_needing_fallback: list[int] = []

    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            page_tables = _tables_pymupdf(page, i + 1)
            if page_tables:
                tables_out.extend(page_tables)
            else:
                pages_needing_fallback.append(i + 1)

    if use_pdfplumber and HAS_PDFPLUMBER and pages_needing_fallback:
        for page_no in pages_needing_fallback:
            tables_out.extend(_tables_pdfplumber(pdf_path, page_no))

    return tables_out


# ===========================================================================
# Markdown (optional)
# ===========================================================================
def extract_pdf_markdown(pdf_path: Path) -> str:
    if not HAS_PYMUPDF4LLM:
        return ""
    try:
        md = pymupdf4llm.to_markdown(str(pdf_path))
        return md or ""
    except Exception as exc:
        log.debug("pymupdf4llm failed on %s: %s", pdf_path.name, exc)
        return ""


# ===========================================================================
# Main
# ===========================================================================
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract raw text + tables from TEXT-type PDFs."
    )
    ap.add_argument("--statuses", nargs="+", default=["TEXT"])
    ap.add_argument("--sources", nargs="+", default=None)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--scan-all", action="store_true")
    ap.add_argument("--no-pdfplumber", action="store_true")
    ap.add_argument("--no-md", action="store_true")
    args = ap.parse_args()

    allowed = {s.upper() for s in args.statuses}
    only_sources = set(args.sources) if args.sources else None
    use_pdfplumber = (not args.no_pdfplumber) and HAS_PDFPLUMBER
    use_md = (not args.no_md) and HAS_PYMUPDF4LLM

    if args.scan_all:
        print("[*] --scan-all: ignoring analysis CSV")
        targets = discover_all_pdfs(only_sources)
    else:
        if not ANALYSIS_CSV.exists():
            print(f"[!] Analysis CSV not found: {ANALYSIS_CSV}")
            sys.exit(1)
        targets = load_targets_from_csv(ANALYSIS_CSV, allowed, only_sources)

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("[!] No matching PDFs found.")
        sys.exit(0)

    print(f"[*] Repo root        : {REPO_ROOT}")
    print(f"[*] Output root      : {OUTPUT_ROOT}")
    print(f"[*] Statuses         : {sorted(allowed)}")
    print(f"[*] Targets          : {len(targets)} PDFs")
    if HAS_PYMUPDF_LAYOUT:
        layout_status = "ENABLED (better tables)"
    elif PYMUPDF_LAYOUT_SPEC:
        layout_status = "INSTALLED but not active in this Python environment (restart VS Code / activate the correct venv)"
    else:
        layout_status = "NOT INSTALLED (pip install pymupdf-layout)"
    print(f"[*] pymupdf_layout   : {layout_status}")
    print(f"[*] pdfplumber       : "
          f"{'enabled' if use_pdfplumber else ('installed, disabled' if HAS_PDFPLUMBER else 'NOT INSTALLED')}")
    print(f"[*] Markdown         : "
          f"{'enabled (pymupdf4llm)' if use_md else ('installed, disabled' if HAS_PYMUPDF4LLM else 'NOT INSTALLED')}")
    print(f"[*] Table filter     : >= {MIN_TABLE_ROWS} rows, >= {MIN_TABLE_COLS} cols")
    print(f"[*] Skip existing    : {args.skip_existing}")
    print()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    per_source_stats: dict[str, dict] = defaultdict(lambda: {
        "total_pdfs": 0,
        "extracted": 0,
        "skipped": 0,
        "errors": 0,
        "total_chars": 0,
        "total_tables": 0,
        "tables_pymupdf": 0,
        "tables_pdfplumber": 0,
        "pages_pdfplumber_text": 0,
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
        src_out_dir.mkdir(parents=True, exist_ok=True)

        txt_path = src_out_dir / f"{stem}.txt"
        tbl_path = src_out_dir / f"{stem}.tables.json"
        md_path = src_out_dir / f"{stem}.md"

        if args.skip_existing and txt_path.exists() and tbl_path.exists():
            try:
                chars = len(txt_path.read_text(encoding="utf-8"))
                existing = json.loads(tbl_path.read_text(encoding="utf-8"))
                n_tables = len(existing)
                n_pymupdf = sum(1 for x in existing if isinstance(x, dict)
                                and x.get("source") == "pymupdf")
                n_pdfplumber = sum(1 for x in existing if isinstance(x, dict)
                                   and x.get("source") == "pdfplumber")
            except Exception:
                chars = n_tables = n_pymupdf = n_pdfplumber = 0

            stats["skipped"] += 1
            stats["total_chars"] += chars
            stats["total_tables"] += n_tables
            stats["tables_pymupdf"] += n_pymupdf
            stats["tables_pdfplumber"] += n_pdfplumber
            stats["files"].append({
                "pdf": filename,
                "status": "skipped",
                "chars": chars,
                "tables": n_tables,
                "txt": str(txt_path.relative_to(OUTPUT_ROOT)),
                "tables_json": str(tbl_path.relative_to(OUTPUT_ROOT)),
            })
            continue

        try:
            text, page_count, quality = extract_pdf_text(
                pdf_path, use_pdfplumber_fallback=use_pdfplumber
            )
            tables = extract_pdf_tables(
                pdf_path, use_pdfplumber=use_pdfplumber
            )

            n_pymupdf = sum(1 for x in tables if x.get("source") == "pymupdf")
            n_pdfplumber = sum(1 for x in tables if x.get("source") == "pdfplumber")

            txt_path.write_text(text, encoding="utf-8")
            tbl_path.write_text(
                json.dumps(tables, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            md_written = False
            if use_md:
                md_text = extract_pdf_markdown(pdf_path)
                if md_text:
                    md_path.write_text(md_text, encoding="utf-8")
                    md_written = True

            stats["extracted"] += 1
            stats["total_chars"] += len(text)
            stats["total_tables"] += len(tables)
            stats["tables_pymupdf"] += n_pymupdf
            stats["tables_pdfplumber"] += n_pdfplumber
            stats["pages_pdfplumber_text"] += quality["pages_pdfplumber_used"]

            stats["files"].append({
                "pdf": filename,
                "status": "ok",
                "pages": page_count,
                "chars": len(text),
                "tables": len(tables),
                "tables_pymupdf": n_pymupdf,
                "tables_pdfplumber": n_pdfplumber,
                "avg_line_len": quality["avg_line_len_overall"],
                "pages_fragmented": quality["pages_fragmented"],
                "pages_pdfplumber_text": quality["pages_pdfplumber_used"],
                "txt": str(txt_path.relative_to(OUTPUT_ROOT)),
                "tables_json": str(tbl_path.relative_to(OUTPUT_ROOT)),
                "md": str(md_path.relative_to(OUTPUT_ROOT)) if md_written else None,
                "extracted_at": utcnow_iso(),
            })

        except Exception as exc:
            stats["errors"] += 1
            stats["files"].append({
                "pdf": filename,
                "status": "error",
                "err": str(exc),
            })

    # ---------- Manifests ----------
    generated_at = utcnow_iso()

    global_summary = {
        "generated_at": generated_at,
        "analysis_csv": (str(ANALYSIS_CSV.relative_to(REPO_ROOT))
                         if ANALYSIS_CSV.exists() else None),
        "statuses_processed": sorted(allowed),
        "scan_all": args.scan_all,
        "pymupdf_layout": HAS_PYMUPDF_LAYOUT,
        "pdfplumber_enabled": use_pdfplumber,
        "markdown_enabled": use_md,
        "table_filter": {
            "min_rows": MIN_TABLE_ROWS,
            "min_cols": MIN_TABLE_COLS,
        },
        "sources": {},
        "totals": {
            "total_pdfs": 0, "extracted": 0, "skipped": 0, "errors": 0,
            "total_chars": 0, "total_tables": 0,
            "tables_pymupdf": 0, "tables_pdfplumber": 0,
            "pages_pdfplumber_text": 0,
        },
    }

    for source, stats in sorted(per_source_stats.items()):
        src_dir = OUTPUT_ROOT / source
        src_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "source": source,
            "generated_at": generated_at,
            "pymupdf_layout": HAS_PYMUPDF_LAYOUT,
            **{k: stats[k] for k in (
                "total_pdfs", "extracted", "skipped", "errors",
                "total_chars", "total_tables",
                "tables_pymupdf", "tables_pdfplumber",
                "pages_pdfplumber_text",
            )},
            "files": stats["files"],
        }
        (src_dir / "_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        global_summary["sources"][source] = {
            k: stats[k] for k in (
                "total_pdfs", "extracted", "skipped", "errors",
                "total_chars", "total_tables",
                "tables_pymupdf", "tables_pdfplumber",
                "pages_pdfplumber_text",
            )
        }
        global_summary["sources"][source]["manifest_file"] = \
            f"{source}/_manifest.json"
        for k in global_summary["totals"]:
            global_summary["totals"][k] += stats.get(k, 0)

    (OUTPUT_ROOT / "_manifest.json").write_text(
        json.dumps(global_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    elapsed = time.time() - started
    print()
    print("=" * 100)
    print(f"EXTRACTION COMPLETE   ({elapsed:.1f}s)")
    print("=" * 100)
    print(f"pymupdf_layout: "
          f"{'ON' if HAS_PYMUPDF_LAYOUT else 'OFF — install with: pip install pymupdf-layout'}")
    print(
        f"{'SOURCE':<18} {'TOTAL':>6} {'OK':>6} {'SKIP':>6} "
        f"{'ERR':>5} {'CHARS':>10} {'TABLES':>7} "
        f"{'P-MUPDF':>8} {'P-PLUMB':>8} {'PDFP-TXT':>9}"
    )
    print("-" * 100)
    for source in sorted(per_source_stats.keys()):
        s = per_source_stats[source]
        print(
            f"{source:<18} {s['total_pdfs']:>6} {s['extracted']:>6} "
            f"{s['skipped']:>6} {s['errors']:>5} "
            f"{s['total_chars']:>10} {s['total_tables']:>7} "
            f"{s['tables_pymupdf']:>8} {s['tables_pdfplumber']:>8} "
            f"{s['pages_pdfplumber_text']:>9}"
        )
    print("-" * 100)
    t = global_summary["totals"]
    print(
        f"{'TOTAL':<18} {t['total_pdfs']:>6} {t['extracted']:>6} "
        f"{t['skipped']:>6} {t['errors']:>5} "
        f"{t['total_chars']:>10} {t['total_tables']:>7} "
        f"{t['tables_pymupdf']:>8} {t['tables_pdfplumber']:>8} "
        f"{t['pages_pdfplumber_text']:>9}"
    )
    print()
    print(f"[+] Global manifest : {OUTPUT_ROOT / '_manifest.json'}")


if __name__ == "__main__":
    main()