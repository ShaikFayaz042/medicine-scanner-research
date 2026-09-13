#!/usr/bin/env python3
"""
FDC parser — handles both tabular prohibition lists and prose notices.

Inputs:
    type_classification/fdc_prohibited/_manifest.json    (prohibition lists)
    type_classification/fdc_notification/_manifest.json  (process notices)

Outputs:
    structured_raw/fdc_prohibited/<doc_id>.json
    structured_raw/fdc_notification/<doc_id>.json

Two extraction modes:
    TABLE  — PyMuPDF tables.json with columns: composition, S.O. number, date
    PROSE  — notice text with detected notification numbers + dates

RAW — no normalization.
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
OUTPUT_ROOT = REPO_ROOT / "structured_raw"

MANIFESTS = {
    "fdc_prohibited": REPO_ROOT / "type_classification" / "fdc_prohibited" / "_manifest.json",
    "fdc_notification": REPO_ROOT / "type_classification" / "fdc_notification" / "_manifest.json",
}


# ---------------------------------------------------------------------------
# Canonical keys for FDC tables
# ---------------------------------------------------------------------------
CANONICAL_KEYS = {
    "s_no":                 ["s no", "s n", "s. no", "s.n.", "s no.", "sl no", "sr no", "s.n", "sno"],
    "composition":          [
        "drugs name", "drug name", "composition", "name of drug",
        "name of drugs", "fixed dose combination", "fdc", "product",
        "drugs", "combination",
        "name of fdc", "fdc name", "list of fdcs",
    ],
    "notification_number":  [
        "notification no", "notification no.", "notification number",
        "s.o. no", "so no", "gazette notification", "notification",
        "s.o", "so", "gsr", "g.s.r.",
    ],
    "notification_date":    [
        "notification date", "date", "dated", "date of notification",
        "notification dt",
        "date of noc", "noc date",
    ],
    "status":               [
        "status", "action", "category", "type",
    ],
    "dosage_form":          ["dosage form", "form"],
    "conditions":           ["conditions", "remarks", "notes"],
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
    if "composition" in n or "drugs name" in n or "drug name" in n:
        return "composition"
    if "notificatio" in n:
        return "notification_number"
    if "notification no" in n or "s o" in n or "so no" in n or re.search(r"\bs\.?\s*o\b", n):
        return "notification_number"
    if "notification date" in n or n == "date" or "dated" in n:
        return "notification_date"
    if "status" in n or "action" in n or "category" in n:
        return "status"
    if re.match(r"^s\s*\.?\s*n", n) or "sl no" in n:
        return "s_no"
    return None


# ---------------------------------------------------------------------------
# Section + header detection
# ---------------------------------------------------------------------------
HEADER_KEYWORDS = [
    "composition", "drugs name", "notification", "s o", "s.o", "gsr",
    "status", "category", "s no", "dosage",
]

HEADER_ANCHORS = [
    "composition", "drugs name", "notification", "s o", "s.o", "status",
]

FALLBACK_LAYOUTS: dict[int, tuple[list[str], list[str]]] = {
    2: (
        ["s_no", "composition"],
        ["S. No.", "Name of FDC"],
    ),
    3: (
        ["s_no", "composition", "notification_number"],
        ["S.No", "Name of FDC", "Notification No"],
    ),
    4: (
        ["s_no", "composition", "notification_number", "notification_date"],
        ["S.No", "Name of FDC", "Notification No", "Date"],
    ),
}


def _guess_layout_by_shape(cells: list[str]) -> tuple[list[str], list[str]] | None:
    if not cells:
        return None
    first = cells[0].strip()
    non_empty = sum(1 for c in cells if c.strip())
    if non_empty < 2:
        return None
    # Layout keyed on column count
    return FALLBACK_LAYOUTS.get(len(cells))


def is_header_row(cells: list[str]) -> bool:
    keys = {canonical_key(c) for c in cells if c and c.strip()}
    keys.discard(None)
    header_labels = 0
    for cell in cells:
        normalized = normalize_header(cell)
        if normalized in NORMALIZED_TO_CANONICAL or normalized == "notificatio":
            header_labels += 1
    return len(keys) >= 2 and header_labels >= 2


def is_section_row(cells: list[str]) -> bool:
    non_empty = [c.strip() for c in cells if c and c.strip()]
    if len(non_empty) != 1:
        return False
    first = non_empty[0]
    if len(first) > 100:
        return False
    lower = first.lower()
    if any(h in lower for h in ("tablet", "capsule", "injection", "mg", "ml")):
        return False
    if first.isupper() and not re.search(r"\d{4,}", first):
        return True
    return False


def _row_is_valid(canonical_data: dict[str, str]) -> bool:
    comp = canonical_data.get("composition", "").strip()
    notif = canonical_data.get("notification_number", "").strip()
    s_no = canonical_data.get("s_no", "").strip()
    date = canonical_data.get("notification_date", "").strip()

    # Reject rows where s_no cell is a header label
    if s_no.lower().replace(".", "").replace(" ", "") in (
        "sno", "sn", "sno.", "snon", "snonumber", "srno", "slno"
    ):
        return False
    # Reject rows where composition is a header label
    if comp.lower() in ("name of fdc", "name of fdcs", "composition",
                        "drugs name", "drug name", "fdc"):
        return False

    # Real data: composition must look like a drug (has mg / + / dosage word)
    # OR notification number is a real S.O./G.S.R. pattern
    has_drug_signal = bool(
        re.search(r"(mg|mcg|iu|ml|\+|tablet|capsule|injection|syrup|suspension)",
                  comp, re.IGNORECASE)
    ) or len(comp) >= 8
    has_notif_signal = bool(
        re.search(
            r"(S\.?\s*O\.?\s*(?:NO\.?)?\s*\d+"
            r"|G\.?\s*S\.?\s*R\.?\s*(?:NO\.?)?\s*\d+"
            r"|GSR\s*(?:NO\.?)?\s*\d+"
            r"|SO\s*(?:NO\.?)?\s*\d+"
            r"|F\.?\s*No\.?\s*[\w/-]+)",
            notif, re.IGNORECASE,
        )
    )
    has_noc_date = bool(re.match(r"\d{2}[./-]\d{2}[./-]\d{2,4}", date))

    return (has_drug_signal or has_notif_signal or has_noc_date) and len(comp) >= 5


def _is_continuation_row(canonical_data: dict[str, str]) -> bool:
    comp = canonical_data.get("composition", "").strip()
    notif = canonical_data.get("notification_number", "").strip()
    s_no = canonical_data.get("s_no", "").strip()
    if s_no and re.fullmatch(r"\d+[.]?", s_no):
        return False
    return bool(comp or notif)


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
                for field in ("composition", "notification_number", "notification_date"):
                    fragment = canonical_data.get(field, "").strip()
                    if not fragment:
                        continue
                    previous = prev.get(field, "").strip()
                    prev[field] = f"{previous} {fragment}".strip() if previous else fragment
                records[-1]["raw_data"] = {
                    **records[-1]["raw_data"],
                    **{
                        field: prev[field]
                        for field in ("composition", "notification_number", "notification_date")
                        if field in prev
                    },
                }
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
# PROSE extraction (fallback)
# ---------------------------------------------------------------------------
NOTIF_RE = re.compile(
    r"(?:S\.O\.|G\.S\.R\.)\s*\d+(?:\s*\(E\))?(?:\s*to\s*(?:S\.O\.|G\.S\.R\.)\s*\d+(?:\s*\(E\))?)?",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)


def extract_from_text(text_path: Path) -> tuple[list[dict], dict]:
    """Create a single record from prose text with detected metadata."""
    if not text_path.exists():
        return [], {"error": "text missing"}
    text = text_path.read_text(encoding="utf-8", errors="replace")
    # First 3000 chars for metadata extraction
    head = text[:5000]

    notification_numbers = list({m.group(0).strip() for m in NOTIF_RE.finditer(text)})
    dates = list({m.group(0).strip() for m in DATE_RE.finditer(head)})

    # Try to find a subject line
    subject = ""
    for line in text.splitlines()[:40]:
        line = line.strip()
        if len(line) > 30 and not line.startswith("====="):
            subject = line[:300]
            break

    canonical = {
        "composition":          "",
        "notification_number":  "; ".join(notification_numbers[:10]),
        "notification_date":    dates[0] if dates else "",
        "status":               "",
    }
    raw_data = dict(canonical)
    raw_data["subject"] = subject
    raw_data["all_notification_numbers"] = notification_numbers
    raw_data["all_dates"] = dates

    record = {
        "section": None,
        "raw_data": raw_data,
        "canonical": canonical,
        "prose": True,
    }
    stats = {
        "tables_read": 0,
        "rows_extracted": 1,
        "prose_fallback": True,
        "notification_numbers_found": len(notification_numbers),
        "dates_found": len(dates),
    }
    return [record], stats


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------
def build_output_document(doc_entry, records, stats, method) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = len(records)
    with_composition = sum(1 for r in records
                           if r.get("canonical", {}).get("composition", "").strip())
    with_notif = sum(1 for r in records
                     if r.get("canonical", {}).get("notification_number", "").strip())

    return {
        "document": {
            "document_id": doc_entry["document_id"],
            "source_file": doc_entry["filename"],
            "document_type": doc_entry["type"].upper(),
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
            "records_with_composition": with_composition,
            "records_with_notification_number": with_notif,
        },
        "records": [
            {
                "record_type": "FDC",
                "section": r.get("section"),
                "raw_data": r["raw_data"],
                "canonical": r.get("canonical", {}),
                **({"prose": True} if r.get("prose") else {}),
            }
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def process_one(doc_entry) -> dict:
    content_type = doc_entry["content_type"]
    extra_path = doc_entry.get("extra_path")
    text_path = doc_entry.get("text_source_path")

    records: list[dict] = []
    stats: dict = {}
    method = "NONE"

    # Try table extraction first
    if content_type in ("TEXT", "MIXED") and extra_path:
        p = REPO_ROOT / extra_path
        if p.name.endswith(".tables.json"):
            records, stats = extract_from_tables_json(p)
            method = "PDF_TEXT_TABLE"

    if not records and text_path:
        p = REPO_ROOT / text_path
        if p.exists():
            records, stats = extract_from_text(p)
            method = "PROSE_TEXT"

    return build_output_document(doc_entry, records, stats, method)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse FDC PDFs.")
    ap.add_argument("--type", choices=["fdc_prohibited", "fdc_notification"],
                    default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    types_to_run = ([args.type] if args.type else list(MANIFESTS.keys()))

    grand_total = 0
    for type_name in types_to_run:
        manifest_path = MANIFESTS[type_name]
        if not manifest_path.exists():
            print(f"[!] Manifest not found: {manifest_path}")
            continue

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        docs = manifest.get("documents", [])
        if args.limit:
            docs = docs[: args.limit]

        output_dir = OUTPUT_ROOT / type_name
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[*] Type: {type_name}  ({len(docs)} documents)")
        print(f"[*] Output: {output_dir}")

        started = time.time()
        results = []

        for i, doc in enumerate(docs, 1):
            stem = Path(doc["filename"]).stem
            out_path = output_dir / f"{stem}.json"
            if out_path.exists() and not args.force:
                try:
                    existing = json.loads(out_path.read_text(encoding="utf-8"))
                    n = existing.get("validation", {}).get("records_extracted", 0)
                    print(f"[{i:>3}/{len(docs)}] SKIP  {stem[:60]:<60} records={n:>3}")
                    results.append({"status": "skipped", "records": n,
                                    "document_id": doc["document_id"],
                                    "filename": doc["filename"]})
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
                print(f"[{i:>3}/{len(docs)}] OK    {stem[:60]:<60} "
                      f"records={n:>3}  method={m}")
                results.append({
                    "document_id": doc["document_id"],
                    "filename": doc["filename"],
                    "status": result["extraction"]["status"],
                    "method": m,
                    "records": n,
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
        grand_total += total_records

        print()
        print(f"  Documents total : {len(docs)}")
        print(f"  Success         : {ok}")
        print(f"  Empty           : {empty}")
        print(f"  Errors          : {errors}")
        print(f"  Skipped         : {skipped}")
        print(f"  Total records   : {total_records}")

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "type": type_name,
            "total_documents": len(docs),
            "success": ok, "empty": empty, "errors": errors, "skipped": skipped,
            "total_records": total_records,
            "elapsed_sec": round(elapsed, 2),
            "documents": results,
        }
        (output_dir / "_manifest.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(f"\n[+] Grand total records : {grand_total}")


if __name__ == "__main__":
    main()