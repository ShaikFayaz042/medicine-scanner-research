#!/usr/bin/env python3
"""Extract English text and tables from the paragraph PDF collection.

Text extraction: PyMuPDF (fitz) block-level extraction, in reading order.
Table extraction: pdfplumber, line-based strategies only (no false positives).
Hindi filtering: block-level English-dominance check (>= 85% Latin letters).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pdfplumber


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "paragraph_files"
DEFAULT_MANIFEST = SCRIPT_DIR / "full_corpus_classified_paragraph_only.csv"
DEFAULT_OUTPUT = SCRIPT_DIR / "paragraph_files_extracted"

WHITESPACE = re.compile(r"\s+")

LATIN_RATIO_THRESHOLD = 0.85
MIN_ENGLISH_CHARS = 200
MIN_GOOD_BLOCKS = 2
MIN_BLOCK_LENGTH = 20

HEADER_KEYWORDS = {
    "batch", "category", "date", "device", "drug", "exp", "expiry",
    "failure", "from", "lot", "manufacturer", "mfg", "name", "no",
    "product", "reason", "reported", "result", "serial", "status",
}

# Line-based table detection only.
# The "text" strategy is deliberately excluded: it treats every
# multi-column-looking paragraph as a table, which produces false positives.
TABLE_STRATEGIES: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "lines",
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
        },
    ),
    (
        "lines_strict",
        {
            "vertical_strategy": "lines_strict",
            "horizontal_strategy": "lines_strict",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
        },
    ),
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _is_devanagari(character: str) -> bool:
    return "DEVANAGARI" in unicodedata.name(character, "")


def remove_devanagari(text: str) -> str:
    return "".join(c for c in text if not _is_devanagari(c))


def latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(c.isascii() for c in letters) / len(letters)


def is_english_dominant(text: str, threshold: float = LATIN_RATIO_THRESHOLD) -> bool:
    return latin_ratio(text) >= threshold


def clean_text_block(text: str) -> str:
    """Clean an already-English-dominant block and collapse intra-line spaces."""
    cleaned = remove_devanagari(text)
    lines = [WHITESPACE.sub(" ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# PyMuPDF text extraction
# ---------------------------------------------------------------------------


def extract_blocks_fitz(page: fitz.Page) -> list[dict[str, Any]]:
    """Return English-dominant text blocks from a PyMuPDF page in reading order."""
    blocks: list[dict[str, Any]] = []
    try:
        raw_blocks = page.get_text("blocks", sort=True)
    except TypeError:
        # Older PyMuPDF versions may not accept the sort kwarg.
        raw_blocks = page.get_text("blocks")

    for block in raw_blocks:
        x0, y0, x1, y1, raw_text, _block_no, block_type = block
        if block_type != 0:  # 0 = text, 1 = image
            continue
        if not raw_text or not raw_text.strip():
            continue
        if not is_english_dominant(raw_text):
            continue  # Hindi-dominant block: discard entirely
        cleaned = clean_text_block(raw_text)
        if not cleaned:
            continue
        blocks.append(
            {
                "bbox": [
                    round(float(x0), 2),
                    round(float(y0), 2),
                    round(float(x1), 2),
                    round(float(y1), 2),
                ],
                "text": cleaned,
            }
        )
    return blocks


# ---------------------------------------------------------------------------
# pdfplumber table extraction (line-based only)
# ---------------------------------------------------------------------------


def clean_table_cell(value: Any) -> str:
    return WHITESPACE.sub(" ", remove_devanagari(str(value or ""))).strip()


def normalize_table(rows: list[list[Any]]) -> list[list[str]]:
    normalized: list[list[str]] = []
    for row in rows:
        cells = [clean_table_cell(value) for value in row]
        while cells and not cells[-1]:
            cells.pop()
        if any(cells):
            normalized.append(cells)
    return normalized


def detect_header_row(rows: list[list[str]]) -> int | None:
    """Pick the most header-like row from the first ten rows."""
    best_index: int | None = None
    best_score = 0.0

    for index, row in enumerate(rows[:10]):
        cells = [cell for cell in row if cell]
        if len(cells) < 2:
            continue
        words = [word.casefold() for cell in cells for word in re.findall(r"[a-z]+", cell)]
        if not words:
            continue
        keyword_hits = sum(word in HEADER_KEYWORDS for word in words)
        text_cells = sum(any(c.isalpha() for c in cell) for cell in cells)
        unique_ratio = len({cell.casefold() for cell in cells}) / len(cells)
        average_length = sum(len(cell) for cell in cells) / len(cells)
        score = keyword_hits * 5 + text_cells * 2 + unique_ratio + min(average_length, 20) / 20

        if text_cells >= 2 and unique_ratio >= 0.5 and score > best_score:
            best_index = index
            best_score = score

    return best_index


def is_real_table(rows: list[list[str]]) -> bool:
    """Reject paragraph-shaped false positives from line-based detection."""
    if len(rows) < 2:
        return False
    wide_rows = [row for row in rows if sum(bool(cell) for cell in row) >= 2]
    return len(wide_rows) >= 2


def find_tables(page: pdfplumber.page.Page, page_number: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, ...], ...]] = set()

    for strategy_name, settings in TABLE_STRATEGIES:
        try:
            candidates = page.find_tables(table_settings=settings)
        except Exception:
            continue

        for candidate in candidates:
            try:
                rows = normalize_table(candidate.extract() or [])
            except Exception:
                continue
            if not is_real_table(rows):
                continue

            signature = tuple(tuple(row) for row in rows)
            if signature in seen:
                continue
            seen.add(signature)

            header_index = detect_header_row(rows)
            bbox = [round(float(v), 2) for v in candidate.bbox]
            found.append(
                {
                    "page": page_number,
                    "detection_strategy": strategy_name,
                    "bbox": bbox,
                    "header_row_index": header_index,
                    "headers": rows[header_index] if header_index is not None else [],
                    "rows": rows,
                }
            )

    return found


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------


def extraction_quality(pages: list[dict[str, Any]]) -> dict[str, Any]:
    total_chars = sum(len(p.get("english_text", "")) for p in pages)
    good_blocks = 0
    for page in pages:
        for block in page.get("blocks", []):
            text = block.get("text", "")
            if len(text) >= MIN_BLOCK_LENGTH and text[:1].isupper():
                good_blocks += 1

    reconstructable = total_chars >= MIN_ENGLISH_CHARS and good_blocks >= MIN_GOOD_BLOCKS

    if total_chars == 0:
        flag = "NO_ENGLISH"
    elif reconstructable:
        flag = "GOOD"
    else:
        flag = "POOR"

    return {
        "total_english_chars": total_chars,
        "good_blocks": good_blocks,
        "reconstructable": reconstructable,
        "flag": flag,
    }


# ---------------------------------------------------------------------------
# Per-PDF driver
# ---------------------------------------------------------------------------


def extract_pdf(pdf_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file_name": pdf_path.name,
        "status": "COMPLETE",
        "page_count": 0,
        "pages_with_english_text": 0,
        "table_count": 0,
        "pages": [],
        "quality": {},
        "error": None,
    }

    try:
        fitz_doc = fitz.open(str(pdf_path))
    except Exception as exc:
        result["status"] = "FAILED"
        result["error"] = f"PyMuPDF open failed: {exc}"
        return result

    result["page_count"] = fitz_doc.page_count

    try:
        with pdfplumber.open(str(pdf_path)) as plumber_pdf:
            plumber_page_count = len(plumber_pdf.pages)
            for page_index in range(fitz_doc.page_count):
                fitz_page = fitz_doc.load_page(page_index)
                page_number = page_index + 1

                blocks = extract_blocks_fitz(fitz_page)
                english_text = "\n\n".join(b["text"] for b in blocks)

                tables: list[dict[str, Any]] = []
                if page_index < plumber_page_count:
                    tables = find_tables(plumber_pdf.pages[page_index], page_number)

                result["pages"].append(
                    {
                        "page": page_number,
                        "text_method": "fitz_blocks",
                        "english_text": english_text,
                        "blocks": blocks,
                        "tables": tables,
                    }
                )
                if english_text:
                    result["pages_with_english_text"] += 1
                result["table_count"] += len(tables)
    except Exception as exc:
        result["status"] = "FAILED"
        result["error"] = f"Page loop failed: {exc}"
        fitz_doc.close()
        return result

    fitz_doc.close()

    quality = extraction_quality(result["pages"])
    result["quality"] = quality
    if quality["flag"] == "NO_ENGLISH":
        result["status"] = "NO_ENGLISH_TEXT"
    elif quality["flag"] == "POOR":
        result["status"] = "POOR_EXTRACTION"

    return result


# ---------------------------------------------------------------------------
# Manifest & IO
# ---------------------------------------------------------------------------


def table_headers(record: dict[str, Any]) -> list[dict[str, Any]]:
    headers: list[dict[str, Any]] = []
    for page in record.get("pages", []):
        for table in page.get("tables", []):
            if table.get("headers"):
                headers.append({"page": table["page"], "headers": table["headers"]})
    return headers


def load_existing_result(output_path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def manifest_file_key(source: str, filename: str) -> str:
    source_path = Path(source.strip()) if source.strip() else Path()
    return (source_path / filename).as_posix()


def source_directory(input_dir: Path, source: str) -> Path | None:
    source_path = Path(source.strip()) if source.strip() else Path()
    if source_path.is_absolute() or ".." in source_path.parts:
        return None

    input_root = input_dir.resolve()
    directory = (input_root / source_path).resolve()
    try:
        directory.relative_to(input_root)
    except ValueError:
        return None
    return directory


def update_manifest(
    manifest_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
    results: dict[str, dict[str, Any]],
) -> None:
    added_fields = [
        "Text Characters",
        "Extraction Status",
        "Extracted JSON",
        "Pages Processed",
        "Pages With English Text",
        "Table Found",
        "Table Count",
        "Table Headers",
        "Table Pages",
        "Quality Flag",
        "Reconstructable",
        "Good Blocks",
    ]
    output_fields = fieldnames + [name for name in added_fields if name not in fieldnames]
    temporary_path = manifest_path.with_name(f"{manifest_path.name}.tmp")

    with temporary_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()

        for row in rows:
            filename = row.get("File Name", "")
            source = row.get("Source", "") or ""
            record = results.get(manifest_file_key(source, filename), {})
            headers = table_headers(record)
            quality = record.get("quality", {}) or {}

            text_characters = sum(
                len(page.get("english_text", ""))
                for page in record.get("pages", [])
            )
            pages_with_tables = sorted(
                {
                    table["page"]
                    for page in record.get("pages", [])
                    for table in page.get("tables", [])
                }
            )
            row.update(
                {
                    "Text Characters": str(text_characters),
                    "Extraction Status": record.get("status", "NOT_PROCESSED"),
                    "Extracted JSON": (
                        (Path(source) / f"{Path(filename).stem}.json").as_posix()
                        if filename
                        else ""
                    ),
                    "Pages Processed": str(record.get("page_count", 0)),
                    "Pages With English Text": str(record.get("pages_with_english_text", 0)),
                    "Table Found": "yes" if record.get("table_count", 0) else "no",
                    "Table Count": str(record.get("table_count", 0)),
                    "Table Headers": json.dumps(headers, ensure_ascii=False),
                    "Table Pages": json.dumps(pages_with_tables),
                    "Quality Flag": quality.get("flag", ""),
                    "Reconstructable": str(quality.get("reconstructable", "")),
                    "Good Blocks": str(quality.get("good_blocks", "")),
                }
            )
            writer.writerow(row)

    os.replace(temporary_path, manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract English text and detected tables from paragraph PDFs."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="PDF input folder")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="CSV manifest to update")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Per-PDF JSON output folder")
    parser.add_argument("--force", action="store_true", help="Re-extract PDFs with existing JSON output")
    args = parser.parse_args()

    if not args.input.is_dir():
        parser.error(f"PDF input folder does not exist: {args.input}")
    if not args.manifest.is_file():
        parser.error(f"CSV manifest does not exist: {args.manifest}")

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or "File Name" not in reader.fieldnames:
            parser.error("CSV manifest must contain a 'File Name' column")
        fieldnames = reader.fieldnames
        manifest_rows = list(reader)

    args.output.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    input_root = args.input.resolve()

    total_files = len(manifest_rows)
    for index, row in enumerate(manifest_rows, start=1):
        filename = (row.get("File Name") or "").strip()
        source = (row.get("Source") or "").strip()
        result_key = manifest_file_key(source, filename)
        print(f"[{index}/{total_files}] Processing: {filename or '<empty filename>'}", flush=True)

        if not filename or Path(filename).name != filename or Path(filename).suffix.casefold() != ".pdf":
            results[result_key] = {
                "status": "INVALID_FILENAME",
                "pages": [],
                "table_count": 0,
                "quality": {"flag": "INVALID_FILENAME"},
            }
            continue

        source_dir = source_directory(args.input, source)
        if source_dir is None:
            results[result_key] = {
                "status": "INVALID_FILENAME",
                "pages": [],
                "table_count": 0,
                "quality": {"flag": "INVALID_FILENAME"},
            }
            continue

        pdf_path = source_dir / filename
        if not pdf_path.is_file() and source_dir != input_root:
            root_candidate = input_root / filename
            if root_candidate.is_file():
                pdf_path = root_candidate

        relative_json_path = Path(source) / f"{Path(filename).stem}.json"
        json_path = args.output / relative_json_path

        if not pdf_path.is_file():
            results[result_key] = {
                "status": "MISSING_PDF",
                "pages": [],
                "table_count": 0,
                "quality": {"flag": "MISSING_PDF"},
            }
            continue

        record = None if args.force else load_existing_result(json_path)
        if record is None:
            record = extract_pdf(pdf_path)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        else:
            record["status"] = "SKIPPED_EXISTING"

        results[result_key] = record

    update_manifest(args.manifest, manifest_rows, fieldnames, results)

    counts: dict[str, int] = {}
    for record in results.values():
        status = str(record.get("status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1

    print(f"Processed manifest rows: {len(manifest_rows)}")
    print(f"Statuses: {json.dumps(counts, sort_keys=True)}")
    print(f"JSON output: {args.output}")
    print(f"Updated CSV: {args.manifest}")

    failure_statuses = {"FAILED", "MISSING_PDF", "INVALID_FILENAME"}
    return 1 if any(status in failure_statuses for status in counts) else 0


if __name__ == "__main__":
    raise SystemExit(main())