"""Create per-document structured JSON from extracted PDF tables."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import boto3

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_processing_service.shared.config import (
    AWS_REGION,
    S3_INPUT_BUCKET,
    S3_OUTPUT_BUCKET,
)
from data_processing_service.shared.database import (
    get_document_metadata,
    update_parsed_documents,
)
from data_processing_service.shared.manifest import read_manifest, result_key, utc_now_iso, write_result
from data_processing_service.parser import narrative
from data_processing_service.parser.tables import (
    BATCH_COLUMN,
    COMBINED_COLUMN,
    MANUFACTURER_COLUMN,
    PRODUCT_COLUMN,
    records_from_tables,
)

DEFAULT_S3_INPUT_BUCKET = S3_INPUT_BUCKET
DEFAULT_S3_INPUT_PREFIX = "medicine-data-storage/processed_files/extracted_json"
DEFAULT_CLASSIFIER_CSV_KEY = "medicine-data-storage/processed_files/classifier_output/classification_summary.csv"
DEFAULT_S3_OUTPUT_BUCKET = S3_OUTPUT_BUCKET or S3_INPUT_BUCKET
DEFAULT_S3_OUTPUT_PREFIX = "medicine-data-storage/processed_files/parsed_json"
DEFAULT_AWS_REGION = AWS_REGION
SOURCE_CATEGORY_BY_SOURCE = {
    "cdsco_alerts": "alerts",
    "cdsco_banned_drugs": "banned_drugs",
    "cdsco_fdc": "fdc",
    "ipc_pvpi": "ipc",
}


DOCUMENT_TYPES = {
    "Doc 1": ("Doc 1: Banned Drugs", "Banned Drugs"),
    "Doc 2": ("Doc 2: List of Drugs Safety Alerts issued by PvPI", "Pharmacovigilance"),
    "Doc 3": ("Doc 3: NSQ drugs (State Lab format)", "Quality Failures"),
    "Doc 4": ("Doc 4: Spurious Drugs", "Quality Failures"),
    "Doc 5": ("Doc 5: CDSCO Drug Alerts (CDSCO Laboratory format)", "Quality Failures"),
    "Doc 6": ("Doc 6: Legacy CDSCO Monthly Drug Alert (2013-2018 Format)", "Quality Failures"),
    "Doc 7": ("Doc 7: Medical Device & In-Vitro Diagnostic (IVD) Safety Alerts", "Device Alerts"),
    "Doc 8": ("Doc 8: Approved New Drugs & Marketing Authorizations", "Approvals & NOCs"),
    "Doc 9": ("Doc 9: Fixed Dose Combination (FDC) Evaluation & Committee Status List", "Banned Drugs"),
    "Doc 10": ("Doc 10: Subject Expert Committee (SEC) & NDAC Meeting Schedules", "Administrative"),
    "Doc 11": ("Doc 11: NOC, Import Permissions & Medical Device Registration Tracking", "Approvals & NOCs"),
    "Doc 12": ("Doc 12: Vaccine Manufacturing Facility Inspection Status", "Approvals & NOCs"),
    "Doc 13": ("Doc 13: Approved Diagnostic / PCR Testing Kits List", "Approvals & NOCs"),
    "Doc 14": ("Doc 14: Performance Evaluation Laboratories for IVD Analyzers & Software", "Administrative"),
    "Doc 15": ("Doc 15: Regulatory Fee Schedule & Document Checklist for New Applications", "Administrative"),
    "Doc 16": ("Doc 16: Gazette Notification Drug Prohibition Extraordinaries", "Banned Drugs"),
    "Doc 17": ("Doc 17: Drug Recall, Theft & Falsified Product Alerts", "Quality Failures"),
}
GENERAL_DOCUMENT = ("General Regulatory Document", "Administrative")


def _scraper_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("scraper_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _source_category(payload: dict[str, Any]) -> str:
    metadata = _scraper_metadata(payload)
    source = str(metadata.get("source") or payload.get("source_name") or "")
    return str(
        payload.get("source_category")
        or SOURCE_CATEGORY_BY_SOURCE.get(source)
        or payload.get("source_name")
        or payload.get("source_category")
        or "unknown"
    )


def _document_title(payload: dict[str, Any], fallback: str) -> str:
    metadata = _scraper_metadata(payload)
    return str(
        metadata.get("title")
        or payload.get("pdf_title")
        or payload.get("document_title")
        or payload.get("title")
        or fallback
    )


def _apply_scraper_metadata(
    parsed: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    metadata = _scraper_metadata(payload)
    if not metadata:
        return parsed

    parsed["title"] = _document_title(payload, str(parsed.get("title") or "document"))
    parsed["source_category"] = _source_category(payload)
    parsed["scraper_metadata"] = metadata
    for source_field in ("source", "source_key", "release_date"):
        if metadata.get(source_field) is not None:
            parsed[source_field] = metadata[source_field]
    if metadata.get("document_type"):
        parsed["scraper_document_type"] = metadata["document_type"]
    return parsed


def _clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def _rows_from_table(table: dict[str, Any]) -> list[list[Any]]:
    raw_rows = table.get("rows") or table.get("cells") or []
    if not isinstance(raw_rows, list):
        return []

    rows: list[list[Any]] = []
    for raw_row in raw_rows:
        if isinstance(raw_row, dict):
            if isinstance(raw_row.get("cells"), list):
                rows.append(raw_row["cells"])
            else:
                rows.append([cell.get("value", "") if isinstance(cell, dict) else cell for cell in raw_row.values()])
        elif isinstance(raw_row, list):
            rows.append(raw_row)
    return rows


def _table_blocks(payload: dict[str, Any]) -> list[tuple[int, list[list[Any]]]]:
    """Every extracted table as (page, rows), keeping separate tables on one page apart."""
    tables = payload.get("tables") or [
        {"page": page.get("page"), "cells": page.get("tables") or []}
        for page in payload.get("pages") or []
        if isinstance(page, dict) and page.get("tables")
    ]
    blocks: list[tuple[int, list[list[Any]]]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        grouped: dict[int, list[list[Any]]] = {}
        for row in table.get("cells") or table.get("rows") or []:
            if isinstance(row, dict) and isinstance(row.get("cells"), list):
                grouped.setdefault(int(row.get("table_index") or 0), []).append(row["cells"])
            elif isinstance(row, list):
                grouped.setdefault(0, []).append(row)
        blocks.extend((int(table.get("page") or 1), rows) for _, rows in sorted(grouped.items()))
    return blocks


def _parse_pvpi_alert(payload: dict[str, Any]) -> dict[str, Any] | None:
    pages = [page for page in payload.get("pages") or [] if isinstance(page, dict)]
    page_text = "\n".join(str(page.get("text") or "") for page in pages)
    table_rows = [
        (table.get("page", 1), row)
        for table in payload.get("tables") or []
        if isinstance(table, dict)
        for row in _rows_from_table(table)
    ]
    content = (page_text + " " + " ".join(_clean_cell(cell) for _, row in table_rows for cell in row)).casefold()
    has_pvpi_alert_signals = (
        "pvpi" in content
        or "drug safety alerts" in content
        or ("suspected drugs" in content and "adverse drug reactions" in content)
    )
    if not has_pvpi_alert_signals:
        return None

    headers = ["S No", "Suspected Drugs", "Indication(s)", "Adverse Drug Reactions"]
    records: list[dict[str, str]] = []
    current_record: dict[str, str] | None = None
    table_pages: set[int] = set()
    header_found = False

    for page_number, row in table_rows:
        cells = [_clean_cell(cell) for cell in row]
        row_text = " ".join(cells).casefold()
        if "suspected drug" in row_text and "adverse drug" in row_text:
            header_found = True
            table_pages.add(int(page_number or 1))
            continue
        if not header_found:
            continue
        if row_text.startswith("healthcare professional") or row_text.startswith("disclaimer"):
            header_found = False
            continue

        table_pages.add(int(page_number or 1))
        if cells and re.fullmatch(r"\d+\.?", cells[0]):
            record = {header: "" for header in headers}
            record["S No"] = cells[0].rstrip(".")
            for index, value in enumerate(cells[1:4], start=1):
                if value:
                    record[headers[index]] = value
            records.append(record)
            current_record = record
        elif current_record is not None:
            for index, value in enumerate(cells[1:4], start=1):
                if value:
                    current_record[headers[index]] = " ".join(
                        part for part in (current_record[headers[index]], value) if part
                    )

    issue_date_match = re.search(
        r"\bDated\s*:?\s*([^\n\r]+)", page_text, re.IGNORECASE
    )
    issue_date = _clean_cell(issue_date_match.group(1)) if issue_date_match else ""
    file_number_match = re.search(
        r"\bFile\s*No\.?\s*:?\s*(.*?)(?=\s+\bDated\b|[\n\r]|$)",
        page_text,
        re.IGNORECASE,
    )
    file_number = _clean_cell(file_number_match.group(1)) if file_number_match else ""

    if not records:
        section_match = re.search(
            r"(?:S\.?\s*No\.?\s+)?Suspected\s+Drugs.*?Adverse\s+Drug\s+Reactions\s*(.*?)(?=Healthcare\s+Professionals|$)",
            page_text,
            re.IGNORECASE | re.DOTALL,
        )
        section = section_match.group(1) if section_match else ""
        entries = list(re.finditer(r"(?m)^\s*(\d+)\s+(.+?)(?=^\s*\d+\s+|\Z)", section, re.DOTALL))
        indication_start = re.compile(
            r"\b(?:chemotherapy|in\s+combination\s+with|for\s+the\s+treatment\s+of|treatment\s+of|used\s+for|indicated\s+for)\b",
            re.IGNORECASE,
        )
        for entry in entries:
            body = _clean_cell(entry.group(2))
            marker = indication_start.search(body)
            if not marker:
                continue
            drug_name = body[:marker.start()].strip(" .:-")
            indication_and_reaction = body[marker.start():]
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", indication_and_reaction, maxsplit=1)
            indication = sentences[0].strip() if sentences else indication_and_reaction
            reaction = sentences[1].strip() if len(sentences) > 1 else ""
            records.append({
                "S No": entry.group(1),
                "Suspected Drugs": drug_name,
                "Indication(s)": indication,
                "Adverse Drug Reactions": reaction,
            })

    if not records:
        return None

    source_key = str(payload.get("s3_object_key") or payload.get("source_file") or "")
    filename = PurePosixPath(source_key).name if source_key else str(payload.get("doc_id") or "document.pdf")
    title = _document_title(payload, filename)
    alert_rows = [
        {
            "s_no": int(record["S No"]) if record["S No"].isdigit() else record["S No"],
            "issue_date": issue_date,
            "suspected_drug": record["Suspected Drugs"],
            "indications": record["Indication(s)"],
            "adverse_reactions": [record["Adverse Drug Reactions"]] if record["Adverse Drug Reactions"] else [],
        }
        for record in records
    ]
    return _apply_scraper_metadata({
        "document_id": str(payload.get("doc_id") or payload.get("document_id") or "doc_unknown"),
        "source_file": source_key or filename,
        "pdf_path": source_key or filename,
        "source_category": _source_category(payload),
        "document_type": "Doc 2: List of Drugs Safety Alerts issued by PvPI",
        "group_type": "Pharmacovigilance",
        "title": title,
        "pages": sorted(table_pages or {int(page.get("page") or 1) for page in pages}),
        "document_metadata": {
            "alert_type": "Adverse Drug Reaction (ADR) Alert",
            "issuing_authority": "Indian Pharmacopoeia Commission, Ministry of Health & Family Welfare, Government of India",
            "file_number": file_number,
            "date_of_issue": issue_date,
        },
        "total_rows": len(records),
        "exact_columns": headers,
        "adr_alerts": alert_rows,
        "records": records,
    }, payload)


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _classify_document(title: str, columns: list[str], text: str) -> tuple[str, str]:
    """Document type from the scraper title first, then table columns, then body text (whole words only)."""
    # Gazette titles join words with "_" ("4595(E)_Prohibition"); "_" is a word character, so \b would fail.
    title_text = title.lower().replace("_", " ")
    body = text[:6000].lower()
    if _matches(r"\bspurious\b", title_text) and not _matches(r"\bnsq\b|not of standard", title_text):
        return DOCUMENT_TYPES["Doc 4"]
    if _matches(r"\bmedical\s+devices?\b.*\balert|\bdevice\s+alert", title_text):
        return DOCUMENT_TYPES["Doc 7"]
    if _matches(r"\b(?:recall|theft|stolen|falsified|counterfeit)\b", title_text):
        return DOCUMENT_TYPES["Doc 17"]
    prohibition = _matches(r"\b(?:prohibit\w*|banned|section\s*26\s*a)\b", title_text) or (
        _matches(r"\bprohibit\w*\b", body) and _matches(r"\bsection\s*26\s*a\b", body)
    )
    if prohibition:
        if _matches(r"\b(?:s\.?\s*o\.?|g\.?\s*s\.?\s*r\.?)\s*\d+", title_text) and PRODUCT_COLUMN not in columns:
            return DOCUMENT_TYPES["Doc 16"]
        return DOCUMENT_TYPES["Doc 1"]
    quality_alert = _matches(r"\bnsq\b|not of standard|standard quality|\bdrugs?\s+alerts?\b", title_text) or (
        BATCH_COLUMN in columns and "Reason for failure" in columns
    )
    if quality_alert:
        if COMBINED_COLUMN + " (source)" in columns:
            return DOCUMENT_TYPES["Doc 6"]
        if _matches(r"\bstate\b", title_text) or _matches(r"\b(?:reported by|from)\s+state\b|\bstate\s+lab", " ".join(columns) + " " + body):
            return DOCUMENT_TYPES["Doc 3"]
        return DOCUMENT_TYPES["Doc 5"]
    if _matches(r"\bapproved\b", title_text) and _matches(r"\bindications?\b", body):
        return DOCUMENT_TYPES["Doc 8"]
    if _matches(r"\bfdcs?\b|fixed dose combination", title_text) and _matches(r"\bcommittee\b|\bevaluation\b|\bstatus\b", title_text):
        return DOCUMENT_TYPES["Doc 9"]
    if _matches(r"\bsec\b|subject expert committee|\bndac\b|tentative schedule", title_text):
        return DOCUMENT_TYPES["Doc 10"]
    if _matches(r"\bnoc\b|import\s+(?:permission|licen[cs]e)|registration certificate", title_text):
        return DOCUMENT_TYPES["Doc 11"]
    if _matches(r"\bvaccine\b", title_text) and _matches(r"\binspection\b", title_text):
        return DOCUMENT_TYPES["Doc 12"]
    if _matches(r"\bpcr\b|testing kits?\b", title_text):
        return DOCUMENT_TYPES["Doc 13"]
    if _matches(r"\bivd\b", title_text) and _matches(r"\blaborator(?:y|ies)\b", title_text):
        return DOCUMENT_TYPES["Doc 14"]
    if _matches(r"\bfees?\b|\bfaqs?\b|checklist", title_text):
        return DOCUMENT_TYPES["Doc 15"]
    return GENERAL_DOCUMENT


def _record_columns(records: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for record in records:
        for key in record:
            if key not in columns and key != "page_number":
                columns.append(key)
    return columns


def _process_single_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    document_id = str(payload.get("doc_id") or payload.get("document_id") or "doc_unknown")
    source_category = _source_category(payload)
    title = _document_title(payload, document_id)
    source_key = str(payload.get("s3_object_key") or payload.get("source_file") or f"{document_id}.pdf")

    pvpi_result = _parse_pvpi_alert(payload)
    if pvpi_result is not None:
        pvpi_result["parse_method"] = "pvpi_table"
        return pvpi_result

    pages = [page for page in payload.get("pages") or [] if isinstance(page, dict)]
    text = "\n".join(str(page.get("text") or "") for page in pages)
    dropped: list[dict[str, Any]] = []
    records, columns = records_from_tables(_table_blocks(payload), dropped=dropped)
    if dropped:
        print(f"WARN {len(dropped)} table row(s) could not be placed in {source_key}", file=sys.stderr)
    doc_type, group_type = _classify_document(title, columns, text)
    method = "table" if records else "none"

    has_products = any(PRODUCT_COLUMN in record for record in records)
    if (doc_type, group_type) in (DOCUMENT_TYPES["Doc 1"], DOCUMENT_TYPES["Doc 16"]) and not has_products:
        listed = narrative.parse_notification(text)
        if listed:
            records, method = listed, "notification_list"
    if records and not has_products and any(BATCH_COLUMN in record for record in records):
        # Batch tables in recall letters often omit the product; it is named in the letter's subject.
        subject = narrative.subject_product(text, title)
        if subject:
            for record in records:
                record.setdefault(PRODUCT_COLUMN, subject[0])
                if subject[1]:
                    record.setdefault(MANUFACTURER_COLUMN, subject[1])
    if not records:
        # Any document whose tables give nothing may still be an alert written as prose
        # (e.g. an NSQ letter naming its batches in the subject line).
        records, method = narrative.parse_alert(text, title), "alert_prose"
    if not records:
        records, method = narrative.parse_notice(text, title), "notice"
    if not records:
        method = "none"

    structured_json = {
        "document_id": document_id,
        "source_file": source_key,
        "pdf_path": source_key,
        "source_category": source_category,
        "document_type": doc_type,
        "group_type": group_type,
        "title": title,
        "pages": sorted({int(record.get("page_number") or 0) for record in records} - {0}) or sorted(
            int(page.get("page") or 1) for page in pages
        ),
        "parse_method": method,
        "total_rows": len(records),
        "dropped_rows": dropped if method == "table" else [],
        "exact_columns": _record_columns(records),
        "records": records,
    }
    return _apply_scraper_metadata(structured_json, payload)


def _iter_s3_objects(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.strip("/")):
        for item in page.get("Contents", []):
            key = item["Key"]
            if PurePosixPath(key).suffix.lower() == ".json":
                keys.append(key)
    return sorted(keys, key=str.casefold)


def _read_documents_to_parse(s3_client: Any, bucket: str, key: str) -> dict[str, dict[str, Any]]:
    """Classifier decisions for every document that should be parsed, keyed by source PDF key.

    Event-bearing documents are parsed, and so are documents the classifier flagged for review: nothing
    downstream reads the review flag, so skipping them silently discarded documents such as prohibition
    notices. Their records carry the flag through to the run approval step instead.
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    required_columns = {"bucket", "s3_object_key"}
    if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
        raise ValueError(
            "Classifier CSV must contain 'bucket' and 's3_object_key' columns"
        )
    decisions: dict[str, dict[str, Any]] = {}
    for row in reader:
        source_key = (row.get("s3_object_key") or "").strip()
        bucket_name = (row.get("bucket") or "").strip().casefold()
        needs_review = (row.get("needs_review") or "").strip().casefold() == "true"
        if not source_key or not (bucket_name == "event-bearing" or needs_review):
            continue
        try:
            reasons = json.loads(row.get("needs_review_reasons") or "[]")
        except json.JSONDecodeError:
            reasons = [row["needs_review_reasons"]]
        decisions[source_key] = {"bucket": bucket_name, "needs_review": needs_review, "reasons": reasons}
    return decisions


