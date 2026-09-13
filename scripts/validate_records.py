#!/usr/bin/env python3
"""
Record-level validation across all structured_raw types.

Per-type contracts enforced:
    nsq, drug_alert      → must have product_name + batch_no
    spurious             → must have product_name (batch optional)
    fdc_prohibited       → must have composition OR notification_number
    fdc_notification     → if table: composition; if prose: text
    gazette_legal        → if prose: subject OR notif OR date
    pvpi_safety          → must have suspected_drug + adr
    theft_recall,
    medical_device,
    ivd_alert,
    circular,
    guideline,
    other                → if prose: raw_text present

Outputs:
    structured_raw/_record_validation.json   — per-type detailed report
    structured_raw/_record_validation.txt    — human-readable summary
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
REPO_ROOT = SCRIPTS_DIR.parent
STRUCTURED = REPO_ROOT / "structured_raw"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Per-type record contracts
# ---------------------------------------------------------------------------
def _non_empty(canonical: dict, key: str, min_len: int = 1) -> bool:
    v = str(canonical.get(key, "") or "").strip()
    return len(v) >= min_len


def check_nsq_like(canonical: dict, raw: dict, rec: dict) -> tuple[bool, list[str]]:
    """NSQ / drug_alert records: product required; batch is preferred."""
    issues = []
    if not _non_empty(canonical, "product_name", 3):
        issues.append("missing_product")
    if not _non_empty(canonical, "batch_no", 2):
        issues.append("missing_batch_soft")
    fatal = [issue for issue in issues if issue != "missing_batch_soft"]
    return (len(fatal) == 0, issues)


def check_spurious(canonical: dict, raw: dict, rec: dict) -> tuple[bool, list[str]]:
    issues = []
    if not _non_empty(canonical, "product_name", 3):
        issues.append("missing_product")
    # batch optional
    return (len(issues) == 0, issues)


def check_fdc(canonical: dict, raw: dict, rec: dict) -> tuple[bool, list[str]]:
    """FDC records: composition OR notification number."""
    issues = []
    has_comp = _non_empty(canonical, "composition", 3)
    has_notif = _non_empty(canonical, "notification_number", 3)
    if rec.get("prose") or len(str(rec.get("raw_text") or "")) >= 50:
        return (True, [])
    if not (has_comp or has_notif):
        issues.append("missing_composition_and_notification")
    return (len(issues) == 0, issues)


def check_pvpi(canonical: dict, raw: dict, rec: dict) -> tuple[bool, list[str]]:
    issues = []
    if not _non_empty(canonical, "suspected_drug", 2):
        issues.append("missing_drug")
    if not _non_empty(canonical, "adr", 2):
        issues.append("missing_adr")
    return (len(issues) == 0, issues)


def check_prose(canonical: dict, raw: dict, rec: dict) -> tuple[bool, list[str]]:
    """Prose records: metadata may live under detected or raw text."""
    issues = []
    detected = rec.get("detected", {}) or {}
    has_subject = bool((detected.get("subject") or canonical.get("subject") or "").strip())
    has_dates = bool(detected.get("dates")) or bool(raw.get("all_dates"))
    has_notifs = (bool(detected.get("notification_numbers"))
                  or bool(raw.get("all_notification_numbers"))
                  or _non_empty(canonical, "notification_number", 3))
    has_raw_text = len(str(rec.get("raw_text") or "")) >= 50
    if not (has_subject or has_dates or has_notifs or has_raw_text):
        issues.append("no_prose_metadata")
    return (len(issues) == 0, issues)


# Type → checker
CHECKERS = {
    "nsq":              check_nsq_like,
    "drug_alert":       check_nsq_like,
    "spurious":         check_spurious,
    "fdc_prohibited":   check_fdc,
    "fdc_notification": check_fdc,
    "pvpi_safety":      check_pvpi,
    "gazette_legal":    check_prose,
    "theft_recall":     check_prose,
    "medical_device":   check_prose,
    "ivd_alert":        check_prose,
    "circular":         check_prose,
    "guideline":        check_prose,
    "other":            check_prose,
}


# ---------------------------------------------------------------------------
def validate_record(rec: dict, doc_type: str) -> tuple[bool, list[str]]:
    """Dispatch to the right checker. Handles prose vs table records."""
    canonical = rec.get("canonical", {}) or {}
    raw = rec.get("raw_data", {}) or {}
    is_prose = bool(rec.get("prose"))

    # Prose records always use the prose checker
    if is_prose:
        return check_prose(canonical, raw, rec)

    checker = CHECKERS.get(doc_type, check_prose)
    return checker(canonical, raw, rec)


# ---------------------------------------------------------------------------
def validate_all():
    report = {
        "generated_at": utcnow(),
        "types": {},
        "totals": {
            "documents": 0,
            "records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "documents_with_issues": 0,
        },
    }

    for type_dir in sorted(STRUCTURED.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("_"):
            continue
        type_name = type_dir.name
        manifest_path = type_dir / "_manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        docs_meta = manifest.get("documents", [])

        type_stats = {
            "documents": 0,
            "records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "issue_counts": defaultdict(int),
            "documents_with_issues": 0,
            "examples": [],
        }

        for meta in docs_meta:
            if meta.get("status") not in ("SUCCESS", "skipped", "EMPTY"):
                continue
            filename = meta.get("filename")
            if not filename:
                continue
            stem = Path(filename).stem
            doc_path = type_dir / f"{stem}.json"
            if not doc_path.exists():
                continue
            try:
                data = json.loads(doc_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            type_stats["documents"] += 1
            doc_records = data.get("records", [])
            doc_issues = 0

            for i, rec in enumerate(doc_records):
                type_stats["records"] += 1
                ok, issues = validate_record(rec, type_name)
                if ok:
                    type_stats["valid_records"] += 1
                else:
                    type_stats["invalid_records"] += 1
                    doc_issues += 1
                    for issue in issues:
                        type_stats["issue_counts"][issue] += 1
                    if len(type_stats["examples"]) < 5:
                        type_stats["examples"].append({
                            "document": filename,
                            "record_index": i,
                            "issues": issues,
                            "canonical_sample": {
                                k: str(v)[:50]
                                for k, v in list(
                                    rec.get("canonical", {}).items()
                                )[:4]
                            },
                        })

            if doc_issues > 0:
                type_stats["documents_with_issues"] += 1

        # Finalize type stats
        type_stats["issue_counts"] = dict(type_stats["issue_counts"])
        report["types"][type_name] = type_stats
        report["totals"]["documents"] += type_stats["documents"]
        report["totals"]["records"] += type_stats["records"]
        report["totals"]["valid_records"] += type_stats["valid_records"]
        report["totals"]["invalid_records"] += type_stats["invalid_records"]
        report["totals"]["documents_with_issues"] += (
            type_stats["documents_with_issues"]
        )

    return report


def write_report(report):
    # JSON
    (STRUCTURED / "_record_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # TXT
    lines = []
    lines.append("=" * 82)
    lines.append("RECORD-LEVEL VALIDATION")
    lines.append("=" * 82)
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")
    lines.append(
        f"{'TYPE':<20} {'DOCS':>5} {'RECORDS':>8} {'VALID':>7} "
        f"{'INVALID':>8} {'DOCS_W/ISSUES':>14}"
    )
    lines.append("-" * 82)
    t = report["totals"]
    for type_name, s in sorted(report["types"].items()):
        lines.append(
            f"{type_name:<20} {s['documents']:>5} {s['records']:>8} "
            f"{s['valid_records']:>7} {s['invalid_records']:>8} "
            f"{s['documents_with_issues']:>14}"
        )
    lines.append("-" * 82)
    lines.append(
        f"{'TOTAL':<20} {t['documents']:>5} {t['records']:>8} "
        f"{t['valid_records']:>7} {t['invalid_records']:>8} "
        f"{t['documents_with_issues']:>14}"
    )
    lines.append("")
    lines.append("ISSUE BREAKDOWN PER TYPE")
    lines.append("-" * 82)
    for type_name, s in sorted(report["types"].items()):
        if not s["issue_counts"]:
            continue
        lines.append(f"\n  {type_name}")
        for issue, count in sorted(s["issue_counts"].items(),
                                   key=lambda x: -x[1]):
            lines.append(f"    {issue:<45} {count:>6}")
    lines.append("")
    lines.append("=" * 82)
    (STRUCTURED / "_record_validation.txt").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main():
    print(f"[*] Validating records in {STRUCTURED} ...")
    report = validate_all()
    write_report(report)
    t = report["totals"]
    print()
    print("=" * 82)
    print("RECORD VALIDATION COMPLETE")
    print("=" * 82)
    print(f"{'TYPE':<20} {'DOCS':>5} {'RECORDS':>8} {'VALID':>7} "
          f"{'INVALID':>8} {'ISSUES':>7}")
    print("-" * 82)
    for type_name, s in sorted(report["types"].items()):
        print(f"{type_name:<20} {s['documents']:>5} {s['records']:>8} "
              f"{s['valid_records']:>7} {s['invalid_records']:>8} "
              f"{s['documents_with_issues']:>7}")
    print("-" * 82)
    print(f"{'TOTAL':<20} {t['documents']:>5} {t['records']:>8} "
          f"{t['valid_records']:>7} {t['invalid_records']:>8} "
          f"{t['documents_with_issues']:>7}")
    print()
    print(f"[+] JSON : {STRUCTURED / '_record_validation.json'}")
    print(f"[+] TXT  : {STRUCTURED / '_record_validation.txt'}")


if __name__ == "__main__":
    main()