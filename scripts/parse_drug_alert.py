#!/usr/bin/env python3
"""
Drug Alert parser — the monthly "List of Drugs declared as NSQ/Spurious/
Adulterated/Misbranded" PDFs.

Same tabular structure as NSQ alerts but the "result" column can be
NSQ / Spurious / Misbranded / Adulterated. The parser preserves the
category per row via the `section` field.

Inputs:
    type_classification/drug_alert/_manifest.json
    raw_extraction/text/<src>/<name>.tables.json
    raw_extraction/ocr_tesseract/<src>/<name>.blocks.json

Outputs:
    structured_raw/drug_alert/<doc_id>.json
    structured_raw/drug_alert/_manifest.json
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
MANIFEST = REPO_ROOT / "type_classification" / "drug_alert" / "_manifest.json"
OUTPUT_DIR = REPO_ROOT / "structured_raw" / "drug_alert"


# ---------------------------------------------------------------------------
# Canonical column mapping
# ---------------------------------------------------------------------------
CANONICAL_KEYS = {
    "s_no":          ["s no", "s n", "s. no", "s.n.", "s no.", "sl no",
                      "sr no", "s.n", "sno"],
    "product_name":  [
        "product drug name", "product name", "name of drug",
        "name of drugs medical device cosmetics",
        "name of drugs", "drug name", "product",
        "name of drugs medical devices vaccine and cosmetics",
    ],
    "batch_no":      ["batch no", "batch no.", "batch number", "batch",
                      "b no", "b. no", "b no.", "bno"],
    "mfg_date":      [
        "manufacturing date", "manufacturing dt", "mfg date", "mfg dt",
        "date of manufacture", "manufacture date", "date of manufacture",
        "date of manufacturing", "manufacturing date.",
    ],
    "exp_date":      [
        "expiry date", "exp date", "exp dt", "expiry dt", "exp",
        "expiry date.", "date of expiry",
    ],
    "manufacturer":  [
        "manufactured by", "manufacturer", "mfg by", "manufacturer name",
        "manufactured by name", "manufactured by as per label",
        "manufacturer name and address",
    ],
    "nsq_result":    [
        "reason for failure", "failure reason", "reason", "nsq result",
        "result", "nature of failure", "reason for failure",
    ],
    "reported_by":   [
        "reported by cdsco laboratory", "reported by",
        "reported by lab", "reporting source", "reporting lab", "reported",
    ],
    "drawn_by":      ["drawn by"],
    "from_place":    ["from", "from place"],
    "firm_response": [
        "firm s reply", "firm's reply", "firm reply", "firm response",
        "response of original manufacturer",
    ],
    "remarks":       ["remarks", "remark"],
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
    n = normalize_header(header)
    if not n:
        return None
    if n in NORMALIZED_TO_CANONICAL:
        return NORMALIZED_TO_CANONICAL[n]
    compact = n.replace(" ", "")
    for variant, canon in NORMALIZED_TO_CANONICAL.items():
        if variant.replace(" ", "") == compact:
            return canon

    # Keyword fallback
    if "batch" in n:
        return "batch_no"
    if re.match(r"^s\s*\.?\s*n", n) or "sl no" in n or "sr no" in n or "sno" in n:
        return "s_no"
    if "product" in n or "name of drug" in n or ("name of" in n and "drug" in n):
        return "product_name"
    if "manufactur" in n and "date" in n:
        return "mfg_date"
    if ("expiry" in n or "exp date" in n) and "date" in n:
        return "exp_date"
    if "manufactur" in n and "by" in n:
        return "manufacturer"
    if "reason" in n or "failure" in n:
        return "nsq_result"
    if "drawn" in n:
        return "drawn_by"
    if "reported" in n or "reporting" in n:
        return "reported_by"
    if "firm" in n and ("reply" in n or "response" in n):
        return "firm_response"
    if "remark" in n:
        return "remarks"
    return None


# ---------------------------------------------------------------------------
# Fallback layouts by column count
# ---------------------------------------------------------------------------
FALLBACK_LAYOUTS: dict[int, tuple[list[str], list[str]]] = {
    8: (
        ["s_no", "product_name", "batch_no", "mfg_date", "exp_date",
         "manufacturer", "nsq_result", "reported_by"],
        ["S.No", "Name of Drugs", "Batch No.", "Date of Mfg", "Date of Exp",
         "Manufactured By", "Reason for failure", "Reported by"],
    ),
    9: (
        ["s_no", "product_name", "batch_no", "mfg_date", "exp_date",
         "manufacturer", "nsq_result", "firm_response", "reported_by"],
        ["S.No", "Name of Drugs", "Batch No.", "Date of Mfg", "Date of Exp",
         "Manufactured By", "Reason for failure", "Firm Reply", "Reported by"],
    ),
    10: (
        ["s_no", "product_name", "batch_no", "mfg_date", "exp_date",
         "manufacturer", "nsq_result", "drawn_by", "firm_response", "remarks"],
        ["S.No", "Name of Drugs", "Batch No.", "Date of Mfg", "Date of Exp",
         "Manufactured By", "Reason for failure", "Drawn By",
         "Firm's reply", "Remarks"],
    ),
}


def _guess_layout_by_shape(cells: list[str]) -> tuple[list[str], list[str]] | None:
    if not cells:
        return None
    first = cells[0].strip()
    if not re.match(r"^\d{1,4}\.?\d*$", first):
        return None
    non_empty = sum(1 for c in cells if c.strip())
    if non_empty < 3:
        return None
    return FALLBACK_LAYOUTS.get(len(cells))


# ---------------------------------------------------------------------------
# Section detection — CDSCO labels NSQ/Spurious/Misbranded as headers
# ---------------------------------------------------------------------------
SECTION_PATTERNS = [
    re.compile(r"^\s*[A-Z]\s*\.\s*", re.IGNORECASE),               # "A. CDSCO..."
    re.compile(r"\bcdsco\s+central\s+laborator", re.IGNORECASE),
    re.compile(r"\bstate\s+laborator", re.IGNORECASE),
    re.compile(r"\bcentral\s+laborator", re.IGNORECASE),
    re.compile(r"\bcdsco\s+labs?\b", re.IGNORECASE),
    # Category labels
    re.compile(r"^\s*not\s+of\s+standard\s+quality\s*$", re.IGNORECASE),
    re.compile(r"^\s*spurious\s*$", re.IGNORECASE),
    re.compile(r"^\s*misbranded\s*$", re.IGNORECASE),
    re.compile(r"^\s*adulterated\s*$", re.IGNORECASE),
    re.compile(r"^\s*sub[\s-]?standard\s*$", re.IGNORECASE),
]

PRODUCT_HINTS = ["tablet", "capsule", "injection", "syrup", "suspension",
                 "mg", "ml", "iu", "ointment", "cream", "gel", "powder",
                 "solution", "ip", "bp", "usp"]

HEADER_KEYWORDS = [
    "product", "batch", "b no", "b. no", "manufactur", "expiry",
    "exp date", "exp.", "s no", "s. no", "s.n",
    "reason", "reported", "drawn", "firm", "reply", "remark",
]


def is_section_row(cells: list[str]) -> bool:
    non_empty = [c.strip() for c in cells if c and c.strip()]
    if len(non_empty) != 1:
        return False
    first = non_empty[0]
    if len(first) > 120:
        return False
    lower = first.lower()
    if any(hint in lower for hint in PRODUCT_HINTS):
        return False
    return any(p.search(first) for p in SECTION_PATTERNS)


def is_header_row(cells: list[str]) -> bool:
    matched_keys: set[str] = set()
    for c in cells:
        if not c or not c.strip():
            continue
        k = canonical_key(c)
        if k:
            matched_keys.add(k)
    return len(matched_keys) >= 3


def _row_is_valid(canonical_data: dict[str, str]) -> bool:
    for key in ("s_no", "product_name", "batch_no", "nsq_result"):
        if canonical_data.get(key, "").strip():
            return True
    return False


def _is_continuation_row(canonical_data: dict[str, str]) -> bool:
    if canonical_data.get("s_no", "").strip():
        return False
    if canonical_data.get("batch_no", "").strip():
        return False
    return any(v.strip() for v in canonical_data.values())


# ---------------------------------------------------------------------------
# TEXT extraction (tables.json)
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

            if not header_keys:
                guessed = _guess_layout_by_shape(cells)
                if guessed:
                    header_keys, header_display = guessed
                    stats["shape_layout_used"] += 1
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

            if _is_continuation_row(canonical_data) and records:
                prev = records[-1]["canonical"]
                prev_raw = records[-1]["raw_data"]
                for key, val in canonical_data.items():
                    v = val.strip()
                    if not v:
                        continue
                    if prev.get(key, "").strip():
                        prev[key] = (prev[key] + " " + v).strip()
                    else:
                        prev[key] = v
                    for rk in list(prev_raw.keys()):
                        if canonical_key(rk) == key:
                            prev_raw[rk] = prev[key]
                            break
                    else:
                        prev_raw[key] = prev[key]
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
# OCR extraction (blocks.json) — reuse NSQ-style row clustering
# ---------------------------------------------------------------------------
def _cluster_rows(blocks: list[dict], y_tol_ratio: float = 0.6) -> list[list[dict]]:
    if not blocks:
        return []
    heights = sorted(b["y_bottom"] - b["y_top"]
                     for b in blocks if b["y_bottom"] > b["y_top"])
    median_h = heights[len(heights) // 2] if heights else 15.0
    y_tol = max(3.0, median_h * y_tol_ratio)
    sb = sorted(blocks, key=lambda b: (b["y_center"], b["x_left"]))
    rows: list[list[dict]] = []
    current: list[dict] = []
    yc: float | None = None
    for b in sb:
        if yc is None or abs(b["y_center"] - yc) <= y_tol:
            current.append(b)
            yc = sum(bb["y_center"] for bb in current) / len(current)
        else:
            current.sort(key=lambda bb: bb["x_left"])
            rows.append(current)
            current = [b]
            yc = b["y_center"]
    if current:
        current.sort(key=lambda bb: bb["x_left"])
        rows.append(current)
    return rows


def _detect_columns(header_row: list[dict]) -> list[tuple[float, str]]:
    cols: list[tuple[float, str]] = []
    seen: set[str] = set()
    sb = sorted(header_row, key=lambda b: b["x_left"])
    for i, b in enumerate(sb):
        text = b["text"].strip()
        if not text:
            continue
        k = canonical_key(text)
        if not k and i + 1 < len(sb):
            nt = sb[i + 1]["text"].strip()
            if nt:
                k = canonical_key(f"{text} {nt}")
        if k and k not in seen:
            cols.append((b["x_left"], k))
            seen.add(k)
    cols.sort(key=lambda x: x[0])
    return cols


def _assign_to_columns(row, columns) -> dict[str, str]:
    if not columns:
        return {}
    buckets: dict[str, list[str]] = {k: [] for _, k in columns}
    boundaries = [(columns[i - 1][0] + columns[i][0]) / 2.0
                  for i in range(1, len(columns))]
    for b in row:
        text = b["text"].strip()
        if not text:
            continue
        x = b["x_left"]
        idx = 0
        for i, bnd in enumerate(boundaries):
            if x >= bnd:
                idx = i + 1
            else:
                break
        buckets[columns[idx][1]].append(text)
    return {k: " ".join(v) for k, v in buckets.items() if v}


def extract_from_blocks_json(blocks_path: Path) -> tuple[list[dict], dict]:
    if not blocks_path.exists():
        return [], {"error": "blocks.json missing"}
    try:
        pages = json.loads(blocks_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], {"error": f"json parse failed: {exc}"}

    records: list[dict] = []
    stats = {"pages_read": 0, "rows_seen": 0, "rows_extracted": 0,
             "header_rows_skipped": 0, "invalid_rows_skipped": 0,
             "sections": []}

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
# PROSE fallback — for non-tabular drug-alert documents (advisories, revised
# pointers, notices). Same shape as the prose records used elsewhere.
# ---------------------------------------------------------------------------
NOTIF_RE = re.compile(
    r"(?:(?:S\.O\.|G\.S\.R\.|F\.No\.|File\s+No\.)\s*[\w./-]+"
    r"(?:\s*to\s*(?:S\.O\.|G\.S\.R\.)\s*[\w./-]+)?)",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

ACTION_KEYWORDS = {
    "prohibition": ["prohibit", "prohibited", "prohibition", "ban", "banned", "banning"],
    "restriction": ["restrict", "restricted", "restriction"],
    "approval": ["approv", "approval", "grant of"],
    "revocation": ["revoke", "revoked", "revocation", "cancel", "cancellation"],
    "recall": ["recall", "voluntary recall", "product recall"],
    "theft": ["theft", "stolen", "stolen product"],
    "alert": ["alert", "advisory", "caution"],
    "amendment": ["amend", "amendment", "insert", "substitution"],
}

QUALITY_HINTS = [
    "not of standard", "spurious", "adulterated", "misbranded",
    "defective", "sub standard", "substandard",
]


def _detect_actions(text: str) -> list[str]:
    head = text[:3000].lower()
    return [action for action, keywords in ACTION_KEYWORDS.items()
            if any(keyword in head for keyword in keywords)]


def _detect_quality_flags(text: str) -> list[str]:
    head = text[:5000].lower()
    return [keyword for keyword in QUALITY_HINTS if keyword in head]


def _extract_subject(text: str, max_len: int = 300) -> str:
    for line in text.splitlines()[:60]:
        line = line.strip()
        if not line or line.startswith("====="):
            continue
        if len(line) < 25:
            continue
        if line.lower().startswith(("page ", "sl no", "s no", "s. no")):
            continue
        return line[:max_len]
    return ""


def build_prose_record_from_text(text: str) -> dict:
    head = text[:5000]
    notif_numbers = sorted({
        re.sub(r"[.,;:]+$", "", match.group(0).strip())
        for match in NOTIF_RE.finditer(head)
    })
    dates = sorted({match.group(0).strip() for match in DATE_RE.finditer(head)})
    subject = _extract_subject(text)
    actions = _detect_actions(text)
    quality_flags = _detect_quality_flags(text)

    canonical = {
        "subject": subject,
        "notification_number": "; ".join(notif_numbers[:10]),
        "notification_date": dates[0] if dates else "",
        "actions": ", ".join(actions),
        "quality_flags": ", ".join(quality_flags),
    }
    raw_data = dict(canonical)
    raw_data["all_notification_numbers"] = notif_numbers
    raw_data["all_dates"] = dates

    return {
        "record_type": "DRUG_ALERT_NARRATIVE",
        "section": None,
        "raw_data": raw_data,
        "canonical": canonical,
        "prose": True,
    }


def extract_from_text_file(text_path: Path) -> tuple[list[dict], dict]:
    if not text_path.exists():
        return [], {"error": "text missing"}
    text = text_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return [], {"error": "empty text"}
    record = build_prose_record_from_text(text)
    stats = {
        "text_chars": len(text),
        "rows_extracted": 1,
        "prose_fallback": True,
        "actions_found": record["canonical"]["actions"],
        "notification_numbers_found": len(record["raw_data"]["all_notification_numbers"]),
    }
    return [record], stats


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
    return {
        "document": {
            "document_id": doc_entry["document_id"],
            "source_file": doc_entry["filename"],
            "document_type": "DRUG_ALERT",
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
            "records_missing_product": total - with_product,
            "records_missing_batch": total - with_batch,
        },
        "records": [
            {
                "record_type": r.get("record_type", "DRUG_ALERT"),
                "section": r.get("section"),
                **({"ocr_confidence": r["ocr_confidence"]}
                   if "ocr_confidence" in r else {}),
                "raw_data": r["raw_data"],
                "canonical": r.get("canonical", {}),
            }
            for r in records
        ],
    }


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
    text_path = doc_entry.get("text_source_path")
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

    if not records and text_path:
        p = REPO_ROOT / text_path
        if p.exists():
            prose_records, prose_stats = extract_from_text_file(p)
            if prose_records:
                prose_stats["tables_attempted"] = method != "NONE"
                prose_stats["tables_method"] = method
                records = prose_records
                stats = prose_stats
                method = "PROSE_FALLBACK"

    return build_output_document(doc_entry, records, stats, method)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Parse drug_alert PDFs.")
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

    print(f"[*] Drug alert documents to process : {len(docs)}")
    print(f"[*] Output dir                      : {OUTPUT_DIR}")
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
                print(f"[{i:>4}/{len(docs)}] SKIP  {stem[:60]:<60} records={n:>4}")
                results.append({"document_id": doc["document_id"],
                                "filename": doc["filename"],
                                "status": "skipped", "records": n})
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
            m = result["extraction"]["extraction_method"]
            print(f"[{i:>4}/{len(docs)}] OK    {stem[:60]:<60} "
                  f"records={n:>4}  method={m}")
            results.append({
                "document_id": doc["document_id"],
                "filename": doc["filename"],
                "status": result["extraction"]["status"],
                "method": m,
                "records": n,
                "output": str(out_path.relative_to(REPO_ROOT)),
            })
        except Exception as exc:
            print(f"[{i:>4}/{len(docs)}] ERR   {stem[:60]:<60} {exc}")
            results.append({"document_id": doc["document_id"],
                            "filename": doc["filename"],
                            "status": "ERROR", "error": str(exc)})

    elapsed = time.time() - started
    total_records = sum(r.get("records", 0) for r in results)
    ok = sum(1 for r in results if r.get("status") == "SUCCESS")
    empty = sum(1 for r in results if r.get("status") == "EMPTY")
    errors = sum(1 for r in results if r.get("status") == "ERROR")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    print()
    print("=" * 80)
    print(f"DRUG ALERT PARSE COMPLETE   ({elapsed:.1f}s)")
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


if __name__ == "__main__":
    main()