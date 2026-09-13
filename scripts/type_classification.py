#!/usr/bin/env python3
"""
Type classification pipeline.

Reads every important PDF (already downloaded and extracted), classifies it
into one of 13 document types, and builds a type_classification/ folder:

    type_classification/
    ├── _index.json           top-level summary (types, counts, sources)
    ├── _manifest.json        flat manifest of all documents
    ├── _report.csv           sortable classification report (with --report)
    ├── _overrides.json       manual correction template
    ├── nsq_alert/
    ├── spurious_alert/
    ├── drug_alert/
    ├── fdc_prohibited/
    ├── fdc_notification/
    ├── gazette_legal/
    ├── pvpi_safety/
    ├── theft_recall/
    ├── medical_device/
    ├── ivd_alert/
    ├── circular/
    ├── guideline/
    └── other/

Source of truth:
    downloads/_analysis/pdf_analysis.csv          → content type (TEXT/SCANNED)
    raw_extraction/text/<src>/<name>.txt          → text for TEXT PDFs
    raw_extraction/ocr_tesseract/<src>/<name>.txt → text for SCANNED PDFs
    type_classification/_overrides.json           → manual overrides (optional)

Nothing is moved. Only .txt files are COPIED into type folders.
PDFs and tables/blocks JSON stay at their original paths (referenced in manifest).

Classification rules (priority order — first match wins):
    1. Source-based definitive (ipc_pvpi, gazette, banned_drugs)
    2. High-specificity filename keywords (theft/recall, spurious/falsified,
       NSQ, IVD, medical device, guideline)
    3. FDC-specific (source=fdc + prohibit/banned in name/first page)
    4. Gazette pattern in filename (S.O. / GSR)
    5. Drug alert (after higher-specificity checks)
    6. Circular
    7. First-page content signals
    8. Fallback → other

Usage:
    python scripts/type_classification.py
    python scripts/type_classification.py --dry-run
    python scripts/type_classification.py --force
    python scripts/type_classification.py --report
    python scripts/type_classification.py --no-copy
"""

import argparse
import csv
import json
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
REPO_ROOT = SCRIPTS_DIR.parent
DOWNLOADS = REPO_ROOT / "downloads"
ANALYSIS_CSV = DOWNLOADS / "_analysis" / "pdf_analysis.csv"
RAW_TEXT = REPO_ROOT / "raw_extraction" / "text"
RAW_OCR = REPO_ROOT / "raw_extraction" / "ocr_tesseract"
OUTPUT_ROOT = REPO_ROOT / "type_classification"
OVERRIDES_FILE = OUTPUT_ROOT / "_overrides.json"


# ---------------------------------------------------------------------------
# Document types
# ---------------------------------------------------------------------------
TYPES = [
    # folder_name,      parser_type,        description
    ("nsq_alert",        "NSQ",              "NSQ drug alerts (batch-level quality failures)"),
    ("spurious_alert",   "SPURIOUS",         "Spurious / counterfeit drug alerts"),
    ("drug_alert",       "DRUG_ALERT",       "Monthly drug alert lists"),
    ("fdc_prohibited",   "FDC",              "FDC prohibition / banning notices"),
    ("fdc_notification", "FDC",              "FDC regulatory process notices"),
    ("gazette_legal",    "GAZETTE_LEGAL",    "S.O. / G.S.R. legal notifications"),
    ("pvpi_safety",      "PVPI",             "PvPI drug safety alerts"),
    ("theft_recall",     "THEFT_RECALL",     "Theft / voluntary recall alerts"),
    ("medical_device",   "MEDICAL_DEVICE",   "Medical device alerts"),
    ("ivd_alert",        "IVD",              "In-vitro diagnostic alerts"),
    ("circular",         "CIRCULAR",         "Circulars and office orders"),
    ("guideline",        "GUIDELINE",        "Guidance documents, drafts, FAQs"),
    ("other",            "OTHER",            "Unclassified / misc"),
]