def _manifest_has_pdfs(manifest: dict[str, Any]) -> bool:
    if "has_pdfs" in manifest:
        return bool(manifest["has_pdfs"])
    return any(
        isinstance(document, dict)
        and (document.get("kind") == "pdf" or str(document.get("s3_key") or "").casefold().endswith(".pdf"))
        for document in manifest.get("documents") or []
    )


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


def _output_key_for_document(s3_key: str, input_prefix: str, output_prefix: str, title: str | None = None) -> str:
    relative = s3_key.removeprefix(input_prefix.strip("/")).lstrip("/") if input_prefix else s3_key
    relative = _strip_source_root_segment(relative)
    parts = [part for part in PurePosixPath(relative).parts if part not in {"", "."}]
    category_names = {"alerts", "fdc", "ipc", "banned", "banned_drugs", "nsq"}
    known_roots = {
        "medicine-data-storage",
        "processed_files",
        "runs",
        "classifier_output",
        "per_doc",
        "source_files",
        "extracted_json",
        "parsed_json",
        "normalized",
    }
    while len(parts) > 1 and (parts[0] in known_roots or parts[0] not in category_names):
        parts = parts[1:]
    relative = "/".join(parts)
    if title:
        relative_path = PurePosixPath(relative) if relative else PurePosixPath()
        parent_dir = relative_path.parent.as_posix() if relative_path.parent != PurePosixPath(".") else ""
        filename = _safe_title_filename(title, fallback=relative_path.stem if relative else "document")
        output_name = f"{parent_dir}/{filename}.json" if parent_dir else f"{filename}.json"
    else:
        if not relative:
            relative = PurePosixPath(s3_key).name
        relative_path = PurePosixPath(relative)
        output_name = relative_path.as_posix()
        if not PurePosixPath(output_name).suffix:
            output_name = f"{output_name}.json"
    return f"{output_prefix.rstrip('/')}/{output_name}"


