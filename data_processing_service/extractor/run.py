"""Extract text and tables from PDFs stored in S3, with RapidOCR fallback for scanned pages.

The output is written back to S3 as JSON and the matching Supabase document row is
updated with processing_stage='extracted'.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
import pymupdf
import pdfplumber

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_processing_service.shared.config import (
    AWS_REGION,
    S3_INPUT_BUCKET,
    S3_INPUT_PREFIX,
    S3_OUTPUT_BUCKET,
    S3_OUTPUT_PREFIX,
)
from data_processing_service.shared.database import (
    get_document_metadata,
    update_extracted_documents,
)
from data_processing_service.shared.manifest import read_manifest, utc_now_iso, write_result
from data_processing_service.extractor import ocr as page_ocr

# A page whose text layer is shorter than this, while images cover most of it, is a scan with a stamp,
# footer or page number on top; its real content is only in the image.
SPARSE_TEXT_CHARS = 200
IMAGE_COVER_FOR_OCR = 0.5
# Share of undecodable glyphs (U+FFFD, "(cid:NN)") above which a text layer is treated as unusable.
GARBLED_TEXT_RATIO = 0.02

DEFAULT_S3_INPUT_BUCKET = S3_INPUT_BUCKET
DEFAULT_S3_INPUT_PREFIX = S3_INPUT_PREFIX
DEFAULT_S3_OUTPUT_BUCKET = S3_OUTPUT_BUCKET or S3_INPUT_BUCKET
DEFAULT_S3_OUTPUT_PREFIX = S3_OUTPUT_PREFIX
DEFAULT_AWS_REGION = AWS_REGION
SOURCE_CATEGORY_BY_SOURCE = {
    "cdsco_alerts": "alerts",
    "cdsco_banned_drugs": "banned_drugs",
    "cdsco_fdc": "fdc",
    "ipc_pvpi": "ipc",
}


def _safe_object_key_for_s3(subpath: str) -> str:
    return subpath.strip("/")


def _source_name_from_key(key: str, prefix: str) -> str:
    relative_key = key.removeprefix(prefix).lstrip("/")
    if not relative_key:
        return "unknown"
    parts = PurePosixPath(relative_key).parts
    return parts[0] if len(parts) > 1 else PurePosixPath(relative_key).stem or "unknown"


def _page_text(page: Any) -> str:
    try:
        text = (page.get_text("text") or "").strip()
    except Exception:
        return ""
    return _without_overprint(page) or text


def _without_overprint(page: Any) -> str | None:
    """Page text with fake-bold copies removed, or None when the page has none.

    Some gazettes draw bold headings by printing the same span several times a fraction of a point
    apart; the text layer then repeats every word ("S.O. 4482\\nS.O. 4482\\nS.O. 4482(E).\\n(E).").
    """
    try:
        blocks = page.get_text("rawdict").get("blocks", [])
    except Exception:
        return None
    # The copies are split into spans differently, so compare characters: a character is a copy when the
    # same character was already placed less than a third of its width away (a repeated letter, as in
    # "ll", sits a full width away). Points are bucketed by whole pt for a constant-time lookup.
    placed: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    out_blocks, duplicates = [], 0
    for block in blocks:
        out_lines = []
        for line in block.get("lines", []):
            kept = []
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    c, (x, y) = char.get("c", ""), char.get("origin", (0.0, 0.0))
                    bbox = char.get("bbox", (x, y, x, y))
                    tolerance = max(0.15, 0.35 * (bbox[2] - bbox[0]))
                    gx, gy = int(x), int(y)
                    # Combining marks (the Devanagari virama in conjuncts) legitimately share a position.
                    if not unicodedata.category(c or " ").startswith("M") and any(
                        abs(x - px) < tolerance and abs(y - py) < tolerance
                        for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                        for px, py in placed.get((c, gx + dx, gy + dy), ())
                    ):
                        duplicates += 1
                        continue
                    placed.setdefault((c, gx, gy), []).append((x, y))
                    kept.append(c)
            if "".join(kept).strip():
                out_lines.append("".join(kept))
        if out_lines:
            out_blocks.append("\n".join(out_lines))
    return "\n".join(out_blocks).strip() if duplicates > 5 else None


def _is_valid_table_candidate(rows: list[list[str]]) -> bool:
    if not rows or len(rows) < 2:
        return False

    # Rows with a single filled cell are full-width section titles ("B. State Laboratories") or text
    # continuations; they are part of real tables, so only multi-cell rows decide the width spread.
    widths = [
        filled
        for row in rows
        if (filled := sum(1 for cell in row if str(cell).strip())) >= 2
    ]
    if len(widths) < 2:
        return False

    # Merged cells make sparse rows common, so allow a modest spread between multi-cell rows.
    return max(widths) - min(widths) <= 6


def _is_valid_text_strategy_table(rows: list[list[str]]) -> bool:
    if not rows or len(rows) < 3:
        return False

    col_counts = [len([cell for cell in row if str(cell).strip()]) for row in rows]
    if not col_counts or max(col_counts) < 2:
        return False
    if min(col_counts) < 2:
        return False
    if max(col_counts) - min(col_counts) > 2:
        return False

    for row in rows:
        for cell in row:
            if len(str(cell)) > 200:
                return False

    header = rows[0]
    if any(str(cell).rstrip().endswith((".", "?", "!")) for cell in header):
        return False

    return True


def _extract_table_rows_from_page(plumber_page: Any) -> tuple[list[list[str]], str]:
    if plumber_page is None:
        return [], "none"

    strategies = [
        ("default", {}),
        ("text", {"vertical_strategy": "text", "horizontal_strategy": "text"}),
        ("mixed_v_text", {"vertical_strategy": "lines", "horizontal_strategy": "text"}),
        ("mixed_h_text", {"vertical_strategy": "text", "horizontal_strategy": "lines"}),
    ]

    for strategy_name, settings in strategies:
        try:
            # Follow the PDF's text order inside cells; position-based word gaps letter-space justified
            # text ("p h y s i c a l").
            tables = plumber_page.extract_tables({**settings, "text_use_text_flow": True}) or []
        except Exception:
            continue

        normalized: list[list[str]] = []
        for table in tables:
            if not table:
                continue
            rows = []
            for row in table:
                cells = [str(cell).strip() if cell is not None else "" for cell in row]
                if cells:
                    rows.append(cells)

            if strategy_name == "text":
                if rows and _is_valid_text_strategy_table(rows):
                    normalized.append(rows)
            elif rows and _is_valid_table_candidate(rows):
                normalized.append(rows)
            elif strategy_name == "default" and len(rows) == 1 and sum(1 for cell in rows[0] if cell) >= 4:
                # A ruled one-row table is the last record of a table that continues from the previous page.
                normalized.append(rows)

        if normalized:
            return normalized, strategy_name

    return [], "none"


def _flatten_table_rows(table_rows: list[list[list[str]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for table_index, rows in enumerate(table_rows):
        for row in rows:
            output.append({"cells": row, "table_index": table_index})
    return output


def _image_cover(page: Any) -> float:
    """Fraction of the page area covered by images (0 when the page cannot report images)."""
    try:
        area = abs(page.rect)
        covered = sum(abs(pymupdf.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    except Exception:
        return 0.0
    return min(covered / area, 1.0) if area else 0.0


def _garbled_ratio(text: str) -> float:
    if not text:
        return 0.0
    return (text.count("�") + text.count("(cid:")) / len(text)


def _ocr_reason(raw_text: str, table_rows: list[list[list[str]]], page: Any) -> str | None:
    """Decide whether a page's content is only available through OCR, and why."""
    if not raw_text and not table_rows:
        return "no_text_layer"
    if _garbled_ratio(raw_text) > GARBLED_TEXT_RATIO:
        return "garbled_text_layer"
    if not table_rows and len(raw_text) < SPARSE_TEXT_CHARS and _image_cover(page) >= IMAGE_COVER_FOR_OCR:
        return "image_page_with_sparse_text"
    return None


