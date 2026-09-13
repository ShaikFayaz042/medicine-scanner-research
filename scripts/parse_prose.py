#!/usr/bin/env python3
"""
Unified prose parser — 1 PDF = 1 logical record with detected metadata.

Handles:
    gazette_legal      (34 docs)  — S.O. / G.S.R. legal notifications
    pvpi_safety        (1 doc)    — PvPI drug safety alerts master PDF
    theft_recall       (6 docs)   — theft / recall alerts
    medical_device     (18 docs)  — medical device alerts
    ivd_alert          (4 docs)   — IVD diagnostic alerts
    circular           (5 docs)   — circulars / office orders
    guideline          (4 docs)   — guidance documents, drafts, FAQs

For each PDF, extracts:
    - Full text (page-marked, preserved as-is)
    - Detected notification numbers (S.O. / G.S.R. / F.No.)
    - Detected dates (multiple formats)
    - Subject line (first meaningful line)
    - Action keywords (prohibition / restriction / approval / ban / revoke)

RAW — no normalization.

Outputs:
    structured_raw/<type>/<doc_id>.json
    structured_raw/<type>/_manifest.json

Usage:
    python scripts/parse_prose.py                     # all 7 types
    python scripts/parse_prose.py --type gazette_legal
    python scripts/parse_prose.py --type pvpi_safety
    python scripts/parse_prose.py --force
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
TYPE_CLASSIFICATION = REPO_ROOT / "type_classification"


# Map: type_name → record_type string used inside the JSON
RECORD_TYPE_MAP = {
    "gazette_legal":  "GAZETTE_LEGAL",
    "pvpi_safety":    "PVPI_SAFETY",
    "theft_recall":   "THEFT_RECALL",
    "medical_device": "MEDICAL_DEVICE",
    "ivd_alert":      "IVD_ALERT",
    "circular":       "CIRCULAR",
    "guideline":      "GUIDELINE",
    "other":          "OTHER",
}

# Which types get special per-file handling
SPECIAL_HANDLERS = {
    "pvpi_safety": "pvpi",
}


# ---------------------------------------------------------------------------
# Regex extractors
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
    "approval":    ["approv", "approval", "grant of"],
    "revocation":  ["revoke", "revoked", "revocation", "cancel", "cancellation"],
    "suspension":  ["suspend", "suspended", "suspension"],
    "recall":      ["recall", "voluntary recall", "product recall"],
    "theft":       ["theft", "stolen", "stolen product"],
    "guidance":    ["guidance", "guideline", "guidelines", "draft"],
    "alert":       ["alert", "advisory", "caution"],
    "amendment":   ["amend", "amendment", "insert", "substitution"],
    "fee_revision": ["fee revision", "fees", "revision of testing fees"],
}

# Quality flags
QUALITY_HINTS = [
    "not of standard", "spurious", "adulterated", "misbranded",
    "defective", "sub standard", "substandard",
]


def detect_action(text: str) -> list[str]:
    """Return action keywords found in text (lowercased match, first 200 chars)."""
    head = text[:3000].lower()
    found = []
    for action, keywords in ACTION_KEYWORDS.items():
        if any(kw in head for kw in keywords):
            found.append(action)
    return found


def extract_notification_numbers(text: str, max_n: int = 20) -> list[str]:
    """Return distinct notification numbers found in text."""
    found = set()
    for m in NOTIF_RE.finditer(text):
        n = m.group(0).strip()
        # Clean up trailing punctuation
        n = re.sub(r"[.,;:]+$", "", n)
        found.add(n)
        if len(found) >= max_n:
            break
    return sorted(found)


def extract_dates(text: str, max_n: int = 20) -> list[str]:
    """Return distinct dates found in the head of the text."""
    head = text[:5000]
    found = set()
    for m in DATE_RE.finditer(head):
        d = m.group(0).strip()
        found.add(d)
        if len(found) >= max_n:
            break
    return sorted(found)


def extract_subject(text: str, max_len: int = 300) -> str:
    """Return the first meaningful long line as the subject."""
    for line in text.splitlines()[:60]:
        line = line.strip()
        if line.startswith("====="):
            continue
        if len(line) < 25:
            continue
        if line.lower().startswith(("page ", "sl no", "s no")):
            continue
        return line[:max_len]
    return ""


def extract_quality_flags(text: str) -> list[str]:
    """Check for quality-related keywords."""
    head = text[:5000].lower()
    return [kw for kw in QUALITY_HINTS if kw in head]


# ---------------------------------------------------------------------------
# Read text from raw extraction output
# ---------------------------------------------------------------------------
def read_text(doc_entry) -> tuple[str, str]:
    """Return (text, error_msg)."""
    text_path = doc_entry.get("text_source_path")
    if not text_path:
        return "", "no text_source_path"
    p = REPO_ROOT / text_path
    if not p.exists():
        return "", f"text file missing: {text_path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace"), ""
    except Exception as exc:
        return "", f"read failed: {exc}"


# ---------------------------------------------------------------------------
# PVPI master table canonical keys
# ---------------------------------------------------------------------------
PVPI_KEYS = {
    "s_no":          ["s no", "s no.", "s. no.", "s.n.", "sno"],
    "issue_date":    ["issue date", "date", "issued on"],
    "suspected_drug": ["suspected drug", "suspected drugs", "drug", "drug name"],
    "indication":    ["indication", "indications"],
    "adr":           ["adverse drug reaction", "adverse drug reactions",
                      "adr", "adrs", "reaction"],
}

PVPI_NORM_TO_KEY: dict[str, str] = {}
for k, variants in PVPI_KEYS.items():
    for v in variants:
        PVPI_NORM_TO_KEY[v] = k


def _pvpi_canonical_key(header: str) -> str | None:
    n = re.sub(r"[\W_]+", " ", (header or "").lower()).strip()
    if not n:
        return None
    if n in PVPI_NORM_TO_KEY:
        return PVPI_NORM_TO_KEY[n]
    compact = n.replace(" ", "")
    for variant, canon in PVPI_NORM_TO_KEY.items():
        if variant.replace(" ", "") == compact:
            return canon
    if "suspected" in n:
        return "suspected_drug"
    if "indication" in n:
        return "indication"
    if "reaction" in n or "adr" in n:
        return "adr"
    if "issue" in n or n == "date":
        return "issue_date"
    if re.match(r"^s\s*\.?\s*n", n):
        return "s_no"
    return None


def _pvpi_row_value_is_date(text: str) -> bool:
    s = re.sub(r"\s+", " ", (text or "").strip())
    m = re.fullmatch(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}", s, flags=re.IGNORECASE)
    return bool(m)


def _extract_positional_pvpi_row(cells: list[str], prev_issue_date: str = "") -> dict | None:
    """Handle the common PVPI table shape: [S.No, Issue Date, Drug, Indication, ADR]."""
    cleaned = [str(c).replace("\n", " ").rstrip() for c in cells]
    cleaned = [re.sub(r"\s+", " ", c).strip() for c in cleaned]
    if not any(cleaned):
        return None

    idx = None
    for i, cell in enumerate(cleaned):
        if re.fullmatch(r"\d{1,4}\.?\d*", cell.strip()):
            idx = i
            break
    if idx is None:
        return None

    s_no = cleaned[idx]
    if len(cleaned) >= 5 and idx == 0:
        issue_date = cleaned[1] if _pvpi_row_value_is_date(cleaned[1]) else prev_issue_date
        drug = cleaned[2]
        indication = cleaned[3]
        adr = cleaned[4]
    elif len(cleaned) >= 4 and idx == 0:
        issue_date = cleaned[1] if _pvpi_row_value_is_date(cleaned[1]) else prev_issue_date
        drug = cleaned[2]
        indication = " ".join(cleaned[3:-1]).strip()
        adr = cleaned[-1]
    else:
        issue_date = prev_issue_date
        drug = " ".join(cleaned[idx + 1:-1]).strip()
        indication = ""
        adr = cleaned[-1] if cleaned else ""

    if not re.fullmatch(r"\d{1,4}\.?\d*", s_no):
        return None
    if not drug:
        return None

    raw_data = {
        "S. No.": s_no,
        "Issue Date": issue_date,
        "Suspected drugs": drug,
        "Indication(s)": indication,
        "Adverse Drug Reactions": adr,
    }
    canonical = {
        "s_no": s_no,
        "issue_date": issue_date,
        "suspected_drug": drug,
        "indication": indication,
        "adr": adr,
    }
    return {"record_type": "PVPI_SAFETY", "raw_data": raw_data, "canonical": canonical}


def extract_pvpi_from_tables(tables_path: Path) -> tuple[list[dict], dict]:
    """Extract PVPI master table rows."""
    if not tables_path.exists():
        return [], {"error": "tables.json missing"}
    try:
        tables = json.loads(tables_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], {"error": f"json parse failed: {exc}"}

    records: list[dict] = []
    stats = {"tables_read": 0, "rows_seen": 0, "rows_extracted": 0,
             "header_rows_skipped": 0, "invalid_rows_skipped": 0}

    header_keys: list[str] = []
    header_display: list[str] = []
    prev_issue_date = ""

    for tbl in tables:
        rows = tbl.get("rows", [])
        if not rows:
            continue
        stats["tables_read"] += 1

        for row in rows:
            stats["rows_seen"] += 1
            cells = [str(c) if c is not None else "" for c in row]
            if not any(c.strip() for c in cells):
                continue

            matched = {_pvpi_canonical_key(c) for c in cells if c.strip()}
            matched.discard(None)
            if len(matched) >= 2:
                header_keys = []
                header_display = []
                for c in cells:
                    h = c.replace("\n", " ").strip()
                    k = _pvpi_canonical_key(h)
                    header_keys.append(k or f"unknown_{len(header_keys)}")
                    header_display.append(h)
                stats["header_rows_skipped"] += 1
                continue

            positional = _extract_positional_pvpi_row(cells, prev_issue_date)
            if positional is not None:
                prev_issue_date = positional["canonical"].get("issue_date", prev_issue_date).strip()
                records.append(positional)
                stats["rows_extracted"] += 1
                continue

            if not header_keys:
                stats["invalid_rows_skipped"] += 1
                continue

            raw_data: dict[str, str] = {}
            canonical: dict[str, str] = {}
            for i, cell in enumerate(cells):
                if i >= len(header_keys):
                    break
                canon = header_keys[i]
                display = (header_display[i] if i < len(header_display)
                           and header_display[i] else canon)
                v = cell.rstrip()
                raw_data[display] = v
                if not canon.startswith("unknown_"):
                    canonical[canon] = v

            if not canonical.get("issue_date", "").strip():
                if prev_issue_date:
                    canonical["issue_date"] = prev_issue_date
                    for rk in list(raw_data.keys()):
                        if _pvpi_canonical_key(rk) == "issue_date":
                            raw_data[rk] = prev_issue_date
                            break

            s_no = canonical.get("s_no", "").strip()
            drug = canonical.get("suspected_drug", "").strip()
            if not re.match(r"^\d{1,4}\.?\d*$", s_no):
                stats["invalid_rows_skipped"] += 1
                continue
            if not drug:
                stats["invalid_rows_skipped"] += 1
                continue

            records.append({
                "record_type": "PVPI_SAFETY",
                "raw_data": raw_data,
                "canonical": canonical,
            })
            stats["rows_extracted"] += 1
            prev_issue_date = canonical.get("issue_date", prev_issue_date).strip()

    return records, stats


PVPI_ALERT_SPLIT_RE = re.compile(
    r"Drug\s+Safety\s+Alert[s]?\s*(?:issued\s+by\s+PvPI)?",
    re.IGNORECASE,
)


def extract_pvpi_from_text(text: str) -> tuple[list[dict], dict]:
    """
    Fallback: parse PVPI rows from the .txt file line-by-line.
    Handles merged-cell PDFs where find_tables() only sees the first page.
    """
    records: list[dict] = []
    stats = {"lines_read": 0, "rows_extracted": 0, "issue_dates_seen": 0}

    date_marker_re = re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}\b"
    )
    row_start_re = re.compile(r"^\s*(\d{1,4})\s+(\S.*)$")

    current_date = ""
    current_sno = None
    current_drug = ""
    current_indication_parts: list[str] = []
    current_adr_parts: list[str] = []

    def flush():
        nonlocal current_sno, current_drug, current_indication_parts, current_adr_parts
        if current_sno is None or not current_drug:
            return
        records.append({
            "record_type": "PVPI_SAFETY",
            "raw_data": {
                "S.No": str(current_sno),
                "Issue Date": current_date,
                "Suspected drugs": current_drug,
                "Indication(s)": " ".join(current_indication_parts).strip(),
                "Adverse Drug Reactions": " ".join(current_adr_parts).strip(),
            },
            "canonical": {
                "s_no": str(current_sno),
                "issue_date": current_date,
                "suspected_drug": current_drug,
                "indication": " ".join(current_indication_parts).strip(),
                "adr": " ".join(current_adr_parts).strip(),
            },
            "detected": {
                "subject": current_drug,
                "dates": [current_date] if current_date else [],
                "notification_numbers": [],
            },
        })
        stats["rows_extracted"] += 1
        current_sno = None
        current_drug = ""
        current_indication_parts = []
        current_adr_parts = []

    seen_header = False

    for raw_line in text.splitlines():
        stats["lines_read"] += 1
        line = raw_line.strip()
        if not line or line.startswith("====="):
            continue

        m = date_marker_re.search(line)
        if m:
            current_date = m.group(0)
            stats["issue_dates_seen"] += 1

        if not seen_header:
            if "suspected drug" in line.lower():
                seen_header = True
            continue

        row_m = row_start_re.match(line)
        if row_m and int(row_m.group(1)) < 10000:
            flush()
            current_sno = int(row_m.group(1))
            rest = row_m.group(2).strip()
            current_drug = rest[:60]
            continue

        if current_sno is not None:
            current_adr_parts.append(line)

    flush()
    return records, stats


def handle_pvpi(text: str) -> list[dict]:
    """
    The PVPI master PDF is a list of Drug Safety Alerts. Try to split it
    into individual alerts. Fallback: return the whole text as one record.
    """
    # Split on "Drug Safety Alert" occurrences
    parts = re.split(
        r"\n(?=(?:Drug\s+Safety\s+Alert|DSA\s+\d+|Alert\s+\d+))",
        text,
        flags=re.IGNORECASE,
    )
    records = []
    for part in parts:
        part = part.strip()
        if len(part) < 100:
            continue
        head = part[:2000]
        records.append({
            "record_type": "PVPI_SAFETY",
            "raw_text": part,
            "detected": {
                "subject": extract_subject(part),
                "dates": extract_dates(head),
                "notification_numbers": extract_notification_numbers(head),
            },
        })
    if not records:
        records.append({
            "record_type": "PVPI_SAFETY",
            "raw_text": text,
            "detected": {
                "subject": extract_subject(text),
                "dates": extract_dates(text),
                "notification_numbers": extract_notification_numbers(text),
            },
        })
    return records


# ---------------------------------------------------------------------------
# Standard prose handler
# ---------------------------------------------------------------------------
def build_prose_record(doc_entry, text: str) -> dict:
    record_type = RECORD_TYPE_MAP[doc_entry["type"]]
    head = text[:5000]
    return {
        "record_type": record_type,
        "raw_text": text,
        "detected": {
            "subject": extract_subject(text),
            "dates": extract_dates(head),
            "notification_numbers": extract_notification_numbers(head),
            "actions": detect_action(text),
            "quality_flags": extract_quality_flags(text),
        },
    }


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------
def build_output_document(doc_entry, records, stats, method) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
            "records_extracted": len(records),
            "text_chars": stats.get("text_chars", 0),
            "has_notification_number": stats.get("has_notification_number", False),
            "has_date": stats.get("has_date", False),
        },
        "records": records,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def process_one(doc_entry) -> dict:
    text, err = read_text(doc_entry)
    record_type = doc_entry["type"]

    # --- PVPI: try tables first, then text fallback ---
    if record_type == "pvpi_safety":
        extra_path = doc_entry.get("extra_path")

        table_records: list[dict] = []
        table_stats: dict = {}
        if extra_path:
            p = REPO_ROOT / extra_path
            if p.name.endswith(".tables.json"):
                table_records, table_stats = extract_pvpi_from_tables(p)
                for r in table_records:
                    r["detected"] = {
                        "subject": r["canonical"].get("suspected_drug", ""),
                        "dates": [r["canonical"].get("issue_date", "")],
                        "notification_numbers": [],
                    }

        if len(table_records) >= 30:
            table_stats["text_chars"] = len(text)
            return build_output_document(
                doc_entry, table_records, table_stats, "PVPI_TABLE"
            )

        if text:
            text_records, text_stats = extract_pvpi_from_text(text)
            if len(text_records) > len(table_records):
                text_stats["text_chars"] = len(text)
                text_stats["table_attempted"] = True
                text_stats["table_records"] = len(table_records)
                return build_output_document(
                    doc_entry, text_records, text_stats, "PVPI_TEXT_FALLBACK"
                )

        if text:
            records = handle_pvpi(text)
            stats = {"text_chars": len(text), "page_count": text.count("===== PAGE")}
            return build_output_document(
                doc_entry, records, stats, "PVPI_MASTER_FALLBACK"
            )

        stats = {"error": err or "no text", "text_chars": 0}
        return build_output_document(doc_entry, [], stats, "NONE")

    # --- Standard prose handling ---
    if not text:
        stats = {"error": err or "no text", "text_chars": 0}
        return build_output_document(doc_entry, [], stats, "NONE")

    records = [build_prose_record(doc_entry, text)]

    head = text[:5000]
    stats = {
        "text_chars": len(text),
        "page_count": text.count("===== PAGE"),
        "notification_numbers_found": len(extract_notification_numbers(head)),
        "dates_found": len(extract_dates(head)),
        "actions_found": detect_action(text),
        "has_notification_number": bool(extract_notification_numbers(head)),
        "has_date": bool(extract_dates(head)),
    }
    return build_output_document(doc_entry, records, stats, "PROSE_TEXT")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Parse prose document types.")
    ap.add_argument("--type", choices=list(RECORD_TYPE_MAP.keys()), default=None,
                    help="Parse only this type (default: all)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    types_to_run = ([args.type] if args.type else list(RECORD_TYPE_MAP.keys()))

    grand_total = 0
    grand_docs = 0

    for type_name in types_to_run:
        manifest_path = TYPE_CLASSIFICATION / type_name / "_manifest.json"
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
                    results.append({
                        "document_id": doc["document_id"],
                        "filename": doc["filename"],
                        "status": "skipped",
                        "records": n,
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
                m = result["extraction"]["extraction_method"]
                nf = result["extraction"]["raw_stats"].get("notification_numbers_found", 0)
                print(f"[{i:>3}/{len(docs)}] OK    {stem[:52]:<52} "
                      f"recs={n:>2} notif={nf:>2} {m}")
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
        grand_docs += len(docs)

        print()
        print(f"  Documents : {len(docs)}")
        print(f"  Success   : {ok}")
        print(f"  Empty     : {empty}")
        print(f"  Errors    : {errors}")
        print(f"  Skipped   : {skipped}")
        print(f"  Records   : {total_records}")

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

    print()
    print("=" * 80)
    print(f"PROSE PARSE COMPLETE")
    print("=" * 80)
    print(f"  Types processed  : {len(types_to_run)}")
    print(f"  Documents        : {grand_docs}")
    print(f"  Total records    : {grand_total}")


if __name__ == "__main__":
    main()