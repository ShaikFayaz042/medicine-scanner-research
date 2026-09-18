#!/usr/bin/env python3
"""
Analyse every PDF under downloads/<source>/important/ and classify it as:
    - TEXT     : born-digital PDF, ≥80% pages have extractable text
    - SCANNED  : image-only PDF, ≥80% pages look scanned
    - MIXED    : genuinely mixed (neither bucket reaches 80%)
    - EMPTY    : no pages or zero bytes
    - ERROR    : could not be opened / parsed

Key change (2026-09): ratio-based classification. Previously a single
odd page (e.g. a 1-char footer) forced the whole document into MIXED,
creating a pipeline gap where TEXT extraction skipped it (status != TEXT)
and OCR also skipped it (status != SCANNED).

Sampling: reads up to SAMPLE_PAGES pages per PDF (default: all, capped at 10).

Thresholds (tunable):
    TEXT_CHARS_PER_PAGE   >= 100   → page contributes as TEXT
    NEAR_EMPTY_CHARS      <  10    → page is empty-ish (ignored in ratio)
    SCANNED_IMG_COVERAGE  >= 0.5   → page looks scanned
    TEXT_RATIO_MIN        >= 0.80  → whole PDF is TEXT
    SCAN_RATIO_MIN        >= 0.80  → whole PDF is SCANNED
    Otherwise → MIXED

Outputs (in downloads/_analysis/):
    pdf_analysis.csv            - one row per PDF
    pdf_analysis.json           - same data, JSON
    pdf_analysis.txt            - human-readable summary per source

Usage:
    python raw_extraction/analyze_pdfs.py
    python raw_extraction/analyze_pdfs.py --sample-pages 5
    python raw_extraction/analyze_pdfs.py --sources alerts fdc gazette
"""

import argparse
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from tqdm import tqdm

# Make cdsco_utils importable if present
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import cdsco_utils as cu
    DOWNLOADS_ROOT = cu.DOWNLOADS_ROOT
except Exception:
    DOWNLOADS_ROOT = Path(__file__).resolve().parent.parent / "downloads"


logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
TEXT_CHARS_PER_PAGE = 100
NEAR_EMPTY_CHARS = 10
SCANNED_IMG_COVERAGE = 0.5
TEXT_RATIO_MIN = 0.80
SCAN_RATIO_MIN = 0.80
DEFAULT_SAMPLE_PAGES = 10