def _extract_page(
    page: Any,
    plumber_page: Any,
    page_num: int,
    s3_key: str,
    ocr_layout: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[list[list[str]]], str]:
    """Extract one page. `ocr_layout` is the table column layout OCR found on an earlier page, for
    scanned continuation pages that repeat no header row."""
    raw_text = _page_text(page)
    table_rows: list[list[list[str]]] = []
    table_strategy = "none"
    if plumber_page is not None:
        try:
            table_rows, table_strategy = _extract_table_rows_from_page(plumber_page)
        except Exception as exc:
            print(f"WARN table extraction failed: {s3_key} page {page_num}: {exc}", file=sys.stderr)
            table_rows, table_strategy = [], "none"

    page_out: dict[str, Any] = {
        "page": page_num,
        "type": "text" if raw_text or table_rows else "empty",
        "method": "pdfplumber" if table_rows else "pymupdf",
        "text": raw_text,
    }
    reason = _ocr_reason(raw_text, table_rows, page)
    if reason:
        if not page_ocr.ocr_available():
            print(f"WARN OCR unavailable; {reason} page left as-is: {s3_key} page {page_num}", file=sys.stderr)
            page_out["ocr_error"] = "ocr_unavailable"
        else:
            try:
                result = page_ocr.ocr_page(page, layout=ocr_layout)
            except Exception as exc:
                print(f"WARN OCR failed: {s3_key} page {page_num}: {exc}", file=sys.stderr)
                page_out["ocr_error"] = f"{type(exc).__name__}: {exc}"
            else:
                if result["text"]:
                    if raw_text:
                        page_out["text_layer"] = raw_text
                    page_out.update({"type": "image", "method": "rapidocr", "text": result["text"]})
                    page_out["ocr"] = {
                        "reason": reason,
                        "rotation": result["rotation"],
                        "mean_score": result["mean_score"],
                        "lines": result["lines"],
                        "layout": result.get("layout"),
                    }
                    if not table_rows and result["table"]:
                        table_rows, table_strategy = [result["table"]], result.get("table_method", "ocr_grid")
                elif not raw_text and not table_rows:
                    page_out["type"] = "empty"

    page_out.update({
        "tables": _flatten_table_rows(table_rows),
        "table_count": len(table_rows),
        "table_strategy": table_strategy,
    })
    return page_out, table_rows, table_strategy


