#!/usr/bin/env python3
"""
Extract raw text + tables from TEXT-type PDFs.

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

TEXT EXTRACTION STRATEGY
------------------------
1. Word-level reconstruction (PyMuPDF):
     get_text("words") → group by y-coordinate → sort by x → join.
   This fixes the classic "one word per line" failure on tabular PDFs.

2. Quality check per page:
     - if avg line length < MIN_AVG_LINE_LEN AND line_count > MIN_LINES_FOR_CHECK
       → treat as fragmented

3. pdfplumber fallback (only for fragmented pages):
     page.extract_text(layout=True)

TABLE EXTRACTION STRATEGY
-------------------------
1. PyMuPDF find_tables() on every page.
2. Post-filter: keep only tables with >= MIN_TABLE_ROWS and >= MIN_TABLE_COLS.
3. pdfplumber fallback per-page when PyMuPDF yields 0 tables.

BEHAVIOR
--------
Upsert by default: every PDF is re-extracted and its outputs overwritten.
Use --skip-existing to make it idempotent instead.

Usage:
    python raw_extraction/extract_text.py
    python raw_extraction/extract_text.py --statuses TEXT MIXED
    python raw_extraction/extract_text.py --sources alerts fdc
    python raw_extraction/extract_text.py --skip-existing
    python raw_extraction/extract_text.py --scan-all
    python raw_extraction/extract_text.py --no-pdfplumber
    python raw_extraction/extract_text.py --no-md
"""

import argparse
import csv
import json
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# --- PyMuPDF: prefer new module name; fall back for old installs ---
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

# --- pdfplumber: optional ---
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# --- pymupdf4llm: optional (Markdown output) ---
try:
    import pymupdf4llm
    HAS_PYMUPDF4LLM = True
except ImportError:
    HAS_PYMUPDF4LLM = False

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

# ---------------------------------------------------------------------------
# Tunables — text
# ---------------------------------------------------------------------------
# Word-level reconstruction
Y_TOLERANCE_RATIO = 0.6          # tolerance = median_word_height * this
COLUMN_GAP_RATIO = 1.5           # gap > median_char_width * this → tab
MIN_CHARS_FOR_TAB = 3            # don't insert tab for trivial gaps

# Fragmentation detection (triggers pdfplumber fallback)
MIN_AVG_LINE_LEN = 20            # avg chars/line below this = suspicious
MIN_LINES_FOR_CHECK = 15         # only flag pages with this many lines+

