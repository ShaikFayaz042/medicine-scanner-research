#!/usr/bin/env python3
"""Classify process_queue PDFs as text, scanned, or mixed and copy them to type folders."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PIPELINE_ROOT / "04_classified_documents" / "process_queue"
DEFAULT_OUTPUT = PIPELINE_ROOT / "05_type_classification"
DEFAULT_REPORT_DIR = DEFAULT_OUTPUT / "output"
VALID_TYPES = ("text", "scanned", "mixed")


def classify_pdf(pdf_path: Path) -> dict[str, object]:
    """Return a classification record for a PDF based on page text/image content."""
    record: dict[str, object] = {
        "filename": pdf_path.name,
        "source": str(pdf_path),
        "type": "scanned",
        "pages": 0,
        "text_pages": 0,
        "scanned_pages": 0,
        "empty_pages": 0,
        "error": None,
    }

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # pragma: no cover - exercised at runtime with bad files
        record["error"] = str(exc)
        return record

    try:
        total_pages = len(doc)
        text_pages = 0
        scanned_pages = 0
        empty_pages = 0

        for page in doc:
            text = page.get_text("text").strip()
            images = page.get_images(full=True)

            if text and len(text) >= 30:
                text_pages += 1
            elif text:
                text_pages += 1
            elif images:
                scanned_pages += 1
            else:
                empty_pages += 1

        if text_pages > 0 and scanned_pages > 0:
            doc_type = "mixed"
        elif text_pages > 0:
            doc_type = "text"
        elif scanned_pages > 0:
            doc_type = "scanned"
        elif empty_pages > 0:
            doc_type = "scanned"
        else:
            doc_type = "scanned"

        record["type"] = doc_type
        record["pages"] = total_pages
        record["text_pages"] = text_pages
        record["scanned_pages"] = scanned_pages
        record["empty_pages"] = empty_pages
        return record
    finally:
        doc.close()


def find_pdfs(input_dir: Path) -> list[Path]:
    return sorted(input_dir.rglob("*.pdf"))


def write_summary_report(results: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total_pdfs": len(results),
        "summary": dict(Counter(result["type"] for result in results)),
        "by_category": {
            "process_queue": dict(Counter(result["type"] for result in results)),
        },
        "details": results,
    }
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv_report(results: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "filename",
        "source",
        "type",
        "pages",
        "text_pages",
        "scanned_pages",
        "empty_pages",
        "error",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result.get(key) for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify process_queue PDFs as text, scanned, or mixed and copy them into the stage-5 folders."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Directory containing PDFs to classify (default: 04_classified_documents/process_queue)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Root directory for type folders (default: 05_type_classification)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_DIR / "pdf_type_classification_report.json",
        help="Path to the JSON summary report",
    )
    parser.add_argument(
        "--csv-report",
        type=Path,
        default=DEFAULT_REPORT_DIR / "pdf_type_classification_report.csv",
        help="Path to the CSV summary report",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report classifications without copying PDFs",
    )
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"Input directory does not exist: {args.input}")

    pdfs = find_pdfs(args.input)
    if not pdfs:
        print(f"No PDFs found in {args.input}")
        return 0

    results: list[dict[str, object]] = []
    copied = 0
    skipped = 0
    manifest: list[dict[str, str]] = []

    for pdf_path in pdfs:
        record = classify_pdf(pdf_path)
        results.append(record)

        doc_type = str(record["type"])
        if doc_type not in VALID_TYPES:
            doc_type = "scanned"

        destination_dir = args.output / doc_type
        destination = destination_dir / pdf_path.name

        if destination.exists():
            status = "EXISTING"
            skipped += 1
        elif args.dry_run:
            status = "PLANNED"
        else:
            destination_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf_path, destination)
            copied += 1
            status = "COPIED"

        manifest.append(
            {
                "filename": pdf_path.name,
                "source": str(pdf_path),
                "type": doc_type,
                "destination": str(destination),
                "status": status,
            }
        )

    write_summary_report(results, args.report)
    write_csv_report(results, args.csv_report)

    if not args.dry_run:
        manifest_path = args.output / "output" / "type_classification_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Found {len(pdfs)} PDFs in {args.input}")
    print(f"Copied: {copied} | Existing: {skipped} | Dry-run: {args.dry_run}")
    summary = Counter(str(result["type"]) for result in results)
    for doc_type in VALID_TYPES:
        print(f"  {doc_type}: {summary.get(doc_type, 0)}")
    print(f"Report: {args.report}")
    print(f"CSV report: {args.csv_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
