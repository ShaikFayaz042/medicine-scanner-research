#!/usr/bin/env python3
"""
NSQ parser — extracts structured records from NSQ alert PDFs.

Inputs:
    type_classification/nsq_alert/_manifest.json          (list of NSQ documents)
    raw_extraction/text/<src>/<name>.tables.json          (TEXT PDFs)
    raw_extraction/ocr_tesseract/<src>/<name>.blocks.json (SCANNED PDFs)

Outputs:
    structured_raw/nsq/<document_id>.json                 (per-document records)
    structured_raw/nsq/_manifest.json                     (batch summary)

RAW — no normalization.
    Dates stay as strings ("10/2023"), product names keep newlines,
    manufacturer names keep their full address, batch numbers keep case.

Two extraction paths:
    TEXT     → read tables.json (PyMuPDF already structured the table)
    SCANNED  → read blocks.json (word-level boxes → reconstruct rows by
               y-clustering → assign words to columns by x-position)

Each record carries two views:
    raw_data   — original header text as key, raw value
    canonical  — canonical key (product_name, batch_no, ...), raw value

Usage:
    python scripts/parse_nsq.py
    python scripts/parse_nsq.py --limit 3                 # smoke test
    python scripts/parse_nsq.py --files "11256_...pdf"
    python scripts/parse_nsq.py --force
    python scripts/parse_nsq.py --only-text
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
REPO_ROOT = SCRIPTS_DIR.parent
NSQ_MANIFEST = REPO_ROOT / "type_classification" / "nsq_alert" / "_manifest.json"
OUTPUT_DIR = REPO_ROOT / "structured_raw" / "nsq"


# ---------------------------------------------------------------------------
# Canonical column mapping
# ---------------------------------------------------------------------------
CANONICAL_KEYS = {
    "s_no":          ["s no", "s n", "s. no", "s.n.", "s no.", "sl no", "sr no", "s.n"],
    "product_name":  [
        "product drug name", "product name", "name of drug",
        "name of drugs medical device cosmetics",
        "name of drugs", "drug name", "product",
    ],
    "batch_no":      ["batch no", "batch no.", "batch number", "batch", "b no", "b. no"],
    "mfg_date":      [
        "manufacturing date", "manufacturing dt", "mfg date", "mfg dt",
        "date of manufacture", "manufacture date",
    ],
    "exp_date":      ["expiry date", "exp date", "exp dt", "expiry dt", "exp"],
    "manufacturer":  [
        "manufactured by", "manufacturer", "mfg by", "manufacturer name",
        "manufactured by name",
    ],
    "nsq_result":    [
        "nsq result", "reason for failure", "result", "nsq reason",
        "reason", "failure reason",
    ],
    "reported_by":   [
        "reported by cdsco laboratory", "reported by", "reported by lab",
        "reporting source", "reporting lab", "reported",
    ],
    "drawn_by":      ["drawn by"],
    "from_place":    ["from", "from place"],
    "testing_lab":   ["testing lab", "lab"],
}

# Reverse map for exact-match lookup
NORMALIZED_TO_CANONICAL: dict[str, str] = {}
for canonical, variants in CANONICAL_KEYS.items():
    for variant in variants:
        NORMALIZED_TO_CANONICAL[variant] = canonical


def normalize_header(s: str) -> str:
    """
    Normalize a header cell for lookup.
    'Date of\\nManufactur\\ne' → 'date of manufactur e'
    """
    if not s:
        return ""
    s = s.replace("\n", " ").strip().lower()
    s = re.sub(r"[\W_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_key(header: str) -> str | None:
    """
    Map a header string to a canonical key, or None if unknown.

    Strategy (in order):
        1. Exact match after normalizing
        2. Compact match — remove all spaces so multi-line splits work
           ("date of manufactur e" → "dateofmanufacture")
        3. Keyword-based fallback for unseen variants
    """
    n = normalize_header(header)
    if not n:
        return None

    # 1. Exact match
    if n in NORMALIZED_TO_CANONICAL:
        return NORMALIZED_TO_CANONICAL[n]

    # 2. Compact match — handles "Manufactur\ne" splits
    compact = n.replace(" ", "")
    for variant, canon in NORMALIZED_TO_CANONICAL.items():
        if variant.replace(" ", "") == compact:
            return canon

    # 3. Keyword fallback
    if "batch" in n:
        return "batch_no"
    if re.match(r"^s\s*\.?\s*n", n) or "sl no" in n or "sr no" in n:
        return "s_no"
    if "product" in n or "name of drug" in n or ("name of" in n and "drug" in n):
        return "product_name"
    if "manufactur" in n and "date" in n:
        return "mfg_date"
    if ("expiry" in n or "exp" in n) and "date" in n:
        return "exp_date"
    if "manufactur" in n and "by" in n:
        return "manufacturer"
    if "reason" in n or "nsq result" in n or "result" in n:
        return "nsq_result"
    if "reported" in n or "reporting" in n:
        return "reported_by"
    if "drawn" in n:
        return "drawn_by"

    return None


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------
SECTION_PATTERNS = [
    re.compile(r"^\s*[A-Z]\s*\.\s*", re.IGNORECASE),
    re.compile(r"\bcdsco\s+central\s+laborator", re.IGNORECASE),
    re.compile(r"\bstate\s+laborator", re.IGNORECASE),
    re.compile(r"\bcentral\s+laborator", re.IGNORECASE),
    re.compile(r"\bcdsco\s+labs?\b", re.IGNORECASE),
]

HEADER_KEYWORDS = [
    "product", "batch", "name of", "manufactur", "expiry", "nsq",
    "s no", "s.n", "reason", "reported",
]


def is_section_row(cells: list[str]) -> bool:
    """A section row has content only in cell 0 and looks like a section title."""
    non_empty = [c for c in cells if c and c.strip()]
    if len(non_empty) > 1:
        return False
    if not non_empty:
        return False
    first = non_empty[0].strip()
    return any(p.search(first) for p in SECTION_PATTERNS)


def is_header_row(cells: list[str]) -> bool:
    """A header row contains multiple column-name keywords."""
    joined = " ".join(c.lower() for c in cells if c)
    hits = sum(1 for kw in HEADER_KEYWORDS if kw in joined)
    return hits >= 2


# ---------------------------------------------------------------------------
# TEXT extraction — from tables.json
# ---------------------------------------------------------------------------
# Fallback layout when a table body appears without a preceding header row
FALLBACK_KEYS = [
    "s_no", "product_name", "batch_no", "mfg_date",
    "exp_date", "manufacturer", "nsq_result", "reported_by",
]
FALLBACK_DISPLAY = [
    "S.N.", "Product/Drug Name", "Batch No.",
    "Manufacturing Date", "Expiry Date",
    "Manufactured By", "NSQ Result",
    "Reported by CDSCO Laboratory",
]


def _row_is_valid(canonical_data: dict[str, str]) -> bool:
    """A data row must have at least one meaningful value in a core column."""
    for key in ("product_name", "batch_no", "nsq_result", "s_no"):
        if canonical_data.get(key, "").strip():
            return True
    return False


def extract_from_tables_json(tables_path: Path) -> tuple[list[dict], dict]:
    """
    Read PyMuPDF tables.json and return (records, stats).

    Section rows and header rows are skipped (but drive state). Data rows
    are kept if they satisfy _row_is_valid() on canonical keys — NOT on
    hardcoded display strings, so varying headers work fine.
    """
    if not tables_path.exists():
        return [], {"error": "tables.json missing"}

    try:
        tables = json.loads(tables_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], {"error": f"json parse failed: {exc}"}

    records: list[dict] = []
    stats = {
        "tables_read": 0,
        "rows_seen": 0,
        "rows_extracted": 0,
        "section_rows_skipped": 0,
        "header_rows_skipped": 0,
        "empty_rows_skipped": 0,
        "invalid_rows_skipped": 0,
        "sections": [],
    }

    current_section: str | None = None
    header_keys: list[str] = []          # canonical keys (persist across tables)
    header_display: list[str] = []       # original header text

    for tbl in tables:
        rows = tbl.get("rows", [])
        if not rows:
            continue
        stats["tables_read"] += 1

        for row in rows:
            stats["rows_seen"] += 1
            cells = [str(c) if c is not None else "" for c in row]

            # Skip fully-empty rows
            if not any(c.strip() for c in cells):
                stats["empty_rows_skipped"] += 1
                continue

            # Section row
            if is_section_row(cells):
                current_section = cells[0].strip()
                if current_section not in stats["sections"]:
                    stats["sections"].append(current_section)
                stats["section_rows_skipped"] += 1
                continue

            # Header row → refresh column mapping
            if is_header_row(cells):
                header_keys = []
                header_display = []
                for c in cells:
                    h = c.replace("\n", " ").strip()
                    k = canonical_key(h)
                    header_keys.append(k or f"unknown_{len(header_keys)}")
                    header_display.append(h)
                stats["header_rows_skipped"] += 1
                continue

            # Data row — need a header mapping (fallback if none seen)
            if not header_keys:
                if len(cells) == len(FALLBACK_KEYS):
                    header_keys = list(FALLBACK_KEYS)
                    header_display = list(FALLBACK_DISPLAY)
                else:
                    stats["invalid_rows_skipped"] += 1
                    continue

            # Build both representations
            raw_data: dict[str, str] = {}
            canonical_data: dict[str, str] = {}
            for i, cell in enumerate(cells):
                if i >= len(header_keys):
                    break
                canon = header_keys[i]
                display = (
                    header_display[i]
                    if i < len(header_display) and header_display[i]
                    else canon
                )
                value = cell.rstrip()
                raw_data[display] = value
                if not canon.startswith("unknown_"):
                    canonical_data[canon] = value

            if not _row_is_valid(canonical_data):
                stats["invalid_rows_skipped"] += 1
                continue

            records.append({
                "section": current_section,
                "raw_data": raw_data,
                "canonical": canonical_data,
            })
            stats["rows_extracted"] += 1

    return records, stats


# ---------------------------------------------------------------------------
# SCANNED extraction — from blocks.json
# ---------------------------------------------------------------------------
def _cluster_rows(blocks: list[dict], y_tol_ratio: float = 0.6) -> list[list[dict]]:
    """Group word-blocks into visual rows by y-center proximity."""
    if not blocks:
        return []

    heights = sorted(
        b["y_bottom"] - b["y_top"]
        for b in blocks
        if b["y_bottom"] > b["y_top"]
    )
    median_h = heights[len(heights) // 2] if heights else 15.0
    y_tol = max(3.0, median_h * y_tol_ratio)

    sorted_blocks = sorted(blocks, key=lambda b: (b["y_center"], b["x_left"]))
    rows: list[list[dict]] = []
    current: list[dict] = []
    current_yc: float | None = None

    for b in sorted_blocks:
        if current_yc is None or abs(b["y_center"] - current_yc) <= y_tol:
            current.append(b)
            current_yc = sum(bb["y_center"] for bb in current) / len(current)
        else:
            current.sort(key=lambda bb: bb["x_left"])
            rows.append(current)
            current = [b]
            current_yc = b["y_center"]

    if current:
        current.sort(key=lambda bb: bb["x_left"])
        rows.append(current)

    return rows


def _detect_columns(header_row: list[dict]) -> list[tuple[float, str]]:
    """
    Given the header row's word blocks, return [(x_left, canonical_key), ...]
    sorted by x_left. Each canonical key appears at most once (first win).
    """
    cols: list[tuple[float, str]] = []
    seen: set[str] = set()

    # Try to merge adjacent header words into a single phrase first
    # (helps "Batch" + "No." → "Batch No.")
    joined_blocks = sorted(header_row, key=lambda b: b["x_left"])
    for i, b in enumerate(joined_blocks):
        text = b["text"].strip()
        if not text:
            continue
        key = canonical_key(text)
        # If single word doesn't map, try pairing with next word
        if not key and i + 1 < len(joined_blocks):
            next_text = joined_blocks[i + 1]["text"].strip()
            if next_text:
                key = canonical_key(f"{text} {next_text}")
        if key and key not in seen:
            cols.append((b["x_left"], key))
            seen.add(key)

    cols.sort(key=lambda x: x[0])
    return cols


def _assign_to_columns(
    row: list[dict],
    columns: list[tuple[float, str]],
) -> dict[str, str]:
    """Assign each word in a row to the nearest column by x_left."""
    if not columns:
        return {}

    buckets: dict[str, list[str]] = {key: [] for _, key in columns}

    # Boundaries = midpoint between consecutive column x_left values
    boundaries: list[float] = []
    for i in range(1, len(columns)):
        boundaries.append((columns[i - 1][0] + columns[i][0]) / 2.0)

    for b in row:
        text = b["text"].strip()
        if not text:
            continue
        x = b["x_left"]
        col_idx = 0
        for i, bnd in enumerate(boundaries):
            if x >= bnd:
                col_idx = i + 1
            else:
                break
        key = columns[col_idx][1]
        buckets[key].append(text)

    return {k: " ".join(v) for k, v in buckets.items() if v}


def extract_from_blocks_json(blocks_path: Path) -> tuple[list[dict], dict]:
    """
    Reconstruct rows from OCR word-blocks and return (records, stats).
    Column mapping is derived from the first header row encountered.
    """
    if not blocks_path.exists():
        return [], {"error": "blocks.json missing"}

    try:
        pages = json.loads(blocks_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], {"error": f"json parse failed: {exc}"}

    records: list[dict] = []
    stats = {
        "pages_read": 0,
        "rows_seen": 0,
        "rows_extracted": 0,
        "header_rows_skipped": 0,
        "invalid_rows_skipped": 0,
        "sections": [],
    }

    columns: list[tuple[float, str]] = []
    current_section: str | None = None

    for page in pages:
        stats["pages_read"] += 1
        blocks = page.get("blocks", [])
        rows = _cluster_rows(blocks)

        for row in rows:
            stats["rows_seen"] += 1
            row_text = " ".join(b["text"] for b in row).strip()
            if not row_text:
                continue

            # Section detection
            if any(p.search(row_text) for p in SECTION_PATTERNS) and len(row) <= 3:
                current_section = row_text
                if current_section not in stats["sections"]:
                    stats["sections"].append(current_section)
                continue

            # Header detection — first row with ≥2 header keywords
            if not columns:
                joined = row_text.lower()
                hits = sum(1 for kw in HEADER_KEYWORDS if kw in joined)
                if hits >= 2:
                    detected = _detect_columns(row)
                    if detected:
                        columns = detected
                        stats["header_rows_skipped"] += 1
                        continue

            if not columns:
                continue

            canonical_data = _assign_to_columns(row, columns)
            if not _row_is_valid(canonical_data):
                stats["invalid_rows_skipped"] += 1
                continue

            records.append({
                "section": current_section,
                "raw_data": dict(canonical_data),   # same shape as canonical
                "canonical": canonical_data,
                "ocr_confidence": (
                    sum(b.get("confidence", 0) for b in row) / len(row)
                    if row else 0.0
                ),
            })
            stats["rows_extracted"] += 1

    return records, stats


# ---------------------------------------------------------------------------
# Common output builder
# ---------------------------------------------------------------------------
def build_output_document(
    doc_entry: dict,
    records: list[dict],
    stats: dict,
    extraction_method: str,
) -> dict:
    """Wrap records + metadata into the standard raw JSON shape."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    total = len(records)
    with_product = sum(
        1 for r in records
        if r.get("canonical", {}).get("product_name", "").strip()
    )
    with_batch = sum(
        1 for r in records
        if r.get("canonical", {}).get("batch_no", "").strip()
    )

    return {
        "document": {
            "document_id": doc_entry["document_id"],
            "source_file": doc_entry["filename"],
            "document_type": "NSQ_ALERT",
            "source_category": (
                doc_entry["sources"][0] if doc_entry["sources"] else None
            ),
            "sources": doc_entry["sources"],
            "pdf_paths": doc_entry["pdf_paths"],
            "pages": doc_entry["pages"],
            "content_type": doc_entry["content_type"],
            "text_origin": doc_entry["text_origin"],
        },
        "extraction": {
            "extraction_method": extraction_method,
            "status": "SUCCESS" if records else "EMPTY",
            "extracted_at": now,
            "raw_stats": stats,
        },
        "validation": {
            "records_extracted": total,
            "records_with_product": with_product,
            "records_with_batch": with_batch,
            "records_missing_product": total - with_product,
            "records_missing_batch": total - with_batch,
        },
        "records": [
            {
                "record_type": "NSQ",
                "section": r.get("section"),
                **({"ocr_confidence": r["ocr_confidence"]}
                   if "ocr_confidence" in r else {}),
                "raw_data": r["raw_data"],
                "canonical": r.get("canonical", {}),
            }
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Per-document dispatch
# ---------------------------------------------------------------------------
def _try_ocr_fallback(doc_entry: dict) -> tuple[list[dict], dict]:
    """Look for an OCR blocks.json sibling across all source folders."""
    stem = Path(doc_entry["filename"]).stem
    for src in doc_entry["sources"]:
        ocr_blk = (
            REPO_ROOT / "raw_extraction" / "ocr_tesseract"
            / src / f"{stem}.blocks.json"
        )
        if ocr_blk.exists():
            return extract_from_blocks_json(ocr_blk)
    return [], {}


def process_one(doc_entry: dict) -> dict:
    """Extract records from one NSQ document, return the output JSON."""
    content_type = doc_entry["content_type"]
    extra_path = doc_entry.get("extra_path")

    records: list[dict] = []
    stats: dict = {}
    method = "NONE"

    if content_type == "TEXT" and extra_path:
        tables_path = REPO_ROOT / extra_path
        records, stats = extract_from_tables_json(tables_path)
        method = "PDF_TEXT_TABLE"

        if not records:
            fallback_records, fallback_stats = _try_ocr_fallback(doc_entry)
            if fallback_records:
                records, stats = fallback_records, fallback_stats
                method = "OCR_BLOCKS_FALLBACK"

    elif content_type == "SCANNED" and extra_path:
        blocks_path = REPO_ROOT / extra_path
        records, stats = extract_from_blocks_json(blocks_path)
        method = "OCR_BLOCKS"

    elif content_type == "MIXED":
        if extra_path:
            p = REPO_ROOT / extra_path
            if p.name.endswith(".tables.json"):
                records, stats = extract_from_tables_json(p)
                method = "PDF_TEXT_TABLE"
            elif p.name.endswith(".blocks.json"):
                records, stats = extract_from_blocks_json(p)
                method = "OCR_BLOCKS"

        if not records:
            fallback_records, fallback_stats = _try_ocr_fallback(doc_entry)
            if fallback_records:
                records, stats = fallback_records, fallback_stats
                method = "OCR_BLOCKS_FALLBACK"

    else:
        stats = {"error": "no input path"}

    return build_output_document(doc_entry, records, stats, method)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Parse NSQ alert PDFs.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only first N documents (smoke test).")
    ap.add_argument("--files", nargs="+", default=None,
                    help="Only process these exact PDF filenames.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing outputs.")
    ap.add_argument("--only-text", action="store_true",
                    help="Skip SCANNED documents.")
    args = ap.parse_args()

    if not NSQ_MANIFEST.exists():
        print(f"[!] NSQ manifest not found: {NSQ_MANIFEST}")
        print("    Run scripts/type_classification.py first.")
        sys.exit(1)

    manifest = json.loads(NSQ_MANIFEST.read_text(encoding="utf-8"))
    docs = manifest.get("documents", [])

    if args.files:
        wanted = {f.lower() for f in args.files}
        docs = [d for d in docs if d["filename"].lower() in wanted]

    if args.only_text:
        docs = [d for d in docs if d["content_type"] == "TEXT"]

    if args.limit:
        docs = docs[: args.limit]

    print(f"[*] NSQ documents to process : {len(docs)}")
    print(f"[*] Output dir               : {OUTPUT_DIR}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    started = time.time()
    results = []

    for i, doc in enumerate(docs, 1):
        stem = Path(doc["filename"]).stem
        out_path = OUTPUT_DIR / f"{stem}.json"

        if out_path.exists() and not args.force:
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                n = existing.get("validation", {}).get("records_extracted", 0)
                print(f"[{i:>3}/{len(docs)}] SKIP  {stem[:55]:<55} records={n:>3}")
                results.append({
                    "document_id": doc["document_id"],
                    "filename": doc["filename"],
                    "status": "skipped",
                    "records": n,
                    "output": str(out_path.relative_to(REPO_ROOT)),
                })
            except Exception:
                pass
            continue

        try:
            result = process_one(doc)
            out_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            n = result["validation"]["records_extracted"]
            status = result["extraction"]["status"]
            method = result["extraction"]["extraction_method"]
            print(f"[{i:>3}/{len(docs)}] OK    {stem[:55]:<55} "
                  f"records={n:>3}  method={method}")

            results.append({
                "document_id": doc["document_id"],
                "filename": doc["filename"],
                "status": status,
                "content_type": doc["content_type"],
                "method": method,
                "records": n,
                "records_with_batch": result["validation"]["records_with_batch"],
                "output": str(out_path.relative_to(REPO_ROOT)),
            })

        except Exception as exc:
            print(f"[{i:>3}/{len(docs)}] ERR   {stem[:55]:<55} {exc}")
            results.append({
                "document_id": doc["document_id"],
                "filename": doc["filename"],
                "status": "ERROR",
                "error": str(exc),
            })

    elapsed = time.time() - started

    total_records = sum(r.get("records", 0) for r in results)
    ok = sum(1 for r in results if r.get("status") == "SUCCESS")
    empty = sum(1 for r in results if r.get("status") == "EMPTY")
    errors = sum(1 for r in results if r.get("status") == "ERROR")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    print()
    print("=" * 80)
    print(f"NSQ PARSE COMPLETE   ({elapsed:.1f}s)")
    print("=" * 80)
    print(f"  Documents total       : {len(docs)}")
    print(f"  Success               : {ok}")
    print(f"  Empty (no records)    : {empty}")
    print(f"  Errors                : {errors}")
    print(f"  Skipped (already done): {skipped}")
    print(f"  Total records         : {total_records}")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_documents": len(docs),
        "success": ok,
        "empty": empty,
        "errors": errors,
        "skipped": skipped,
        "total_records": total_records,
        "elapsed_sec": round(elapsed, 2),
        "documents": results,
    }
    (OUTPUT_DIR / "_manifest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print()
    print(f"[+] Manifest : {OUTPUT_DIR / '_manifest.json'}")
    print(f"[+] Output   : {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()