TYPE_INFO = {t[0]: {"parser": t[1], "description": t[2]} for t in TYPES}
KNOWN_TYPES = set(TYPE_INFO.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_document_id(filename: str) -> str:
    """Extract the numeric document ID from a filename, or use the stem."""
    m = re.match(r"^(\d+)_", filename)
    if m:
        return m.group(1)
    return Path(filename).stem


def rel(path: Path | None) -> str | None:
    """Return path relative to REPO_ROOT, or None."""
    if not path:
        return None
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
# Pre-compiled normalizer: replaces any run of non-alphanumeric chars with
# a single space, then trims and pads with spaces. This makes \b-style
# word-boundary checks work reliably even when filenames use underscores,
# dots, hyphens, or other separators.
_NORM_RE = re.compile(r"[\W_]+")


def _normalize(s: str) -> str:
    """'voluntary_recall_of.pdf' → ' voluntary recall of pdf '"""
    if not s:
        return " "
    return " " + _NORM_RE.sub(" ", s.lower()).strip() + " "


def classify(
    filename: str,
    source: str,
    first_page_text: str,
) -> tuple[str, str, float, list[str]]:
    """
    Classify a document into (type, parser_type, confidence, signals).
    Rules are evaluated in priority order — first match wins.

    Uses space-normalized strings so \\b works correctly — '_' is a word
    character in regex, so \\brecall\\b would fail on 'voluntary_recall_of'.
    """
    name = _normalize(filename)
    first = _normalize((first_page_text or "")[:3000])

    def has(kw: str) -> bool:
        """Word-boundary-safe keyword check on the normalized filename."""
        return _normalize(kw) in name

    def any_has(*kws: str) -> bool:
        return any(has(k) for k in kws)

    def first_has(kw: str) -> bool:
        return _normalize(kw) in first

    # ---- Level 1: Source-based definitive ----
    if source == "ipc_pvpi":
        return "pvpi_safety", "PVPI", 0.99, ["source:ipc_pvpi"]
    if source == "gazette":
        return "gazette_legal", "GAZETTE_LEGAL", 0.98, ["source:gazette"]
    if source == "banned_drugs":
        return "fdc_prohibited", "FDC", 0.95, ["source:banned_drugs"]

    # ---- Level 2: High-specificity filename patterns ----

    # 2A — Theft / recall (very specific; check first)
    if any_has(
        "theft", "recall", "voluntary recall", "stolen",
        "stolen drug", "stolen product",
    ):
        return "theft_recall", "THEFT_RECALL", 0.95, ["filename:theft_or_recall"]

    # 2B — Spurious / falsified (before NSQ and drug alert)
    if any_has(
        "spurious", "falsified", "fake", "counterfeit",
        "misbranded", "adulterated",
    ):
        return "spurious_alert", "SPURIOUS", 0.95, ["filename:spurious_or_falsified"]

    # 2C — NSQ (before drug alert)
    if any_has(
        "nsq",
        "not of standard",
        "not of standard quality",
        "sub standard",
        "substandard",
        "samples declared nsq",
    ):
        return "nsq_alert", "NSQ", 0.95, ["filename:nsq"]

    # 2D — IVD (before medical device since IVD is a subtype)
    if any_has(
        "ivd",
        "in vitro",
        "in vitro diagnostic",
        "diagnostic kit",
        "diagnostic kit alert",
        "mediclone",
        "comipack",
        "mgit",
        "mycobacteria growth indicator tube",
    ):
        return "ivd_alert", "IVD", 0.92, ["filename:ivd"]

    # 2E — Medical device (broad keyword net)
    if any_has(
        "medical device",
        "medical devices",
        "medical device alert",
        "md alert",
        "fsn",
        "field safety notice",
        "heartware",
        "hvad",
        "insulin pump",
        "minimed",
        "ventilator",
        "catheter",
        "guidewire",
        "scaffold",
        "hip system",
        "hip implant",
        "bone screws",
        "embolic",
        "ozurdex",
        "beacon",
        "medtronic",
        "philips",
        "depuy",
    ):
        return "medical_device", "MEDICAL_DEVICE", 0.90, ["filename:medical_device"]

    # 2F — Guideline (before FDC and drug alert; catches "package insert", etc.)
    if any_has(
        "guideline",
        "guidelines",
        "guidance",
        "faq",
        "package insert",
        "approved for marketing",
        "smpc",
        "factsheet",
        "fact sheet",
        "product information",
        "prescribing information",
        "checklist",
        "manual",
    ):
        return "guideline", "GUIDELINE", 0.85, ["filename:guideline"]

    # ---- Level 3: FDC-specific ----
    if source == "fdc" or has("fdc"):
        # Banned / prohibited sub-type
        if any_has(
            "prohibit", "prohibited", "prohibition",
            "banned", "banning",
            "drugs banned",
            "banned in the country",
            "restricted",
            "restriction",
        ):
            return "fdc_prohibited", "FDC", 0.95, ["filename:fdc_prohibit"]
        if (first_has("prohibit") or first_has("prohibited")
                or first_has("banned") or first_has("ban ")):
            return "fdc_prohibited", "FDC", 0.88, ["first_page:prohibition"]
        # Otherwise it's a process / regularisation notice
        return "fdc_notification", "FDC", 0.90, ["source:fdc"]

    # ---- Level 4: Gazette pattern in filename (from non-gazette sources) ----
    # S.O. and G.S.R. are the two legal-instrument prefixes
    if (
        re.search(r"\bs\s*o\s*\d+", name)       # "S.O. 123(E)"
        or re.search(r"\bgsr\s*\d+", name)       # "GSR 123"
        or re.search(r"\bg\s*s\s*r\b", name)     # "G.S.R."
        or has("gazette")
        or has("notification")
    ):
        return "gazette_legal", "GAZETTE_LEGAL", 0.85, ["filename:gazette_pattern"]

    # ---- Level 5: Drug alert (after all higher-specificity checks) ----
    if any_has(
        "drug alert",
        "drugs alert",
        "alert list",
        "drug alert list",
        "alert on",
        "drug alert for",
        "drugs alert for",
        "drug alert january",
        "drug alert february",
        "drug alert march",
        "drug alert april",
        "drug alert may",
        "drug alert june",
        "drug alert july",
        "drug alert august",
        "drug alert september",
        "drug alert october",
        "drug alert november",
        "drug alert december",
    ):
        return "drug_alert", "DRUG_ALERT", 0.90, ["filename:drug_alert"]

    # ---- Level 6: Circular ----
    if any_has(
        "circular",
        "office order",
        "office memorandum",
        "order dated",
    ):
        return "circular", "CIRCULAR", 0.85, ["filename:circular"]

    # ---- Level 7: First-page content signals ----
    if first_has("not of standard") or first_has("nsq"):
        return "nsq_alert", "NSQ", 0.85, ["first_page:nsq"]
    if first_has("spurious") or first_has("falsified"):
        return "spurious_alert", "SPURIOUS", 0.85, ["first_page:spurious"]

    # ---- Default ----
    return "other", "OTHER", 0.5, ["no_match"]


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------
def load_analysis_csv(csv_path: Path) -> dict[tuple[str, str], dict]:
    """Return {(source, filename): {status, pages, text_chars, size_bytes}}."""
    rows: dict[tuple[str, str], dict] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        for row in reader:
            src = (row.get("source") or "").strip()
            fname = (row.get("filename") or "").strip()
            if not src or not fname:
                continue
            def _int(key: str) -> int:
                try:
                    return int(float(row.get(key) or 0))
                except (ValueError, TypeError):
                    return 0
            rows[(src, fname)] = {
                "status": (row.get("status") or "").strip().upper(),
                "pages": _int("pages"),
                "text_chars": _int("text_chars"),
                "size_bytes": _int("size_bytes"),
            }
    return rows


def find_text_source(
    source: str,
    filename: str,
    content_type: str,
) -> tuple[str | None, Path | None, Path | None]:
    """
    Return (origin, txt_path, extra_path):
        origin: "text" | "ocr" | None
        txt_path: Path to .txt (may be None)
        extra_path: Path to .tables.json or .blocks.json (may be None)
    """
    stem = Path(filename).stem
    text_txt = RAW_TEXT / source / f"{stem}.txt"
    text_tbl = RAW_TEXT / source / f"{stem}.tables.json"
    ocr_txt = RAW_OCR / source / f"{stem}.txt"
    ocr_blk = RAW_OCR / source / f"{stem}.blocks.json"

    # Primary: choice based on content_type
    if content_type == "SCANNED" and ocr_txt.exists():
        return "ocr", ocr_txt, (ocr_blk if ocr_blk.exists() else None)
    if content_type in ("TEXT", "MIXED") and text_txt.exists():
        return "text", text_txt, (text_tbl if text_tbl.exists() else None)

    # Fallbacks
    if text_txt.exists():
        return "text", text_txt, (text_tbl if text_tbl.exists() else None)
    if ocr_txt.exists():
        return "ocr", ocr_txt, (ocr_blk if ocr_blk.exists() else None)

    return None, None, None


def read_first_page(txt_path: Path | None, max_chars: int = 3000) -> str:
    """Read first page (up to PAGE 2 marker) or first max_chars."""
    if not txt_path or not txt_path.exists():
        return ""
    try:
        text = txt_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    marker = "===== PAGE 2 ====="
    if marker in text:
        text = text.split(marker, 1)[0]
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def ensure_type_dirs() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for type_name, _, _ in TYPES:
        (OUTPUT_ROOT / type_name).mkdir(exist_ok=True)


def load_overrides() -> dict:
    if not OVERRIDES_FILE.exists():
        return {}
    try:
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[!] Could not read overrides: {exc}")
        return {}
    # Drop keys starting with underscore (comments / examples)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def write_overrides_template() -> None:
    if OVERRIDES_FILE.exists():
        return
    template = {
        "_comment": (
            "Manual overrides for type classification. "
            "Keys are exact PDF filenames (as they appear in downloads/). "
            "Any document listed here will use the specified type/parser."
        ),
        "_example": {
            "12555_NSQ_ALERT_FOR_THE_MONTH_OF_JANUARY-2025.pdf": {
                "type": "nsq_alert",
                "parser": "NSQ",
                "reason": "manual — auto-classified as drug_alert",
            }
        }
    }
    OVERRIDES_FILE.write_text(
        json.dumps(template, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Classify downloaded PDFs into document types."
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Print classification summary only; write nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing .txt copies in type folders.")
    ap.add_argument("--report", action="store_true",
                    help="Write a per-document classification report CSV.")
    ap.add_argument("--no-copy", action="store_true",
                    help="Skip .txt copies; build manifests only.")
    args = ap.parse_args()

    if not ANALYSIS_CSV.exists():
        print(f"[!] Analysis CSV not found: {ANALYSIS_CSV}")
        print("    Run analyze_pdfs.py first.")
        sys.exit(1)

    started = time.time()

    # ---- Load inputs ----
    print(f"[*] Reading {ANALYSIS_CSV.name}...")
    analysis = load_analysis_csv(ANALYSIS_CSV)
    print(f"[*] Loaded {len(analysis)} (source, filename) entries")

    # Group by filename to handle cross-source duplicates
    by_filename: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for (source, filename), info in analysis.items():
        by_filename[filename].append((source, info))

    dup_count = sum(1 for v in by_filename.values() if len(v) > 1)
    print(f"[*] {len(by_filename)} unique filenames "
          f"({dup_count} with duplicate sources)")

    overrides = load_overrides()
    if overrides:
        print(f"[*] Loaded {len(overrides)} manual override(s)")
        for k in overrides:
            if k not in by_filename:
                print(f"    [!] Override for unknown file: {k}")

    if not args.dry_run:
        ensure_type_dirs()
        write_overrides_template()

    # ---- Classify each unique document ----
    print()
    print(f"[*] Classifying {len(by_filename)} documents...")

    all_docs: list[dict] = []
    by_type: dict[str, list[dict]] = defaultdict(list)

    type_priority = {"TEXT": 4, "MIXED": 3, "SCANNED": 2, "EMPTY": 1, "ERROR": 0}

    for filename, source_entries in by_filename.items():
        sources = sorted({s for s, _ in source_entries})

        # Pick the entry with highest-priority content type
        best_source, best_info = max(
            source_entries,
            key=lambda x: type_priority.get(x[1]["status"], -1),
        )
        content_type = best_info["status"]

        # Find text output
        origin, txt_path, extra_path = find_text_source(
            best_source, filename, content_type
        )

        # Read first page for classification signals
        first_page = read_first_page(txt_path) if txt_path else ""

        # Classify
        doc_type, parser_type, confidence, signals = classify(
            filename, best_source, first_page
        )

        # Apply override
        override_applied = False
        if filename in overrides:
            ov = overrides[filename]
            override_type = ov.get("type")
            if override_type in KNOWN_TYPES:
                doc_type = override_type
                parser_type = ov.get(
                    "parser", TYPE_INFO[override_type]["parser"]
                )
                confidence = 1.0
                signals = ["manual_override"]
                override_applied = True
            else:
                print(f"    [!] Unknown override type "
                      f"'{override_type}' for {filename}; ignored")

        # Build document entry
        entry = {
            "filename": filename,
            "document_id": extract_document_id(filename),
            "type": doc_type,
            "parser_type": parser_type,
            "sources": sources,
            "pdf_paths": [
                rel(DOWNLOADS / s / "important" / filename)
                for s in sources
            ],
            "content_type": content_type,
            "text_origin": origin,
            "text_source_path": rel(txt_path),
            "extra_path": rel(extra_path),
            "pages": best_info["pages"],
            "chars": best_info["text_chars"],
            "classification_confidence": confidence,
            "classification_signals": signals,
            "override_applied": override_applied,
            "text_path_in_type_folder": None,
        }

        # Copy .txt into type folder
        if not args.dry_run and not args.no_copy and txt_path and txt_path.exists():
            type_dir = OUTPUT_ROOT / doc_type
            dest = type_dir / f"{Path(filename).stem}.txt"
            if args.force or not dest.exists():
                try:
                    shutil.copy2(txt_path, dest)
                except Exception as exc:
                    print(f"    [!] Copy failed for {filename}: {exc}")
                    dest = None
            if dest and dest.exists():
                entry["text_path_in_type_folder"] = rel(dest)

        all_docs.append(entry)
        by_type[doc_type].append(entry)

    # ---- Summary ----
    print()
    print("=" * 80)
    print("CLASSIFICATION SUMMARY")
    print("=" * 80)
    print(f"{'TYPE':<20} {'PARSER':<15} {'COUNT':>6}")
    print("-" * 80)
    total = 0
    for type_name, parser, _desc in TYPES:
        count = len(by_type.get(type_name, []))
        total += count
        print(f"{type_name:<20} {parser:<15} {count:>6}")
    print("-" * 80)
    print(f"{'TOTAL':<20} {'':<15} {total:>6}")

    # Source breakdown
    source_counts: dict[str, int] = defaultdict(int)
    for doc in all_docs:
        for src in doc["sources"]:
            source_counts[src] += 1

    print()
    print("SOURCE BREAKDOWN")
    print("-" * 40)
    for src in sorted(source_counts):
        print(f"  {src:<20} {source_counts[src]:>6}")

    # Confidence distribution
    buckets = {"<0.70": 0, "0.70-0.80": 0, "0.80-0.90": 0,
               "0.90-0.95": 0, ">=0.95": 0}
    for doc in all_docs:
        c = doc["classification_confidence"]
        if c < 0.70: buckets["<0.70"] += 1
        elif c < 0.80: buckets["0.70-0.80"] += 1
        elif c < 0.90: buckets["0.80-0.90"] += 1
        elif c < 0.95: buckets["0.90-0.95"] += 1
        else: buckets[">=0.95"] += 1

    print()
    print("CONFIDENCE DISTRIBUTION")
    print("-" * 40)
    for bucket, count in buckets.items():
        bar = "█" * min(count, 40)
        print(f"  {bucket:<10} {count:>4}  {bar}")

    # Low-confidence files
    low_conf = [d for d in all_docs if d["classification_confidence"] < 0.85]
    if low_conf:
        print()
        print(f"LOW-CONFIDENCE FILES ({len(low_conf)}) — review or override:")
        for doc in low_conf[:15]:
            print(f"  conf={doc['classification_confidence']:.2f}  "
                  f"type={doc['type']:<18}  {doc['filename'][:70]}")
        if len(low_conf) > 15:
            print(f"  ... and {len(low_conf) - 15} more")

    if args.dry_run:
        print()
        print("[*] Dry-run — no files written.")
        return

    # ---- Write per-type manifests ----
    generated_at = utcnow()
    for type_name, parser, desc in TYPES:
        docs = by_type.get(type_name, [])
        manifest = {
            "type": type_name,
            "parser_type": parser,
            "description": desc,
            "generated_at": generated_at,
            "count": len(docs),
            "documents": sorted(docs, key=lambda x: x["document_id"]),
        }
        (OUTPUT_ROOT / type_name / "_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- Global flat manifest ----
    (OUTPUT_ROOT / "_manifest.json").write_text(
        json.dumps({
            "generated_at": generated_at,
            "total_documents": len(all_docs),
            "documents": sorted(all_docs, key=lambda x: x["document_id"]),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- Index ----
    index = {
        "generated_at": generated_at,
        "total_documents": len(all_docs),
        "types": {},
        "source_breakdown": dict(source_counts),
        "confidence_distribution": buckets,
    }
    for type_name, parser, _desc in TYPES:
        count = len(by_type.get(type_name, []))
        if count:
            index["types"][type_name] = {
                "count": count,
                "parser": parser,
                "manifest": f"{type_name}/_manifest.json",
            }
    (OUTPUT_ROOT / "_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- Optional CSV report ----
    if args.report:
        report_path = OUTPUT_ROOT / "_report.csv"
        fields = [
            "document_id", "type", "parser_type", "confidence",
            "content_type", "text_origin", "sources", "filename", "signals",
        ]
        with report_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for doc in sorted(all_docs,
                              key=lambda x: (x["type"], x["document_id"])):
                w.writerow({
                    "document_id": doc["document_id"],
                    "type": doc["type"],
                    "parser_type": doc["parser_type"],
                    "confidence": doc["classification_confidence"],
                    "content_type": doc["content_type"],
                    "text_origin": doc["text_origin"],
                    "sources": ",".join(doc["sources"]),
                    "filename": doc["filename"],
                    "signals": ",".join(doc["classification_signals"]),
                })
        print(f"\n[+] Report          : {report_path}")

    elapsed = time.time() - started
    print()
    print(f"[+] Elapsed         : {elapsed:.1f}s")
    print(f"[+] Output root     : {OUTPUT_ROOT}")
    print(f"[+] Index           : {OUTPUT_ROOT / '_index.json'}")
    print(f"[+] Flat manifest   : {OUTPUT_ROOT / '_manifest.json'}")
    print(f"[+] Per-type        : {OUTPUT_ROOT}/<type>/_manifest.json")
    print(f"[+] Overrides file  : {OVERRIDES_FILE}")


if __name__ == "__main__":
    main()