# ---------------------------------------------------------------------------
# Tunables — tables
# ---------------------------------------------------------------------------
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
# TEXT EXTRACTION — word-level reconstruction
# ===========================================================================
def _word_reconstruct_page(page) -> str:
    """
    Rebuild a page's text from individual words using their coordinates.

    Steps:
      1. Get words via get_text("words", sort=True).
      2. Compute median word height and char width (for adaptive tolerances).
      3. Group words into lines: same y-center within tolerance.
      4. Sort each line left→right; join with space or tab depending on gap.

    This is the fix for "one word per line" output on tabular PDFs.
    """
    try:
        words = page.get_text("words", sort=True)
    except Exception:
        return ""

    # Filter out empty tokens
    words = [w for w in words if w[4].strip()]
    if not words:
        return ""

    # Adaptive tolerances
    heights = sorted((w[3] - w[1]) for w in words if (w[3] - w[1]) > 0)
    median_h = heights[len(heights) // 2] if heights else 10.0
    y_tol = max(1.5, median_h * Y_TOLERANCE_RATIO)

    # Median char width (for column-gap detection)
    char_widths = []
    for w in words:
        text_len = max(1, len(w[4]))
        char_widths.append((w[2] - w[0]) / text_len)
    char_widths.sort()
    median_cw = char_widths[len(char_widths) // 2] if char_widths else 5.0
    col_gap_threshold = max(6.0, median_cw * COLUMN_GAP_RATIO * 4)

    # Group words into lines
    lines: list[list] = []
    current: list = []
    current_yc: float | None = None

    for w in words:
        x0, y0, x1, y1, text, *_ = w
        yc = (y0 + y1) / 2.0
        if current_yc is None or abs(yc - current_yc) <= y_tol:
            current.append(w)
            # Keep the running average of y-center for better grouping
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

    # Build text with tabs for large horizontal gaps
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
    """
    Compute simple quality metrics for a page's reconstructed text.

    Returns dict with:
        n_lines, avg_line_len, fragmented (bool)
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"n_lines": 0, "avg_line_len": 0.0, "fragmented": True}

    avg_len = sum(len(l) for l in lines) / len(lines)
    fragmented = (
        avg_len < MIN_AVG_LINE_LEN
        and len(lines) >= MIN_LINES_FOR_CHECK
    )
    return {
        "n_lines": len(lines),
        "avg_line_len": round(avg_len, 1),
        "fragmented": fragmented,
    }


def _pdfplumber_page_text(pdf_path: Path, page_no: int) -> str:
    """Extract a single page with pdfplumber's layout-preserving mode."""
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
    """
    Extract text page by page with word-level reconstruction.

    Returns (text, page_count, quality_summary).

    For fragmented pages, retries with pdfplumber layout mode if available.
    """
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

            # Fallback to pdfplumber if fragmentated
            if (
                use_pdfplumber_fallback
                and HAS_PDFPLUMBER
                and q["fragmented"]
            ):
                alt = _pdfplumber_page_text(pdf_path, page_no)
                if alt:
                    alt_q = _page_text_quality(alt)
                    # Only accept the fallback if it's genuinely better
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
            quality["avg_line_len_overall"] = round(
                total_chars / total_lines, 1
            )

    text = "\n".join(chunks).rstrip() + "\n"
    return text, page_count, quality


# ===========================================================================
# TABLE EXTRACTION
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
# MARKDOWN (optional)
# ===========================================================================
def extract_pdf_markdown(pdf_path: Path) -> str:
    """Return Markdown via pymupdf4llm. Empty string if unavailable."""
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
    ap.add_argument(
        "--skip-existing", action="store_true",
        help="Skip PDFs whose outputs already exist "
             "(default: always re-extract).",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--scan-all", action="store_true")
    ap.add_argument("--no-pdfplumber", action="store_true")
    ap.add_argument(
        "--no-md", action="store_true",
        help="Skip Markdown generation (even if pymupdf4llm is installed).",
    )
    args = ap.parse_args()

    allowed = {s.upper() for s in args.statuses}
    only_sources = set(args.sources) if args.sources else None
    use_pdfplumber = (not args.no_pdfplumber) and HAS_PDFPLUMBER
    use_md = (not args.no_md) and HAS_PYMUPDF4LLM

    # --- Build targets ---
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

        # --- skip-existing ---
        if (
            args.skip_existing
            and txt_path.exists()
            and tbl_path.exists()
        ):
            try:
                chars = len(txt_path.read_text(encoding="utf-8"))
                existing = json.loads(tbl_path.read_text(encoding="utf-8"))
                n_tables = len(existing)
                n_pymupdf = sum(
                    1 for x in existing
                    if isinstance(x, dict) and x.get("source") == "pymupdf"
                )
                n_pdfplumber = sum(
                    1 for x in existing
                    if isinstance(x, dict) and x.get("source") == "pdfplumber"
                )
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

        # --- extract ---
        try:
            text, page_count, quality = extract_pdf_text(
                pdf_path, use_pdfplumber_fallback=use_pdfplumber
            )
            tables = extract_pdf_tables(
                pdf_path, use_pdfplumber=use_pdfplumber
            )

            n_pymupdf = sum(
                1 for x in tables if x.get("source") == "pymupdf"
            )
            n_pdfplumber = sum(
                1 for x in tables if x.get("source") == "pdfplumber"
            )

            # Write .txt
            txt_path.write_text(text, encoding="utf-8")

            # Write .tables.json
            tbl_path.write_text(
                json.dumps(tables, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Write .md (optional)
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

            entry = {
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
            }
            stats["files"].append(entry)

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
        "analysis_csv": (
            str(ANALYSIS_CSV.relative_to(REPO_ROOT))
            if ANALYSIS_CSV.exists() else None
        ),
        "statuses_processed": sorted(allowed),
        "scan_all": args.scan_all,
        "pdfplumber_enabled": use_pdfplumber,
        "markdown_enabled": use_md,
        "table_filter": {
            "min_rows": MIN_TABLE_ROWS,
            "min_cols": MIN_TABLE_COLS,
        },
        "text_strategy": {
            "reconstruction": "word-level (y-coordinate grouping)",
            "y_tolerance_ratio": Y_TOLERANCE_RATIO,
            "fragmentation_check": {
                "min_avg_line_len": MIN_AVG_LINE_LEN,
                "min_lines_for_check": MIN_LINES_FOR_CHECK,
            },
        },
        "sources": {},
        "totals": {
            "total_pdfs": 0,
            "extracted": 0,
            "skipped": 0,
            "errors": 0,
            "total_chars": 0,
            "total_tables": 0,
            "tables_pymupdf": 0,
            "tables_pdfplumber": 0,
            "pages_pdfplumber_text": 0,
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
            "tables_pymupdf": stats["tables_pymupdf"],
            "tables_pdfplumber": stats["tables_pdfplumber"],
            "pages_pdfplumber_text": stats["pages_pdfplumber_text"],
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
            "tables_pymupdf": stats["tables_pymupdf"],
            "tables_pdfplumber": stats["tables_pdfplumber"],
            "pages_pdfplumber_text": stats["pages_pdfplumber_text"],
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
    print("=" * 100)
    print(f"EXTRACTION COMPLETE   ({elapsed:.1f}s)")
    print("=" * 100)
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
    print(f"[+] Per-source      : {OUTPUT_ROOT}/<source>/_manifest.json")


if __name__ == "__main__":
    main()