def _manifest_result_keys(s3_client: Any, bucket: str, run_id: str, stage: str) -> list[str]:
    result_s3_key = result_key(run_id, stage)
    response = s3_client.get_object(Bucket=bucket, Key=result_s3_key)
    payload = json.loads(response["Body"].read().decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{stage} result must be a JSON object")
    if payload.get("run_id") != run_id or payload.get("stage") != stage:
        raise ValueError(f"{stage} result does not belong to run {run_id!r}")
    output_keys = payload.get("output_keys")
    if not isinstance(output_keys, list):
        raise ValueError(f"{stage} result must contain an output_keys array")
    return [str(key) for key in output_keys if isinstance(key, str)]


def _manifest_input_prefix(keys: list[str], fallback: str) -> str:
    if not keys:
        return fallback.strip("/")
    normalized = [PurePosixPath(key) for key in keys]
    common_parts = list(normalized[0].parts)
    for candidate in normalized[1:]:
        index = 0
        while index < min(len(common_parts), len(candidate.parts)) and common_parts[index] == candidate.parts[index]:
            index += 1
        common_parts = common_parts[:index]
        if not common_parts:
            break
    common_path = PurePosixPath(*common_parts)
    if common_path.suffix:
        common_dir = common_path.parent
    else:
        common_dir = common_path
    dir_parts = list(common_dir.parts)
    if "per_doc" in dir_parts:
        return PurePosixPath(*dir_parts[: dir_parts.index("per_doc") + 1]).as_posix()
    if dir_parts and dir_parts[-1] in {"alerts", "fdc", "ipc", "banned", "banned_drugs", "nsq"}:
        return PurePosixPath(*dir_parts[:-1]).as_posix() if len(dir_parts) > 1 else fallback.strip("/")
    return common_dir.as_posix() if common_dir.as_posix() else fallback.strip("/")


def _read_json_from_s3(s3_client: Any, bucket: str, key: str) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read().decode("utf-8"))