# ---------------------------------------------------------------------------
def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Core: analyse one PDF
# ---------------------------------------------------------------------------
def analyse_pdf(pdf_path: Path, sample_pages: int) -> dict:
    """
    Return a dict describing the PDF.

    Per page, classify as:
        near_empty  : chars < NEAR_EMPTY_CHARS and img_cov < 0.1
        text        : chars >= TEXT_CHARS_PER_PAGE
        scanned     : chars == 0 and img_cov >= SCANNED_IMG_COVERAGE
        text        : small text, small image  (still counts as text)
        scanned     : no text, no big image    (posters, blanks)

    Whole-PDF:
        near_empty pages are EXCLUDED from the ratio (a 1-page footer
        on page 9 of 9 shouldn't drag a clean PDF into MIXED).

        effective = sampled - near_empty_count
        text_ratio = text_count / effective
        scan_ratio = scan_count / effective

        if effective == 0          → EMPTY
        elif text_ratio >= 0.80    → TEXT
        elif scan_ratio >= 0.80    → SCANNED
        else                       → MIXED
    """
    result = {
        "path": str(pdf_path),
        "size_bytes": pdf_path.stat().st_size,
        "pages": 0,
        "sampled": 0,
        "text_chars": 0,
        "avg_chars": 0.0,
        "avg_img_cov": 0.0,
        "text_pages": 0,
        "scanned_pages": 0,
        "near_empty_pages": 0,
        "status": "ERROR",
        "err": "",
    }

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        result["err"] = f"open failed: {exc}"
        return result

    try:
        total_pages = doc.page_count
        result["pages"] = total_pages

        if total_pages == 0:
            result["status"] = "EMPTY"
            return result

        if total_pages <= sample_pages:
            pages_to_check = list(range(total_pages))
        else:
            step = max(1, total_pages // sample_pages)
            pages_to_check = list(range(0, total_pages, step))[:sample_pages]

        text_count = 0
        scanned_count = 0
        near_empty_count = 0
        total_chars = 0
        total_img_cov = 0.0

        for pno in pages_to_check:
            page = doc.load_page(pno)

            text = page.get_text("text") or ""
            chars = len("".join(text.split()))
            total_chars += chars

            img_cov = 0.0
            try:
                page_area = page.rect.width * page.rect.height
                if page_area > 0:
                    img_area = 0.0
                    for img in page.get_images(full=True):
                        xref = img[0]
                        try:
                            rects = page.get_image_rects(xref)
                        except Exception:
                            rects = []
                        for r in rects:
                            img_area += r.width * r.height
                    img_cov = min(1.0, img_area / page_area)
            except Exception:
                img_cov = 0.0
            total_img_cov += img_cov

            # --- per-page classification ---
            if chars < NEAR_EMPTY_CHARS and img_cov < 0.1:
                near_empty_count += 1
            elif chars >= TEXT_CHARS_PER_PAGE:
                text_count += 1
            elif img_cov >= SCANNED_IMG_COVERAGE:
                scanned_count += 1
            elif chars == 0:
                scanned_count += 1
            else:
                text_count += 1

        sampled = len(pages_to_check)
        result["sampled"] = sampled
        result["text_chars"] = total_chars
        result["avg_chars"] = total_chars / sampled if sampled else 0.0
        result["avg_img_cov"] = total_img_cov / sampled if sampled else 0.0
        result["text_pages"] = text_count
        result["scanned_pages"] = scanned_count
        result["near_empty_pages"] = near_empty_count

        effective = sampled - near_empty_count

        if effective == 0:
            result["status"] = "EMPTY"
        elif text_count / effective >= TEXT_RATIO_MIN:
            result["status"] = "TEXT"
        elif scanned_count / effective >= SCAN_RATIO_MIN:
            result["status"] = "SCANNED"
        else:
            result["status"] = "MIXED"

        return result

    finally:
        doc.close()


# ---------------------------------------------------------------------------
def discover_sources(downloads_root: Path,
                     only: list[str] | None = None) -> list[Path]:
    sources = []
    for p in sorted(downloads_root.iterdir()):
        if not p.is_dir() or p.name.startswith("_"):
            continue
        if only and p.name not in only:
            continue
        important_dir = p / "important"
        if important_dir.is_dir():
            sources.append(important_dir)
    return sources


def write_csv(records: list[dict], out_path: Path) -> None:
    fields = [
        "source", "filename", "status", "pages", "sampled",
        "text_chars", "avg_chars", "avg_img_cov",
        "text_pages", "scanned_pages", "near_empty_pages",
        "size_bytes", "err",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in fields})