def _extract_document_from_bytes(
    pdf_bytes: bytes,
    s3_key: str,
    prefix: str,
    profiler_page_profile: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract every page; raises when the document cannot be opened or no page could be read."""
    source_name = _source_name_from_key(s3_key, prefix)
    relative = s3_key.removeprefix(prefix).lstrip("/")
    file_name = PurePosixPath(relative).name or "document.pdf"
    doc_id = f"{source_name}/{file_name}"

    pages_out: list[dict[str, Any]] = []
    tables_out: list[dict[str, Any]] = []
    counts = {"text": 0, "table": 0, "ocr": 0, "empty": 0, "failed": 0, "ocr_failed": 0}
    tables_by_strategy = {"default": 0, "text": 0, "mixed_v_text": 0, "mixed_h_text": 0, "none": 0}
    table_strategies_used = {"default": 0, "text": 0, "mixed_v": 0, "mixed_h": 0, "none": 0}
    profiler_has_table_by_page = {
        int(page.get("page") or 1): bool(page.get("has_table", False))
        for page in (profiler_page_profile or [])
        if isinstance(page, dict)
    }
    pages_with_zero_tables: list[int] = []

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    plumber_doc = None
    try:
        if doc.needs_pass:
            raise ValueError("encrypted PDF")
        title = (doc.metadata or {}).get("title") or file_name
        try:
            plumber_doc = pdfplumber.open(BytesIO(pdf_bytes))
        except Exception as exc:
            print(f"WARN pdfplumber open failed: {s3_key}: {exc}", file=sys.stderr)

        ocr_layout = None
        for page_index in range(len(doc)):
            page_num = page_index + 1
            plumber_page = (
                plumber_doc.pages[page_index]
                if plumber_doc is not None and page_index < len(plumber_doc.pages)
                else None
            )
            try:
                page_out, table_rows, table_strategy = _extract_page(
                    doc[page_index], plumber_page, page_num, s3_key, ocr_layout=ocr_layout
                )
                ocr_layout = (page_out.get("ocr") or {}).get("layout") or ocr_layout
            except Exception as exc:
                print(f"WARN page extraction failed: {s3_key} page {page_num}: {exc}", file=sys.stderr)
                counts["failed"] += 1
                pages_out.append({
                    "page": page_num, "type": "failed", "method": "failed", "text": "", "tables": [],
                    "table_count": 0, "table_strategy": "none", "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            strategy_key = {"mixed_v_text": "mixed_v", "mixed_h_text": "mixed_h"}.get(table_strategy, table_strategy)
            table_strategies_used[strategy_key] = table_strategies_used.get(strategy_key, 0) + 1
            if table_rows:
                counts["table"] += 1
                tables_by_strategy[table_strategy] = tables_by_strategy.get(table_strategy, 0) + 1
                tables_out.append({"page": page_num, "cells": page_out["tables"]})
            else:
                pages_with_zero_tables.append(page_num)
            if profiler_has_table_by_page.get(page_num, False) and not table_rows:
                print(f"WARN profiler/extractor mismatch: {s3_key} page {page_num}", file=sys.stderr)

            if page_out["method"] == "rapidocr":
                counts["ocr"] += 1
            elif page_out["type"] == "empty":
                counts["empty"] += 1
            elif page_out["text"]:
                counts["text"] += 1
            if "ocr_error" in page_out:
                counts["ocr_failed"] += 1
            pages_out.append(page_out)
    finally:
        doc.close()
        if plumber_doc is not None:
            plumber_doc.close()

    if pages_out and counts["failed"] == len(pages_out):
        raise RuntimeError(f"every page failed to extract ({len(pages_out)} pages)")

    return {
        "doc_id": doc_id,
        "source_name": source_name,
        "s3_object_key": s3_key,
        "pdf_title": title,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages_out,
        "tables": tables_out,
        "extraction_meta": {
            "text_pages": counts["text"],
            "table_pages": counts["table"],
            "ocr_pages": counts["ocr"],
            "ocr_failed_pages": counts["ocr_failed"],
            "empty_pages": counts["empty"],
            "failed_pages": counts["failed"],
            "total_pages": max(len(pages_out), 1),
            "extractor_version": "v2",
            "method": "pymupdf+pdfplumber+rapidocr-en",
            "tables_by_strategy": tables_by_strategy,
            "table_strategies_used": table_strategies_used,
            "pages_with_zero_tables": pages_with_zero_tables,
            "pdfplumber_available": plumber_doc is not None,
        },
    }


def collect_s3_pdfs(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.strip("/")):
        for item in page.get("Contents", []):
            key = item["Key"]
            if PurePosixPath(key).suffix.lower() == ".pdf":
                keys.append(key)
    return sorted(keys, key=str.casefold)


def collect_manifest_pdfs(
    s3_client: Any,
    bucket: str,
    manifest_s3_key: str,
    expected_run_id: str | None = None,
) -> list[str]:
    manifest = read_manifest(s3_client, bucket, manifest_s3_key)
    manifest_run_id = manifest.get("run_id")
    if expected_run_id and manifest_run_id and manifest_run_id != expected_run_id:
        raise ValueError(
            f"Manifest run_id {manifest_run_id!r} does not match --run-id {expected_run_id!r}"
        )
    if not expected_run_id and manifest_run_id:
        expected_run_id = str(manifest_run_id)
    if not isinstance(manifest.get("documents"), list):
        raise ValueError("Manifest must contain a documents array")

    keys = []
    for document in manifest["documents"]:
        if not isinstance(document, dict):
            continue
        key = document.get("s3_key")
        if not isinstance(key, str) or not key.strip():
            continue
        kind = str(document.get("kind") or "").casefold()
        is_pdf = kind == "pdf" if kind else PurePosixPath(key).suffix.casefold() == ".pdf"
        if is_pdf:
            keys.append(key)
    return list(dict.fromkeys(keys))


def _strip_source_root_segment(relative: str) -> str:
    cleaned = relative.strip("/")
    if not cleaned:
        return ""
    if cleaned == "source_files":
        return ""
    if cleaned.startswith("source_files/"):
        return cleaned[len("source_files/") :]
    return cleaned


def _safe_title_filename(value: str | None, fallback: str = "document") -> str:
    candidate = str(value or fallback).strip()
    candidate = re.sub(r"[^\w\s.\-]", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")
    candidate = re.sub(r"\s+", "_", candidate)
    candidate = candidate[:120] or fallback
    return candidate


def _normalized_output_key(s3_key: str, prefix: str, output_prefix: str, title: str | None = None) -> str:
    relative = _strip_source_root_segment(s3_key.removeprefix(prefix).lstrip("/"))
    folder_prefix = ""
    if relative and "/" in relative:
        folder, remainder = relative.split("/", 1)
        if folder in {"alerts", "fdc", "ipc", "banned", "banned_drugs", "nsq"}:
            folder_prefix = f"{folder}/"
            relative = remainder
    if title:
        filename = _safe_title_filename(title, fallback=PurePosixPath(relative).stem if relative else "document")
        output_name = f"{folder_prefix}{filename}.json"
    else:
        if not relative:
            relative = PurePosixPath(s3_key).name
        output_name = f"{folder_prefix}{PurePosixPath(relative).with_suffix('.json').name}"
    return f"{output_prefix.rstrip('/')}/{output_name}"


def write_json_to_s3(s3_client: Any, bucket: str, s3_key: str, prefix: str, output_prefix: str, payload: dict[str, Any]) -> str:
    # Named after the source PDF, which is unique; titles repeat (e.g. monthly alerts) and overwrote each other.
    output_key = _normalized_output_key(s3_key, prefix, output_prefix)
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    s3_client.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=body,
        ContentType="application/json",
    )
    return output_key


def _maybe_write_local_copy(output_path: Path | None, payload: dict[str, Any], name_hint: str) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_path = output_path / f"{name_hint}.json"
    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract text/tables from PDFs in S3, with RapidOCR fallback for scanned pages.")
    parser.add_argument("--bucket", default=DEFAULT_S3_INPUT_BUCKET, help="S3 input bucket for PDFs")
    parser.add_argument("--prefix", default=DEFAULT_S3_INPUT_PREFIX, help="S3 prefix to look under for PDFs")
    parser.add_argument("--region", default=DEFAULT_AWS_REGION, help="AWS region")
    parser.add_argument("--s3-output-bucket", default=DEFAULT_S3_OUTPUT_BUCKET, help="Bucket for extracted JSON output")
    parser.add_argument("--s3-output-prefix", default=DEFAULT_S3_OUTPUT_PREFIX, help="Base S3 prefix for extracted JSON output")
    parser.add_argument("--output", type=Path, default=None, help="Optional local folder to mirror the extracted JSON output")
    parser.add_argument("--doc-id", help="Process only this exact S3 PDF key")
    parser.add_argument("--run-id", help="Run identifier for the S3 manifest")
    parser.add_argument("--manifest-s3-key", help="S3 key for the pipeline manifest JSON")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on the number of PDFs to process")
    args = parser.parse_args(argv)
    started_at = utc_now_iso()

    if not args.bucket:
        parser.error("--bucket is required; set AWS_S3_BUCKET_NAME or AWS_S3_INPUT_BUCKET")
    if not args.s3_output_bucket:
        parser.error("--s3-output-bucket is required")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    prefix = args.prefix.strip("/")
    s3_client = boto3.client("s3", region_name=args.region)
    if args.manifest_s3_key:
        keys = collect_manifest_pdfs(
            s3_client,
            args.bucket,
            args.manifest_s3_key,
            expected_run_id=args.run_id,
        )
        if not args.run_id:
            manifest = read_manifest(s3_client, args.bucket, args.manifest_s3_key)
            args.run_id = str(manifest.get("run_id") or "") or None
    else:
        keys = collect_s3_pdfs(s3_client, args.bucket, prefix)
    if args.doc_id:
        keys = [key for key in keys if key == args.doc_id]
    if args.limit:
        keys = keys[:args.limit]
    if args.doc_id and not keys:
        print(f"No matching S3 PDF: {args.doc_id}", file=sys.stderr)
        return 1

    scraper_metadata_by_key = get_document_metadata(keys)

    extracted_keys: list[str] = []
    output_keys: list[str] = []
    errors: list[str] = []
    failed = 0
    for index, s3_key in enumerate(keys, start=1):
        try:
            response = s3_client.get_object(Bucket=args.bucket, Key=s3_key)
            pdf_bytes = response["Body"].read()
            payload = _extract_document_from_bytes(pdf_bytes, s3_key, prefix)
            scraper_metadata = scraper_metadata_by_key.get(s3_key)
            if scraper_metadata:
                payload["pdf_embedded_title"] = payload.get("pdf_title") or ""
                payload["pdf_title"] = scraper_metadata.get("title") or payload.get("pdf_title") or ""
                payload["source_name"] = scraper_metadata.get("source") or payload.get("source_name")
                payload["source_category"] = SOURCE_CATEGORY_BY_SOURCE.get(
                    scraper_metadata.get("source"), payload.get("source_name", "unknown")
                )
                payload["scraper_metadata"] = scraper_metadata
            output_key = write_json_to_s3(
                s3_client,
                args.s3_output_bucket,
                s3_key,
                prefix,
                args.s3_output_prefix,
                payload,
            )
            extracted_keys.append(s3_key)
            output_keys.append(output_key)
            if args.output is not None:
                _maybe_write_local_copy(args.output, payload, PurePosixPath(s3_key).stem)
            print(f"Extracted {index}/{len(keys)}: {s3_key} -> s3://{args.s3_output_bucket}/{output_key}")
        except Exception as exc:
            failed += 1
            errors.append(f"{s3_key}: {exc}")
            print(f"ERROR extracting {s3_key}: {exc}", file=sys.stderr)

    update_extracted_documents(extracted_keys)
    if args.run_id and args.bucket:
        write_result(
            s3_client,
            args.bucket,
            args.run_id,
            "extractor",
            {
                "schema_version": 1,
                "stage": "extractor",
                "run_id": args.run_id,
                "started_at": started_at,
                "finished_at": utc_now_iso(),
                "status": "failure" if failed else "success",
                "input_keys": keys,
                "output_keys": output_keys,
                "error": "; ".join(errors) or None,
            },
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