def _write_json_to_s3(s3_client: Any, bucket: str, key: str, payload: dict[str, Any]) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert extracted PDF tables into exact structured JSON documents.")
    parser.add_argument("--bucket", default=DEFAULT_S3_INPUT_BUCKET, help="S3 bucket containing extracted JSON files")
    parser.add_argument("--prefix", default=DEFAULT_S3_INPUT_PREFIX, help="Prefix to scan for extracted JSON files")
    parser.add_argument("--classifier-csv-bucket", default=None, help="Bucket containing classifier_summary.csv; defaults to --bucket")
    parser.add_argument("--classifier-csv-key", default=DEFAULT_CLASSIFIER_CSV_KEY, help="S3 key for classification_summary.csv")
    parser.add_argument("--region", default=DEFAULT_AWS_REGION, help="AWS region")
    parser.add_argument("--s3-output-bucket", default=DEFAULT_S3_OUTPUT_BUCKET, help="Bucket for parsed JSON output")
    parser.add_argument("--s3-output-prefix", default=DEFAULT_S3_OUTPUT_PREFIX, help="Base prefix for parsed JSON output")
    parser.add_argument("--doc-id", help="Process only this exact extracted JSON S3 key")
    parser.add_argument("--run-id", help="Run identifier for the S3 manifest")
    parser.add_argument("--manifest-s3-key", help="S3 key for the pipeline manifest JSON")
    parser.add_argument("--limit", type=int, default=0, help="Optional file limit")
    args = parser.parse_args(argv)
    started_at = utc_now_iso()

    if not args.bucket:
        parser.error("--bucket is required")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    s3_client = boto3.client("s3", region_name=args.region)
    manifest_mode = bool(args.manifest_s3_key and args.run_id)
    if manifest_mode and not _manifest_has_pdfs(read_manifest(s3_client, args.bucket, args.manifest_s3_key)):
        # JSON-only runs skip the extractor and classifier; there is nothing for the parser to read.
        print("Manifest has no PDFs; nothing to parse.")
        write_result(s3_client, args.bucket, args.run_id, "parser", {
            "schema_version": 1, "stage": "parser", "run_id": args.run_id, "started_at": started_at,
            "finished_at": utc_now_iso(), "status": "success", "input_keys": [], "output_keys": [],
            "review_documents": [], "error": None,
        })
        return 0
    if manifest_mode:
        # Parse the extractor's page/table JSON; the classifier's per-document verdicts carry no content.
        keys = [
            key for key in _manifest_result_keys(s3_client, args.bucket, args.run_id, "extractor")
            if PurePosixPath(key).suffix.casefold() == ".json"
        ]
        classifier_output_keys = _manifest_result_keys(s3_client, args.bucket, args.run_id, "classifier")
        classifier_csv_keys = [
            key for key in classifier_output_keys
            if PurePosixPath(key).name.casefold() == "classification_summary.csv"
        ]
        if not classifier_csv_keys:
            parser.error("Classifier result does not include classification_summary.csv in output_keys")
        classifier_csv_key = classifier_csv_keys[0]
        input_prefix = _manifest_input_prefix(keys, args.prefix)
    else:
        keys = _iter_s3_objects(s3_client, args.bucket, args.prefix)
        input_prefix = args.prefix
        classifier_csv_key = args.classifier_csv_key
    if args.doc_id:
        keys = [key for key in keys if key == args.doc_id]
    if args.limit:
        keys = keys[:args.limit]
    classifier_bucket = args.classifier_csv_bucket or args.bucket
    try:
        documents_to_parse = _read_documents_to_parse(
            s3_client, classifier_bucket, classifier_csv_key
        )
    except Exception as exc:
        parser.error(
            f"Could not load classifier CSV from s3://{classifier_bucket}/"
            f"{classifier_csv_key}: {exc}"
        )
    if not keys and not manifest_mode:
        print(
            f"No JSON files found in s3://{args.bucket}/{args.prefix}. "
            "Point --prefix to the extractor JSON output, currently "
            "medicine-data-storage/processed_files/extracted_json.",
            file=sys.stderr,
        )
        return 1

    parsed_keys: list[str] = []
    review_documents: list[str] = []
    output_keys: list[str] = []
    errors: list[str] = []
    skipped_count = 0
    failed = 0
    batch_size = 100
    for offset in range(0, len(keys), batch_size):
        batch_keys = keys[offset:offset + batch_size]
        batch_payloads: list[tuple[str, dict[str, Any]]] = []
        for s3_key in batch_keys:
            try:
                payload = _read_json_from_s3(s3_client, args.bucket, s3_key)
                source_pdf_key = payload.get("s3_object_key") or payload.get("source_file")
                if not source_pdf_key or source_pdf_key not in documents_to_parse:
                    skipped_count += 1
                    print(f"Skipped (not event-bearing): {s3_key}")
                    continue
                batch_payloads.append((s3_key, payload))
            except Exception as exc:
                failed += 1
                errors.append(f"{s3_key}: {exc}")
                print(f"ERROR reading {s3_key}: {exc}", file=sys.stderr)

        metadata_keys = [
            str(payload.get("s3_object_key") or payload.get("source_file"))
            for _, payload in batch_payloads
            if (payload.get("s3_object_key") or payload.get("source_file"))
            and not _scraper_metadata(payload)
        ]
        metadata_by_key = get_document_metadata(metadata_keys)

        for index, (s3_key, payload) in enumerate(batch_payloads, start=offset + 1):
            try:
                source_pdf_key = payload.get("s3_object_key") or payload.get("source_file")
                if source_pdf_key and not _scraper_metadata(payload):
                    metadata = metadata_by_key.get(source_pdf_key)
                    if metadata:
                        payload["scraper_metadata"] = metadata
                structured = _process_single_payload(payload)
                decision = documents_to_parse.get(source_pdf_key) or {}
                if decision.get("needs_review"):
                    structured["classifier_review"] = {"bucket": decision["bucket"], "reasons": decision["reasons"]}
                    review_documents.append(source_pdf_key)
                # Named after the input file, which is unique; titles repeat across monthly documents.
                output_key = _output_key_for_document(s3_key, input_prefix, args.s3_output_prefix)
                _write_json_to_s3(s3_client, args.s3_output_bucket, output_key, structured)
                output_keys.append(output_key)
                parsed_keys.append(source_pdf_key or s3_key)
                print(f"Parsed {index}/{len(keys)}: {s3_key} -> s3://{args.s3_output_bucket}/{output_key}")
            except Exception as exc:
                failed += 1
                errors.append(f"{s3_key}: {exc}")
                print(f"ERROR parsing {s3_key}: {exc}", file=sys.stderr)

    update_parsed_documents(parsed_keys)
    print(
        f"Parsing complete: {len(parsed_keys)} documents parsed ({len(review_documents)} flagged for review); "
        f"{skipped_count} non-event-bearing documents skipped"
    )
    if args.run_id and args.bucket:
        write_result(
            s3_client,
            args.bucket,
            args.run_id,
            "parser",
            {
                "schema_version": 1,
                "stage": "parser",
                "run_id": args.run_id,
                "started_at": started_at,
                "finished_at": utc_now_iso(),
                "status": "failure" if failed else "success",
                "input_keys": keys,
                "output_keys": output_keys,
                "review_documents": review_documents,
                "error": "; ".join(errors) or None,
            },
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
