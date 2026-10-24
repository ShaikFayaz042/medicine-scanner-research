#!/usr/bin/env python3
"""Inventory unique table schemas — V3 with strict English-only validation.

Key fixes vs V2:
  1. pymupdf `text` strategy DROPPED — it treats aligned Devanagari text
     as tables. Only `lines` strategy used (reliable, needs visible borders).
  2. pdfplumber fallback for borderless tables (English-only validated).
  3. is_junk_cell(): rejects "", "-", "|", "a", "1", ".", ":", pure punctuation.
  4. ascii_ratio(): rejects any header/data with >15% non-ASCII (Hindi/Devanagari).
  5. Header must have >= 2 real cells, each >= 3 chars.
  6. Data rows: >= 2 rows with >= 2 populated non-junk cells.
  7. Junk ratio check: if >50% cells in a table are junk -> reject.
  8. Rejected tables logged separately with reason codes.
  9. Quality score per schema: HIGH/MEDIUM/LOW based on docs + rows.
 10. Fixed HEADER_CANON key canonicalization (bug in V2).

Outputs:
  unique_table_schemas.csv       — valid schemas, sorted by doc count
  table_schema_occurrences.csv   — per-(schema, pdf, page) detail
  unique_table_schemas.json      — nested JSON
  rejected_tables.csv            — tables rejected, with reason code
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import pymupdf
except ImportError:
    sys.exit("ERROR: pip install pymupdf")

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = SCRIPT_DIR / "full_corpus_classified.csv"
DEFAULT_ROOT = SCRIPT_DIR
DEFAULT_OUT = SCRIPT_DIR / "unique_table_schemas.csv"
DEFAULT_OUT_OCC = SCRIPT_DIR / "table_schema_occurrences.csv"
DEFAULT_OUT_JSON = SCRIPT_DIR / "unique_table_schemas.json"
DEFAULT_OUT_REJ = SCRIPT_DIR / "rejected_tables.csv"


# ============================================================
# NORMALIZATION
# ============================================================
WHITESPACE = re.compile(r"\s+")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
NUMBER_ONLY = re.compile(r"[\d.\-/]+")

_RAW_CANON = {
    # Serial
    "s no": "sno", "s no.": "sno", "s.no": "sno", "s.no.": "sno",
    "s. no": "sno", "s. no.": "sno", "sr no": "sno", "sr no.": "sno",
    "sr.no": "sno", "sr.no.": "sno", "sl no": "sno", "sl no.": "sno",
    "sl.no": "sno", "sl.no.": "sno", "sl. no": "sno", "sl. no.": "sno",
    "s n": "sno", "s n.": "sno", "s.n.": "sno", "s.n o": "sno",
    "serial no": "sno", "serial no.": "sno", "serial number": "sno",
    "sr number": "sno",
    # Product
    "name of drugs": "product_name", "name of drug": "product_name",
    "name of the drug": "product_name", "name of the drugs": "product_name",
    "product name": "product_name", "product/drug name": "product_name",
    "drug name": "product_name", "drugs name": "product_name",
    "name of drugs/medical device/cosmetics": "product_name",
    "name of the drug/ medical device/ cosmetic": "product_name",
    "name of drugs/medical device/cosmetic s": "product_name",
    "name of drugs/medical device/cosmeti cs": "product_name",
    # Batch
    "batch no": "batch_no", "batch no.": "batch_no",
    "batch number": "batch_no", "b.no": "batch_no", "b.no.": "batch_no",
    "b no": "batch_no", "b. no.": "batch_no",
    # Dates
    "mfg date": "mfg_date", "mfg dt": "mfg_date",
    "date of manufacture": "mfg_date", "manufacturing date": "mfg_date",
    "date of manufa cture": "mfg_date", "date of manufactur e": "mfg_date",
    "date of manufactu re": "mfg_date", "manufact uring date": "mfg_date",
    "exp date": "exp_date", "exp dt": "exp_date",
    "date of expiry": "exp_date", "expiry date": "exp_date",
    # Manufacturer
    "manufactured by": "manufacturer", "mfg by": "manufacturer",
    "mfd by": "manufacturer", "manufacturer": "manufacturer",
    "manufactured by as per label": "manufacturer",
    # Reason
    "reason for failure": "failure_reason", "reasons for failure": "failure_reason",
    "reason for failure with report no": "failure_reason",
    "reasons for failure with report": "failure_reason",
    # Drawn / reported
    "drawn by": "drawn_by", "reported by": "reported_by",
    "reported by cdsco laboratory": "reported_by",
    "reported by state laboratory": "reported_by",
    "drawn by (from state/cdsco zone)": "drawn_by",
    # From / lab
    "from": "from", "from (name of laboratory)": "from",
    "from (name of the laboratory)": "from",
    # NSQ
    "nsq result": "nsq_result", "nsq results": "nsq_result",
    # Remarks / reply
    "remarks": "remarks", "remark": "remarks",
    "firm's reply": "firms_reply", "firms reply": "firms_reply",
    "firm reply": "firms_reply", "firm’s reply": "firms_reply",
    "firms’s reply": "firms_reply",
    # Device
    "device name": "device_name", "medical device name": "device_name",
    "name of the medical device": "device_name",
    "name of the medical devices": "device_name",
    "intended use": "intended_use", "inteded use": "intended_use",
    "risk class": "risk_class", "risk classification": "risk_class",
    # NOC
    "file no": "file_no", "file . no": "file_no", "file nos": "file_no",
    "name of the company and address": "company_address",
    "regulatory status": "regulatory_status",
    "date of issue": "date_of_issue",
    # Lab list
    "category of in vitro diagnostics medical devices": "category",
    "name of testing facility": "name_of_facility",
    # Fee
    "subject": "subject", "rule": "rule", "section": "section",
    "rupees": "fee",
    "in rupees (inr) except where specified in dollars ($)": "fee",
    # Contents
    "content": "content", "contents": "content", "topic": "content",
    "title": "content", "page no": "page_no", "page no.": "page_no",
    "page number": "page_no",
    # Schedule
    "month": "month", "tentative dates": "dates", "day": "day",
    "study": "study", "study conditions": "study_conditions",
    "duration of study": "duration",
    # Vaccine
    "name of vaccine": "name_of_vaccine",
    "strain": "strain", "name of the strain": "strain",
}


def _canon_key(s: str) -> str:
    """Canonicalize a string for lookup keys (lowercase, spaces only)."""
    return WHITESPACE.sub(" ", NON_ALNUM.sub(" ", s.casefold())).strip()


HEADER_CANON = {_canon_key(k): v for k, v in _RAW_CANON.items()}


def clean_cell(v) -> str:
    return WHITESPACE.sub(" ", str(v or "")).strip()


def canon_cell(cell: str) -> str:
    c = _canon_key(clean_cell(cell))
    return HEADER_CANON.get(c, c)


def sig_from_header(header_cells: list[str]) -> str:
    return "|".join(canon_cell(c) for c in header_cells)


def trim_trailing(cells: list[str]) -> list[str]:
    cells = list(cells)
    while cells and not cells[-1]:
        cells.pop()
    return cells


# ============================================================
# JUNK / ASCII DETECTION
# ============================================================
def is_junk_cell(cell: str) -> bool:
    """True if cell is empty, punctuation-only, or a single char."""
    c = clean_cell(cell)
    if not c:
        return True
    if len(c) == 1:
        return True
    if not any(ch.isalnum() for ch in c):
        return True
    if NUMBER_ONLY.fullmatch(c):
        return True
    return False


def ascii_ratio(text: str) -> float:
    if not text:
        return 1.0
    return sum(1 for ch in text if ord(ch) < 128) / len(text)


def junk_ratio(rows: list[list], max_rows: int = 10) -> float:
    """Fraction of junk cells across first N rows."""
    total = 0
    junk = 0
    for r in rows[:max_rows]:
        for c in r:
            total += 1
            if is_junk_cell(clean_cell(c)):
                junk += 1
    return junk / max(total, 1)


# ============================================================
# TABLE VALIDATION
# ============================================================
def is_valid_table(rows: list[list], min_data_rows: int = 2) -> tuple[bool, str]:
    """Strict validation. Returns (is_valid, reason)."""
    if len(rows) < 2:
        return False, "TOO_FEW_ROWS"

    # Junk ratio on first 10 rows
    jr = junk_ratio(rows, 10)
    if jr > 0.5:
        return False, "HIGH_JUNK_RATIO"

    # Header row = first row
    header_raw = [clean_cell(c) for c in rows[0]]
    header_real = [c for c in header_raw if not is_junk_cell(c)]

    if len(header_real) < 2:
        return False, "HEADER_TOO_SMALL"

    # Each real header cell must be >= 3 chars
    short_cells = [c for c in header_real if len(c) < 3]
    if short_cells:
        return False, "HEADER_CELL_TOO_SHORT"

    # Header ASCII dominance
    header_text = " ".join(header_real)
    if ascii_ratio(header_text) < 0.85:
        return False, "HEADER_NON_ASCII"

    # Data rows: at least 2 rows with 2+ real (non-junk) cells
    data_rows = rows[1:]
    qualifying = 0
    for r in data_rows[:50]:
        populated = [c for c in (clean_cell(x) for x in r) if not is_junk_cell(c)]
        if len(populated) >= 2:
            qualifying += 1

    if qualifying < min_data_rows:
        return False, "TOO_FEW_DATA_ROWS"

    return True, ""


# ============================================================
# HEADER ROW DETECTION
# ============================================================
HEADER_KEYWORDS = {
    "no", "name", "batch", "date", "mfg", "exp", "reason", "drawn",
    "from", "nsq", "result", "reported", "device", "intended", "use",
    "risk", "class", "file", "company", "product", "regulatory",
    "status", "subject", "content", "page", "lot", "strength",
    "notification", "manufacturer", "remarks", "reply", "category",
    "testing", "facility", "vaccine", "strain", "indication",
    "month", "day", "study", "duration",
}


def find_header_idx(rows: list[list]) -> int | None:
    """Find the most header-like row using keyword + ASCII + length scoring."""
    best_score = -1.0
    best_idx = None

    for idx, row in enumerate(rows[:12]):
        cells = [clean_cell(c) for c in row if not is_junk_cell(clean_cell(c))]
        if len(cells) < 2:
            continue

        text = " ".join(cells)
        if ascii_ratio(text) < 0.85:
            continue

        avg_len = sum(len(c) for c in cells) / len(cells)
        if avg_len < 3:
            continue

        keyword_hits = sum(
            1 for c in cells
            if any(kw in c.lower() for kw in HEADER_KEYWORDS)
        )

        # Score: keyword hits dominate, more cells better, longer avg better
        score = keyword_hits * 10 + len(cells) * 2 + min(avg_len, 20) * 0.1
        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


# ============================================================
# PDF EXTRACTION
# ============================================================
def extract_pymupdf_lines(pdf_path: Path, max_pages: int) -> list[dict]:
    """pymupdf lines-only extraction (visible borders)."""
    out = []
    try:
        doc = pymupdf.open(pdf_path)
    except Exception:
        return out
    try:
        pages = list(doc)[:max_pages] if max_pages > 0 else list(doc)
        for page_num, page in enumerate(pages, start=1):
            seen = set()
            for tbl in page.find_tables(strategy="lines").tables:
                try:
                    rows = tbl.extract()
                except Exception:
                    continue
                if not rows or len(rows) < 2:
                    continue
                sig = tuple(tuple(clean_cell(c) for c in r) for r in rows)
                if sig in seen:
                    continue
                seen.add(sig)
                out.append({"page": page_num, "rows": rows, "method": "pymupdf_lines"})
    finally:
        doc.close()
    return out


def extract_pdfplumber(pdf_path: Path, max_pages: int) -> list[dict]:
    """pdfplumber extraction (handles borderless tables better)."""
    if not HAS_PDFPLUMBER:
        return []
    out = []
    try:
        with pdfplumber.open(str(pdf_path)) as doc:
            pages = doc.pages[:max_pages] if max_pages > 0 else doc.pages
            for page_num, page in enumerate(pages, start=1):
                try:
                    tables = page.extract_tables()
                except Exception:
                    continue
                for tbl in tables or []:
                    if not tbl or len(tbl) < 2:
                        continue
                    cleaned = [[clean_cell(c) for c in row] for row in tbl]
                    out.append({"page": page_num, "rows": cleaned, "method": "pdfplumber"})
    except Exception:
        return out
    return out


def extract_tables(pdf_path: Path, max_pages: int) -> list[dict]:
    """Try pymupdf lines first; if nothing, fall back to pdfplumber."""
    tables = extract_pymupdf_lines(pdf_path, max_pages)
    if tables:
        return tables
    return extract_pdfplumber(pdf_path, max_pages)


# ============================================================
# AGGREGATION
# ============================================================
def analyze(csv_path: Path, root: Path, min_rows: int, max_pages: int):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [
            r for r in reader
            if (r.get("Structure") or "").strip().casefold() == "table"
        ]

    print(f"Corpus: {len(rows)} PDFs with Structure=table")

    schemas: dict[str, dict] = defaultdict(lambda: {
        "header_variants": Counter(),
        "sample_header": "",
        "sample_first_row": "",
        "sample_source": "",
        "sample_method": "",
        "num_tables": 0,
        "num_docs": set(),
        "num_rows": [],
        "num_cols": [],
        "occurrences": [],
        "methods": Counter(),
    })

    rejected: list[dict] = []
    rej_reasons: Counter = Counter()
    total_tables_raw = 0
    total_tables_valid = 0
    total_pdfs_with_tables = 0

    for i, row in enumerate(rows, start=1):
        src = (row.get("Source") or "").strip()
        fname = (row.get("File Name") or "").strip()
        label = f"{src}/{fname}".strip("/") or "(missing source or filename)"
        print(f"[{i}/{len(rows)}] Processing {label}", flush=True)
        if not src or not fname:
            print("  SKIP: missing source or filename", flush=True)
            continue
        pdf_path = root / src / fname
        if not pdf_path.is_file():
            print("  SKIP: PDF not found", flush=True)
            continue

        tables = extract_tables(pdf_path, max_pages)
        pdf_valid_count = 0

        for tbl in tables:
            total_tables_raw += 1
            rows_list = tbl["rows"]

            ok, reason = is_valid_table(rows_list, min_rows)
            if not ok:
                rej_reasons[reason] += 1
                rejected.append({
                    "source": src, "filename": fname, "page": tbl["page"],
                    "method": tbl["method"], "reason": reason,
                    "num_rows": len(rows_list),
                    "header_preview": " | ".join(
                        clean_cell(c) for c in (rows_list[0][:5] if rows_list else [])
                    )[:200],
                })
                continue

            hidx = find_header_idx(rows_list)
            if hidx is None:
                rej_reasons["NO_HEADER_FOUND"] += 1
                rejected.append({
                    "source": src, "filename": fname, "page": tbl["page"],
                    "method": tbl["method"], "reason": "NO_HEADER_FOUND",
                    "num_rows": len(rows_list), "header_preview": "",
                })
                continue

            header_cells = trim_trailing([clean_cell(c) for c in rows_list[hidx]])
            header_real = [c for c in header_cells if not is_junk_cell(c)]
            if len(header_real) < 2:
                rej_reasons["HEADER_TOO_SMALL_AFTER_PICK"] += 1
                continue

            first_row = []
            if hidx + 1 < len(rows_list):
                first_row = trim_trailing(
                    [clean_cell(c) for c in rows_list[hidx + 1]]
                )

            data_rows = rows_list[hidx + 1:]
            num_data_rows = sum(
                1 for r in data_rows
                if sum(
                    1 for c in r if not is_junk_cell(clean_cell(c))
                ) >= 2
            )

            total_tables_valid += 1
            pdf_valid_count += 1

            sig = sig_from_header(header_cells)
            header_raw = " | ".join(header_cells)
            first_row_raw = " | ".join(first_row)

            entry = schemas[sig]
            entry["header_variants"][header_raw] += 1
            if not entry["sample_header"]:
                entry["sample_header"] = header_raw
                entry["sample_first_row"] = first_row_raw
                entry["sample_source"] = f"{src}/{fname}"
                entry["sample_method"] = tbl["method"]
            entry["num_tables"] += 1
            entry["num_docs"].add((src, fname))
            entry["num_rows"].append(num_data_rows)
            entry["num_cols"].append(len(header_cells))
            entry["methods"][tbl["method"]] += 1
            entry["occurrences"].append({
                "source": src, "filename": fname,
                "page": tbl["page"], "method": tbl["method"],
                "num_rows": num_data_rows, "num_cols": len(header_cells),
                "header_raw": header_raw, "first_row_raw": first_row_raw,
            })

        if pdf_valid_count > 0:
            total_pdfs_with_tables += 1

        if i % 25 == 0:
            print(
                f"  [{i}/{len(rows)}] unique={len(schemas)} "
                f"valid={total_tables_valid} raw={total_tables_raw}",
                flush=True,
            )

    print(f"\n{'='*70}")
    print(f"RAW tables extracted:   {total_tables_raw:>6}")
    print(f"VALID tables kept:      {total_tables_valid:>6}")
    print(f"REJECTED:               {total_tables_raw - total_tables_valid:>6}")
    print(f"PDFs w/ valid tables:   {total_pdfs_with_tables:>6}")
    print(f"UNIQUE schemas:         {len(schemas):>6}")
    print(f"{'='*70}\n")
    print("Rejection reasons:")
    for reason, count in rej_reasons.most_common():
        print(f"  {reason:<30} {count:>5}")

    # Quality classification
    for sig, d in schemas.items():
        docs = len(d["num_docs"])
        avg_rows = sum(d["num_rows"]) / max(len(d["num_rows"]), 1)
        if docs >= 5 and avg_rows >= 3:
            d["quality"] = "HIGH"
        elif docs >= 2 or avg_rows >= 5:
            d["quality"] = "MEDIUM"
        else:
            d["quality"] = "LOW"

    ordered = sorted(
        schemas.items(),
        key=lambda kv: (
            -len(kv[1]["num_docs"]),
            -sum(kv[1]["num_rows"]),
        ),
    )
    return ordered, rejected, rej_reasons


# ============================================================
# OUTPUT
# ============================================================
def write_schema_csv(ordered, out_path: Path):
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "schema_id", "quality", "signature", "sample_header",
            "sample_first_row", "num_documents", "num_tables",
            "total_data_rows", "avg_rows_per_table", "max_rows",
            "num_cols", "sample_source", "sample_method",
            "header_variants_top3",
        ])
        for sid, (sig, d) in enumerate(ordered, start=1):
            total_rows = sum(d["num_rows"])
            avg_rows = round(total_rows / max(len(d["num_rows"]), 1), 1)
            variants = d["header_variants"].most_common(3)
            variants_str = " ;; ".join(f"{h[:120]} (x{c})" for h, c in variants)
            writer.writerow([
                f"T{sid:03d}", d["quality"], sig,
                d["sample_header"], d["sample_first_row"],
                len(d["num_docs"]), d["num_tables"],
                total_rows, avg_rows,
                max(d["num_rows"]) if d["num_rows"] else 0,
                max(d["num_cols"]) if d["num_cols"] else 0,
                d["sample_source"], d["sample_method"],
                variants_str,
            ])


def write_occurrences_csv(ordered, out_path: Path):
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "schema_id", "source", "filename", "page", "method",
            "num_rows", "num_cols", "header_raw", "first_row_raw",
        ])
        for sid, (sig, d) in enumerate(ordered, start=1):
            for occ in d["occurrences"]:
                writer.writerow([
                    f"T{sid:03d}", occ["source"], occ["filename"],
                    occ["page"], occ["method"],
                    occ["num_rows"], occ["num_cols"],
                    occ["header_raw"], occ["first_row_raw"],
                ])


def write_schema_json(ordered, out_path: Path):
    payload = []
    for sid, (sig, d) in enumerate(ordered, start=1):
        total_rows = sum(d["num_rows"])
        payload.append({
            "schema_id": f"T{sid:03d}",
            "quality": d["quality"],
            "signature": sig,
            "sample_header": d["sample_header"],
            "sample_first_row": d["sample_first_row"],
            "num_documents": len(d["num_docs"]),
            "num_tables": d["num_tables"],
            "total_data_rows": total_rows,
            "num_rows_range": [
                min(d["num_rows"]) if d["num_rows"] else 0,
                max(d["num_rows"]) if d["num_rows"] else 0,
            ],
            "num_cols": max(d["num_cols"]) if d["num_cols"] else 0,
            "header_variants": dict(d["header_variants"].most_common(10)),
            "sample_source": d["sample_source"],
            "sample_method": d["sample_method"],
            "methods": dict(d["methods"]),
            "documents": sorted({f"{s}/{f}" for s, f in d["num_docs"]})[:25],
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_rejected_csv(rejected, out_path: Path):
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "source", "filename", "page", "method", "reason",
            "num_rows", "header_preview",
        ])
        writer.writeheader()
        writer.writerows(rejected)


# ============================================================
# CLI
# ============================================================
def main():
    p = argparse.ArgumentParser(
        description="Inventory unique table schemas (English-only, strict validation)."
    )
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--min-rows", type=int, default=2,
                   help="Min qualifying data rows (default: 2)")
    p.add_argument("--sample-pages", type=int, default=0,
                   help="Max pages per PDF; 0 = all")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--out-occ", type=Path, default=DEFAULT_OUT_OCC)
    p.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    p.add_argument("--out-rejected", type=Path, default=DEFAULT_OUT_REJ)
    args = p.parse_args()

    ordered, rejected, _ = analyze(
        args.csv.resolve(), args.root.resolve(),
        args.min_rows, args.sample_pages,
    )

    write_schema_csv(ordered, args.out)
    write_occurrences_csv(ordered, args.out_occ)
    write_schema_json(ordered, args.out_json)
    write_rejected_csv(rejected, args.out_rejected)

    print("\nWrote:")
    print(f"  {args.out.name}")
    print(f"  {args.out_occ.name}")
    print(f"  {args.out_json.name}")
    print(f"  {args.out_rejected.name}")

    print("\nTop 20 schemas by document count:")
    for sid, (sig, d) in enumerate(ordered[:20], start=1):
        ncols = max(d["num_cols"]) if d["num_cols"] else 0
        max_rows = max(d["num_rows"]) if d["num_rows"] else 0
        total_rows = sum(d["num_rows"])
        print(
            f"  T{sid:03d}  {d['quality']:<6}  docs={len(d['num_docs']):>3}  "
            f"tables={d['num_tables']:>3}  rows={total_rows:>5}  "
            f"cols={ncols:>2}  max={max_rows:>4}  "
            f"{d['sample_header'][:60]}"
        )


if __name__ == "__main__":
    main()