#!/usr/bin/env python3
"""
Spurious parser — extracts structured records from spurious drug alert PDFs.

Handles multiple spurious alert layouts (8/9/10 columns).
RAW — no normalization.

Inputs:
    type_classification/spurious_alert/_manifest.json
    raw_extraction/text/<src>/<name>.tables.json
    raw_extraction/ocr_tesseract/<src>/<name>.blocks.json

Outputs:
    structured_raw/spurious/<document_id>.json
    structured_raw/spurious/_manifest.json
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
REPO_ROOT = SCRIPTS_DIR.parent
MANIFEST = REPO_ROOT / "type_classification" / "spurious_alert" / "_manifest.json"
OUTPUT_DIR = REPO_ROOT / "structured_raw" / "spurious"


# ---------------------------------------------------------------------------
# Canonical column mapping
# ---------------------------------------------------------------------------
CANONICAL_KEYS = {
    "s_no":          ["s no", "s n", "s. no", "s.n.", "s no.", "sl no", "sr no", "s.n", "sno"],
    "product_name":  [
        "product drug name", "product name", "name of drug",
        "name of drugs medical device cosmetics",
        "name of drugs", "drug name", "product",
    ],
    "batch_no":      ["batch no", "batch no.", "batch number", "batch", "b no", "b. no", "b no.", "bno"],
    "mfg_date":      [
        "manufacturing date", "manufacturing dt", "mfg date", "mfg dt",
        "date of manufacture", "manufacture date", "manufacturing date.",
    ],
    "exp_date":      [
        "expiry date", "exp date", "exp dt", "expiry dt", "exp",
        "expiry date.", "date of expiry", "date of exp",
    ],
    "manufacturer":  [
        "manufactured by", "manufacturer", "mfg by", "manufacturer name",
        "manufactured by name", "manufactured by as per label",
        "manufacturer name and address", "manufactured by as per label claim",
    ],
    "nsq_result":    [
        "reason for failure", "failure reason", "reason", "nsq result",
        "result", "nature of failure",
    ],
    "sales_outlets": [
        "sales outlets involved in distribution of spurious drugs",
        "sales outlets involved", "sales outlets", "outlets involved",
    ],
    "firm_response": [
        "response of original manufacturer stating how to identify the original product from reported spurious product",
        "response of original manufacturer", "response of manufacturer",
        "firm response", "firm s reply", "firms reply", "firm's reply",
        "firm reply", "manufacturer response",
    ],
    "reported_by":   [
        "reported by cdsco state manufacturer", "reported by cdsco state",
        "reported by", "reported",
    ],
    "drawn_by":      ["drawn by"],
    "remarks":       ["remarks", "remark"],
    "testing_lab":   ["testing lab", "lab"],
}

NORMALIZED_TO_CANONICAL: dict[str, str] = {}
for canonical, variants in CANONICAL_KEYS.items():
    for variant in variants:
        NORMALIZED_TO_CANONICAL[variant] = canonical


def normalize_header(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip().lower()
    s = re.sub(r"[\W_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_key(header: str) -> str | None:
    """3-tier header matching: exact → compact → keyword."""
    n = normalize_header(header)
    if not n:
        return None

    if n in NORMALIZED_TO_CANONICAL:
        return NORMALIZED_TO_CANONICAL[n]

    compact = n.replace(" ", "")
    for variant, canon in NORMALIZED_TO_CANONICAL.items():
        if variant.replace(" ", "") == compact:
            return canon

    if "sales outlet" in n or "outlet involved" in n:
        return "sales_outlets"
    if "response of" in n and ("manufactur" in n or "original" in n):
        return "firm_response"
    if ("firm" in n and ("response" in n or "reply" in n)) or "firm response" in n:
        return "firm_response"
    if "remark" in n:
        return "remarks"
    if "batch" in n or re.match(r"^b\s*\.?\s*n\b", n):
        return "batch_no"
    if re.match(r"^s\s*\.?\s*n", n) or "sl no" in n or "sr no" in n or "sno" in n:
        return "s_no"
    if "product" in n or "name of drug" in n or ("name of" in n and "drug" in n):
        return "product_name"
    if "manufactur" in n and "date" in n:
        return "mfg_date"
    if ("expiry" in n or "exp date" in n or re.search(r"\bexp\b", n)) and "date" in n:
        return "exp_date"
    if "manufactur" in n and "by" in n:
        return "manufacturer"
    if "reason" in n or "failure" in n:
        return "nsq_result"
    if "drawn" in n:
        return "drawn_by"
    if "reported" in n or "reporting" in n:
        return "reported_by"

    return None


# ---------------------------------------------------------------------------
# Fallback layouts (multi-version support)
# ---------------------------------------------------------------------------
FALLBACK_LAYOUTS: dict[int, tuple[list[str], list[str]]] = {
    8: (
        ["s_no", "product_name", "batch_no", "mfg_date", "exp_date",
         "manufacturer", "nsq_result", "reported_by"],
        ["S.No", "Name of Drugs/medical device/cosmetics", "Batch No.",
         "Date of Manufacture", "Date of Expiry", "Manufactured By",
         "Reason for failure", "Reported by"],
    ),
    9: (
        ["s_no", "product_name", "batch_no", "mfg_date", "exp_date",
         "manufacturer", "sales_outlets", "firm_response", "reported_by"],
        ["S. No.", "Product/Drug Name", "B. No.", "Manufacturing Date",
         "Expiry Date", "Manufactured By as per label",
         "Sales Outlets Involved in Distribution of Spurious Drugs",
         "Response of Original Manufacturer",
         "Reported by CDSCO/State/Manufacturer"],
    ),
    10: (
        ["s_no", "product_name", "batch_no", "mfg_date", "exp_date",
         "manufacturer", "nsq_result", "drawn_by", "firm_response", "reported_by"],
        ["S.No.", "Name of Drugs/medical device/cosmetics", "Batch No.",
         "Date of Manufacture", "Date of Expiry", "Manufactured By",
         "Reason for failure", "Drawn By", "Firm's reply", "Remarks"],
    ),
}


def _guess_layout_by_shape(cells: list[str]) -> tuple[list[str], list[str]] | None:
    """
    Detect layout from row shape.
    Requires: numeric first cell (S.No) AND ≥4 non-empty cells.
    """
    if not cells:
        return None
    first = cells[0].strip()
    if not re.match(r"^\d{1,4}\.?\d*$", first):
        return None
    non_empty = sum(1 for c in cells if c.strip())
    if non_empty < 4:
        return None
    return FALLBACK_LAYOUTS.get(len(cells))


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------
STATE_HINT_PATTERNS = [
    re.compile(r"^\s*(NCT\s+of\s+DELHI|DELHI)\s*$", re.IGNORECASE),
    re.compile(r"^\s*MAHARASHTRA\s*$", re.IGNORECASE),
    re.compile(r"^\s*GUJARAT\s*$", re.IGNORECASE),
    re.compile(r"^\s*KARNATAKA\s*$", re.IGNORECASE),
    re.compile(r"^\s*TAMIL\s+NADU\s*$", re.IGNORECASE),
    re.compile(r"^\s*UTTAR\s+PRADESH\s*$", re.IGNORECASE),
    re.compile(r"^\s*WEST\s+BENGAL\s*$", re.IGNORECASE),
    re.compile(r"^\s*RAJASTHAN\s*$", re.IGNORECASE),
    re.compile(r"^\s*PUNJAB\s*$", re.IGNORECASE),
    re.compile(r"^\s*HARYANA\s*$", re.IGNORECASE),
    re.compile(r"^\s*KERALA\s*$", re.IGNORECASE),
    re.compile(r"^\s*TELANGANA\s*$", re.IGNORECASE),
    re.compile(r"^\s*ANDHRA\s+PRADESH\s*$", re.IGNORECASE),
    re.compile(r"^\s*MADHYA\s+PRADESH\s*$", re.IGNORECASE),
    re.compile(r"^\s*HIMACHAL\s+PRADESH\s*$", re.IGNORECASE),
    re.compile(r"^\s*UTTARAKHAND\s*$", re.IGNORECASE),
    re.compile(r"^\s*BIHAR\s*$", re.IGNORECASE),
    re.compile(r"^\s*JHARKHAND\s*$", re.IGNORECASE),
    re.compile(r"^\s*ODISHA\s*$", re.IGNORECASE),
    re.compile(r"^\s*ASSAM\s*$", re.IGNORECASE),
    re.compile(r"^\s*GOA\s*$", re.IGNORECASE),
    re.compile(r"^\s*CHANDIGARH\s*$", re.IGNORECASE),
    re.compile(r"^\s*JAMMU\s*(and|&)?\s*KASHMIR\s*$", re.IGNORECASE),
    re.compile(r"^\s*STATE\s*$", re.IGNORECASE),
    re.compile(r"^\s*[A-Z]\s*\.\s*", re.IGNORECASE),
]

PRODUCT_HINTS = [
    "tablet", "capsule", "injection", "syrup", "suspension",
    "mg", "ml", "iu", "ointment", "cream", "gel", "powder",
    "solution", "ip", "bp", "usp",
]

HEADER_KEYWORDS = [
    "product", "batch", "b no", "b. no", "manufactur", "expiry",
    "exp date", "exp.", "s no", "s. no", "s.n",
    "sales", "outlet", "reported", "response",
    "name of", "drugs", "failure", "reason",
    "firm", "reply", "remark", "drawn",
]

# Anchors that MUST appear in a header row (at least one)
HEADER_ANCHORS = [
    "s no", "s. no", "s.n", "s n", "sno",
    "batch", "b no", "b. no", "b no.",
    "product", "name of drugs", "name of drug",
]


def is_section_row(cells: list[str]) -> bool:
    non_empty = [c.strip() for c in cells if c and c.strip()]
    if len(non_empty) != 1:
        return False
    first = non_empty[0]
    if len(first) > 80:
        return False
    lower = first.lower()
    if any(hint in lower for hint in PRODUCT_HINTS):
        return False
    if any(p.search(first) for p in STATE_HINT_PATTERNS):
        return True
    if first.isupper() and not re.search(r"\d", first) and len(first) < 60:
        return True
    return False


def is_header_row(cells: list[str]) -> bool:
    """
    A real header row has ≥3 DISTINCT cells that map to canonical keys.
    Uses canonical_key() which handles:
      - exact matches ("Batch No.")
      - compact matches ("S.N\n o" → "sno", "Date\nof\nManuf\nacture" → "dateofmanufacture")
      - keyword fallbacks ("Firm reply" → firm_response)
    """
    matched_keys: set[str] = set()
    for c in cells:
        if not c or not c.strip():
            continue
        key = canonical_key(c)
        if key:
            matched_keys.add(key)
    return len(matched_keys) >= 3


def _row_is_valid(canonical_data: dict[str, str]) -> bool:
    """
    A real spurious record has:
      - A product name (≥5 chars)
      - AND a numeric S.No OR a batch number
    """
    s_no = canonical_data.get("s_no", "").strip()
    batch = canonical_data.get("batch_no", "").strip()
    product = canonical_data.get("product_name", "").strip()

    has_product = len(product) >= 5
    has_sno = bool(re.match(r"^\d{1,4}\.?\d*$", s_no))
    has_batch = len(batch) >= 3

    return has_product and (has_sno or has_batch)


def _is_continuation_row(canonical_data: dict[str, str]) -> bool:
    """
    A continuation row has no s_no and no batch_no, but has content in
    other columns. These are wrapped product names / addresses that
    belong to the PREVIOUS record.
    """
    s_no = canonical_data.get("s_no", "").strip()
    batch = canonical_data.get("batch_no", "").strip()
    if s_no or batch:
        return False
    return any(v.strip() for v in canonical_data.values())


# ---------------------------------------------------------------------------
# TEXT extraction
# ---------------------------------------------------------------------------
def extract_from_tables_json(tables_path: Path) -> tuple[list[dict], dict]:
    if not tables_path.exists():
        return [], {"error": "tables.json missing"}

    try:
        tables = json.loads(tables_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], {"error": f"json parse failed: {exc}"}

    records: list[dict] = []
    stats = {
        "tables_read": 0, "rows_seen": 0, "rows_extracted": 0,
        "section_rows_skipped": 0, "header_rows_skipped": 0,
        "empty_rows_skipped": 0, "invalid_rows_skipped": 0,
        "shape_layout_used": 0, "continuation_rows_merged": 0,
        "sections": [],
    }

    current_section: str | None = None
    header_keys: list[str] = []
    header_display: list[str] = []

    for tbl in tables:
        rows = tbl.get("rows", [])
        if not rows:
            continue
        stats["tables_read"] += 1

        for row in rows:
            stats["rows_seen"] += 1
            cells = [str(c) if c is not None else "" for c in row]

            if not any(c.strip() for c in cells):
                stats["empty_rows_skipped"] += 1
                continue

            if is_section_row(cells):
                current_section = next((c.strip() for c in cells if c.strip()), None)
                if current_section and current_section not in stats["sections"]:
                    stats["sections"].append(current_section)
                stats["section_rows_skipped"] += 1
                continue

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

            # Data row
            if not header_keys:
                guessed = _guess_layout_by_shape(cells)
                if guessed:
                    header_keys, header_display = guessed
                    stats["shape_layout_used"] += 1
                elif len(cells) in FALLBACK_LAYOUTS:
                    # Only use count-only fallback if row starts with digit
                    if re.match(r"^\d{1,4}\.?\d*$", cells[0].strip()):
                        header_keys, header_display = FALLBACK_LAYOUTS[len(cells)]
                        stats["shape_layout_used"] += 1
                    else:
                        stats["invalid_rows_skipped"] += 1
                        continue
                else:
                    stats["invalid_rows_skipped"] += 1
                    continue

            raw_data: dict[str, str] = {}
            canonical_data: dict[str, str] = {}
            for i, cell in enumerate(cells):
                if i >= len(header_keys):
                    break
                canon = header_keys[i]
                display = (header_display[i] if i < len(header_display)
                           and header_display[i] else canon)
                value = cell.rstrip()
                raw_data[display] = value
                if not canon.startswith("unknown_"):
                    canonical_data[canon] = value

            # Continuation row — merge into previous record
            if _is_continuation_row(canonical_data) and records:
                prev_canon = records[-1]["canonical"]
                prev_raw = records[-1]["raw_data"]
                for key, val in canonical_data.items():
                    v = val.strip()
                    if not v:
                        continue
                    if prev_canon.get(key, "").strip():
                        prev_canon[key] = (prev_canon[key] + " " + v).strip()
                    else:
                        prev_canon[key] = v
                    for rk in list(prev_raw.keys()):
                        if canonical_key(rk) == key:
                            prev_raw[rk] = prev_canon[key]
                            break
                    else:
                        prev_raw[key] = prev_canon[key]
                stats["continuation_rows_merged"] += 1
                continue

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
# SCANNED extraction
# ---------------------------------------------------------------------------
def _cluster_rows(blocks: list[dict], y_tol_ratio: float = 0.6) -> list[list[dict]]:
    if not blocks:
        return []
    heights = sorted(b["y_bottom"] - b["y_top"]
                     for b in blocks if b["y_bottom"] > b["y_top"])
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
    cols: list[tuple[float, str]] = []
    seen: set[str] = set()
    sorted_blocks = sorted(header_row, key=lambda b: b["x_left"])
    for i, b in enumerate(sorted_blocks):
        text = b["text"].strip()
        if not text:
            continue
        key = canonical_key(text)
        if not key and i + 1 < len(sorted_blocks):
            next_text = sorted_blocks[i + 1]["text"].strip()
            if next_text:
                key = canonical_key(f"{text} {next_text}")
        if key and key not in seen:
            cols.append((b["x_left"], key))
            seen.add(key)
    cols.sort(key=lambda x: x[0])
    return cols


def _assign_to_columns(row: list[dict],
                       columns: list[tuple[float, str]]) -> dict[str, str]:
    if not columns:
        return {}
    buckets: dict[str, list[str]] = {key: [] for _, key in columns}
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
    if not blocks_path.exists():
        return [], {"error": "blocks.json missing"}
    try:
        pages = json.loads(blocks_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], {"error": f"json parse failed: {exc}"}

    records: list[dict] = []
    stats = {
        "pages_read": 0, "rows_seen": 0, "rows_extracted": 0,
        "header_rows_skipped": 0, "invalid_rows_skipped": 0,
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

            if not columns:
                detected = _detect_columns(row)
                if detected and len(detected) >= 4:
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
                "raw_data": dict(canonical_data),
                "canonical": canonical_data,
                "ocr_confidence": (
                    sum(b.get("confidence", 0) for b in row) / len(row)
                    if row else 0.0
                ),
            })
            stats["rows_extracted"] += 1

    return records, stats


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------
def build_output_document(doc_entry, records, stats, method) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = len(records)
    with_product = sum(1 for r in records
                       if r.get("canonical", {}).get("product_name", "").strip())
    with_batch = sum(1 for r in records
                     if r.get("canonical", {}).get("batch_no", "").strip())
    with_outlets = sum(1 for r in records
                       if r.get("canonical", {}).get("sales_outlets", "").strip())

    return {
        "document": {
            "document_id": doc_entry["document_id"],
            "source_file": doc_entry["filename"],
            "document_type": "SPURIOUS_ALERT",
            "source_category": doc_entry["sources"][0] if doc_entry["sources"] else None,
            "sources": doc_entry["sources"],
            "pdf_paths": doc_entry["pdf_paths"],
            "pages": doc_entry["pages"],
            "content_type": doc_entry["content_type"],
            "text_origin": doc_entry["text_origin"],
        },
        "extraction": {
            "extraction_method": method,
            "status": "SUCCESS" if records else "EMPTY",
            "extracted_at": now,
            "raw_stats": stats,
        },
        "validation": {
            "records_extracted": total,
            "records_with_product": with_product,
            "records_with_batch": with_batch,
            "records_with_sales_outlets": with_outlets,
            "records_missing_product": total - with_product,
            "records_missing_batch": total - with_batch,
        },
        "records": [
            {
                "record_type": "SPURIOUS",
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
# Dispatch
# ---------------------------------------------------------------------------
def _try_ocr_fallback(doc_entry):
    stem = Path(doc_entry["filename"]).stem
    for src in doc_entry["sources"]:
        ocr_blk = (REPO_ROOT / "raw_extraction" / "ocr_tesseract"
                   / src / f"{stem}.blocks.json")
        if ocr_blk.exists():
            return extract_from_blocks_json(ocr_blk)
    return [], {}


def process_one(doc_entry) -> dict:
    content_type = doc_entry["content_type"]
    extra_path = doc_entry.get("extra_path")

    records: list[dict] = []
    stats: dict = {}
    method = "NONE"

    if content_type == "TEXT" and extra_path:
        records, stats = extract_from_tables_json(REPO_ROOT / extra_path)
        method = "PDF_TEXT_TABLE"
        if not records:
            fb_r, fb_s = _try_ocr_fallback(doc_entry)
            if fb_r:
                records, stats, method = fb_r, fb_s, "OCR_BLOCKS_FALLBACK"

    elif content_type == "SCANNED" and extra_path:
        records, stats = extract_from_blocks_json(REPO_ROOT / extra_path)
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
            fb_r, fb_s = _try_ocr_fallback(doc_entry)
            if fb_r:
                records, stats, method = fb_r, fb_s, "OCR_BLOCKS_FALLBACK"

    else:
        stats = {"error": "no input path"}

    return build_output_document(doc_entry, records, stats, method)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Parse spurious alert PDFs.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--files", nargs="+", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"[!] Manifest not found: {MANIFEST}")
        sys.exit(1)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    docs = manifest.get("documents", [])

    if args.files:
        wanted = {f.lower() for f in args.files}
        docs = [d for d in docs if d["filename"].lower() in wanted]

    if args.limit:
        docs = docs[: args.limit]

    print(f"[*] Spurious documents to process : {len(docs)}")
    print(f"[*] Output dir                    : {OUTPUT_DIR}")
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
                print(f"[{i:>3}/{len(docs)}] SKIP  {stem[:60]:<60} records={n:>3}")
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
            print(f"[{i:>3}/{len(docs)}] OK    {stem[:60]:<60} "
                  f"records={n:>3}  method={method}")
            results.append({
                "document_id": doc["document_id"],
                "filename": doc["filename"],
                "status": status,
                "content_type": doc["content_type"],
                "method": method,
                "records": n,
                "records_with_batch": result["validation"]["records_with_batch"],
                "records_with_sales_outlets": result["validation"]["records_with_sales_outlets"],
                "output": str(out_path.relative_to(REPO_ROOT)),
            })
        except Exception as exc:
            print(f"[{i:>3}/{len(docs)}] ERR   {stem[:60]:<60} {exc}")
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
    print(f"SPURIOUS PARSE COMPLETE   ({elapsed:.1f}s)")
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
        "success": ok, "empty": empty, "errors": errors, "skipped": skipped,
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