def write_txt_summary(records: list[dict], out_path: Path,
                      elapsed: float) -> None:
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_source[r["source"]].append(r)

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("PDF TEXT / SCANNED ANALYSIS")
    lines.append("=" * 78)
    lines.append(f"Analysed {len(records)} PDFs in {elapsed:.1f}s")
    lines.append("")
    lines.append(
        f"{'SOURCE':<20} {'TOTAL':>6} {'TEXT':>6} {'SCANNED':>8} "
        f"{'MIXED':>6} {'EMPTY':>6} {'ERROR':>6}"
    )
    lines.append("-" * 78)

    grand = defaultdict(int)
    for source in sorted(by_source.keys()):
        recs = by_source[source]
        counts = defaultdict(int)
        for r in recs:
            counts[r["status"]] += 1
            grand[r["status"]] += 1
        lines.append(
            f"{source:<20} {len(recs):>6} {counts['TEXT']:>6} "
            f"{counts['SCANNED']:>8} {counts['MIXED']:>6} "
            f"{counts['EMPTY']:>6} {counts['ERROR']:>6}"
        )
    lines.append("-" * 78)
    lines.append(
        f"{'TOTAL':<20} {len(records):>6} {grand['TEXT']:>6} "
        f"{grand['SCANNED']:>8} {grand['MIXED']:>6} "
        f"{grand['EMPTY']:>6} {grand['ERROR']:>6}"
    )
    lines.append("")
    lines.append("")

    for source in sorted(by_source.keys()):
        recs = by_source[source]
        groups = {
            "TEXT": [], "SCANNED": [], "MIXED": [],
            "EMPTY": [], "ERROR": [],
        }
        for r in recs:
            groups[r["status"]].append(r["filename"])

        lines.append("=" * 78)
        lines.append(f"### {source}  ({len(recs)} files)")
        lines.append("=" * 78)
        lines.append("")
        for status in ("TEXT", "SCANNED", "MIXED", "EMPTY", "ERROR"):
            items = sorted(groups[status])
            lines.append(f"  {status} ({len(items)})")
            lines.append("  " + "-" * 74)
            if not items:
                lines.append("    (none)")
            else:
                for f in items:
                    lines.append(f"    - {f}")
            lines.append("")

    lines.append("=" * 78)
    lines.append("END OF REPORT")
    lines.append("=" * 78)
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-pages", type=int,
                        default=DEFAULT_SAMPLE_PAGES)
    parser.add_argument("--sources", nargs="+", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    downloads_root = DOWNLOADS_ROOT
    if not downloads_root.is_dir():
        raise SystemExit(f"[!] Downloads root not found: {downloads_root}")

    out_dir = args.output_dir or (downloads_root / "_analysis")
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = discover_sources(downloads_root, only=args.sources)
    if not sources:
        raise SystemExit("[!] No <source>/important/ folders found.")

    # pymupdf-layout exposes its feature via pymupdf.layout, not a top-level pymupdf_layout module.
    try:
        import pymupdf.layout  # noqa: F401
        layout_ok = True
    except Exception:
        layout_ok = False

    print(f"[*] Downloads root : {downloads_root}")
    print(f"[*] Output dir     : {out_dir}")
    print(f"[*] Sample pages   : {args.sample_pages}")
    print(f"[*] pymupdf_layout : "
          f"{'installed (better table detection)' if layout_ok else 'NOT installed'}")
    print()

    records: list[dict] = []
    started = time.time()

    for important_dir in sources:
        source = important_dir.parent.name
        pdfs = sorted(important_dir.glob("*.pdf"))
        if not pdfs:
            print(f"[*] {source}: no PDFs, skipping")
            continue

        print(f"[*] {source}: {len(pdfs)} PDFs")
        for pdf in tqdm(pdfs, desc=f"  {source}", unit="pdf"):
            res = analyse_pdf(pdf, sample_pages=args.sample_pages)
            res["source"] = source
            res["filename"] = pdf.name
            records.append(res)

    elapsed = time.time() - started

    csv_path = out_dir / "pdf_analysis.csv"
    json_path = out_dir / "pdf_analysis.json"
    txt_path = out_dir / "pdf_analysis.txt"

    write_csv(records, csv_path)
    json_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_txt_summary(records, txt_path, elapsed)

    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records:
        by_source[r["source"]][r["status"]] += 1
        by_source[r["source"]]["TOTAL"] += 1

    print()
    print("=" * 78)
    print(f"ANALYSIS COMPLETE  ({len(records)} PDFs in {elapsed:.1f}s)")
    print("=" * 78)
    print(
        f"{'SOURCE':<20} {'TOTAL':>6} {'TEXT':>6} {'SCANNED':>8} "
        f"{'MIXED':>6} {'EMPTY':>6} {'ERROR':>6}"
    )
    print("-" * 78)
    for src in sorted(by_source.keys()):
        c = by_source[src]
        print(
            f"{src:<20} {c['TOTAL']:>6} {c['TEXT']:>6} "
            f"{c['SCANNED']:>8} {c['MIXED']:>6} "
            f"{c['EMPTY']:>6} {c['ERROR']:>6}"
        )
    print("-" * 78)
    print()
    print(f"[+] CSV  : {csv_path}")
    print(f"[+] JSON : {json_path}")
    print(f"[+] TXT  : {txt_path}")


if __name__ == "__main__":
    main()