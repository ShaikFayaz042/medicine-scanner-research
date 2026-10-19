"""Score the extractor + parser against hand-verified records from real CDSCO PDFs.

The golden set (golden.json) lists, for each document, the number of data rows the PDF contains and a
few sample rows checked by eye against the rendered pages. Scoring runs the production extraction and
parsing functions only (no S3, no database).

    python -m data_processing_service.tests.regression.harness                    # scorecard
    python -m data_processing_service.tests.regression.harness --update-baseline  # ratchet baselines up

Baselines only move up: --update-baseline records a document's new score when it beats the stored one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLDEN_PATH = Path(__file__).with_name("golden.json")
SOURCE_PREFIX = "medicine-data-storage/source_files"
SCRAPER_SOURCE_BY_CATEGORY = {"alerts": "cdsco_alerts", "fdc": "cdsco_fdc", "banned_drugs": "cdsco_banned_drugs"}

_PRODUCT_KEY = re.compile(r"product|drug|name|vaccine", re.I)
_MANUFACTURER_KEY = re.compile(r"manufactur", re.I)
_BATCH_KEY = re.compile(r"batch|b\.?\s*no\b|lot", re.I)
_NOTIFICATION_KEY = re.compile(r"notification|s\.?\s*o\b|g\.?\s*s\.?\s*r", re.I)


def load_golden(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


def pdf_path(document: dict[str, Any]) -> Path:
    return REPO_ROOT / document["file"]


def fixture_status(document: dict[str, Any]) -> str | None:
    """Return a skip reason when the PDF is missing or differs from the verified copy."""
    path = pdf_path(document)
    if not path.is_file():
        return f"missing {document['file']} (run fetch_fixtures)"
    if hashlib.sha256(path.read_bytes()).hexdigest() != document["sha256"]:
        return f"{document['file']} differs from the verified copy (sha256 mismatch)"
    return None


def _alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _code(value: Any) -> str:
    """Batch numbers compare exactly apart from case, outer punctuation and repeated whitespace."""
    return re.sub(r"\s+", " ", str(value or "")).strip(" .,;:").upper()


def _role_values(record: dict[str, Any], key_pattern: re.Pattern[str]) -> list[str]:
    return [
        str(value)
        for key, value in record.items()
        if key_pattern.search(str(key)) and not (key_pattern is _PRODUCT_KEY and _MANUFACTURER_KEY.search(str(key)))
    ]


def sample_matches(sample: dict[str, str], record: dict[str, Any]) -> bool:
    """A sample matches when one record holds its product, and its batch or notification (when given), under the right columns."""
    if not any(_alnum(sample["product"]) in _alnum(value) for value in _role_values(record, _PRODUCT_KEY)):
        return False
    if "batch" in sample:
        return any(_code(sample["batch"]) == _code(value) for value in _role_values(record, _BATCH_KEY))
    if "notification" not in sample:
        return True  # product-only sample (a device alert names no batch)
    return any(_alnum(sample["notification"]) in _alnum(value) for value in _role_values(record, _NOTIFICATION_KEY))


def run_pipeline(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Run production extraction and parsing on one golden PDF and return the parsed records."""
    from data_processing_service.extractor import run as extractor
    from data_processing_service.parser import run as parser

    path = pdf_path(document)
    category = document["source_category"]
    payload = extractor._extract_document_from_bytes(
        path.read_bytes(), f"{SOURCE_PREFIX}/{category}/{path.name}", SOURCE_PREFIX
    )
    scraper_source = SCRAPER_SOURCE_BY_CATEGORY.get(category, category)
    payload.update({
        "pdf_title": document["title"],
        "source_category": category,
        "source_name": scraper_source,
        "scraper_metadata": {"title": document["title"], "source": scraper_source, "release_date": document["release_date"]},
    })
    return parser._process_single_payload(payload)["records"]


def score(document: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    expected = document["rows_expected"]
    samples = document["samples"]
    matched = [sample for sample in samples if any(sample_matches(sample, record) for record in records)]
    return {
        "rows_parsed": len(records),
        "rows_expected": expected,
        "rows_matched": min(len(records), expected),
        "rows_extra": max(len(records) - expected, 0),
        "samples_correct": len(matched),
        "samples_total": len(samples),
        "samples_missed": [sample["s_no"] for sample in samples if sample not in matched],
    }


def meets_baseline(result: dict[str, Any], baseline: dict[str, int]) -> list[str]:
    """Return the ways a result falls below its recorded baseline (empty when it does not regress)."""
    problems = []
    if result["rows_matched"] < baseline["rows_matched"]:
        problems.append(f"rows_matched {result['rows_matched']} < baseline {baseline['rows_matched']}")
    if result["rows_extra"] > baseline["rows_extra"]:
        problems.append(f"rows_extra {result['rows_extra']} > baseline {baseline['rows_extra']}")
    if result["samples_correct"] < baseline["samples_correct"]:
        problems.append(f"samples_correct {result['samples_correct']} < baseline {baseline['samples_correct']}")
    return problems


def _improved(result: dict[str, Any], baseline: dict[str, int]) -> bool:
    return (
        not meets_baseline(result, baseline)
        and (
            result["rows_matched"] > baseline["rows_matched"]
            or result["rows_extra"] < baseline["rows_extra"]
            or result["samples_correct"] > baseline["samples_correct"]
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score extraction + parsing against the real-PDF golden set.")
    parser.add_argument("--update-baseline", action="store_true", help="Raise baselines for documents that improved")
    parser.add_argument("--skip-ocr", action="store_true", help="Skip documents that need OCR")
    args = parser.parse_args(argv)

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    totals = {"rows_matched": 0, "rows_expected": 0, "samples_correct": 0, "samples_total": 0}
    regressions = 0
    print(f"{'document':58} {'rows':>9} {'extra':>5} {'samples':>8}  status")
    for document in golden["documents"]:
        skip = fixture_status(document) or ("needs OCR" if args.skip_ocr and document["requires_ocr"] else None)
        if skip:
            print(f"{document['id'] + ' ' + document['title'][:50]:58} {'-':>9} {'-':>5} {'-':>8}  skipped: {skip}")
            continue
        result = score(document, run_pipeline(document))
        problems = meets_baseline(result, document["baseline"])
        if problems:
            status, regressions = "REGRESSION: " + "; ".join(problems), regressions + 1
        elif _improved(result, document["baseline"]):
            status = "improved"
            if args.update_baseline:
                document["baseline"] = {key: result[key] for key in ("rows_matched", "rows_extra", "samples_correct")}
                status += " (baseline raised)"
        else:
            status = "ok"
        if result["samples_missed"]:
            status += f"; missed samples {result['samples_missed']}"
        for key in totals:
            totals[key] += result[key]
        print(
            f"{document['id'] + ' ' + document['title'][:50]:58} "
            f"{result['rows_matched']:>4}/{result['rows_expected']:<4} {result['rows_extra']:>5} "
            f"{result['samples_correct']:>3}/{result['samples_total']:<4}  {status}"
        )
    print(
        f"\nTOTAL rows {totals['rows_matched']}/{totals['rows_expected']}"
        f"  samples {totals['samples_correct']}/{totals['samples_total']}  regressions {regressions}"
    )
    if args.update_baseline:
        GOLDEN_PATH.write_text(json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
