"""Create per-document structured JSON from extracted PDF tables."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
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


SPECIAL_FILE_IDS = [
    "3145", "3146", "3147", "3246", "3253", "11255", "2058", "4540", "7571",
    "7770", "7881", "banneddrugs", "514_Notice", "List-of-Drugs-Safety-Alerts",
]

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
}


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


def _sanitize_header_key(value: Any) -> str:
    cleaned = _clean_cell(value)
    cleaned = re.sub(r"[\.\s]+\b", " ", cleaned)
    cleaned = re.sub(r"[^a-zA-Z0-9\s/_\-&]", "", cleaned).strip()
    return cleaned if cleaned else "Column"


def _is_summary_table(rows: list[list[Any]]) -> bool:
    if not rows or len(rows) <= 6:
        table_text = " ".join(
            " ".join(_clean_cell(cell) for cell in row if _clean_cell(cell))
            for row in rows
        ).lower()
        return "total number of samples" in table_text or "samples declared" in table_text
    return False


def _is_noise_row(row: list[Any]) -> bool:
    row_str = " ".join(_clean_cell(cell) for cell in row if str(cell).strip()).lower()
    if not row_str:
        return True
    if re.search(r"^page\s+\d+\s+of\s+\d+", row_str) or re.search(r"^\d+\s+of\s+\d+", row_str):
        return True
    if (
        ("name of product" in row_str or "product/drug name" in row_str or "batch no" in row_str)
        and ("manufacturing date" in row_str or "expiry date" in row_str or "nsq result" in row_str)
    ):
        return True
    if "this report is issued" in row_str or "confidential" in row_str or "cdsco website" in row_str:
        return True
    return False


def _is_valid_anchor(first_cell: Any) -> bool:
    cell_str = _clean_cell(first_cell)
    return bool(re.match(r"^\d+[\.)]?$", cell_str))


def _find_real_header_row(rows: list[list[Any]]) -> tuple[int, list[str]]:
    for idx, row in enumerate(rows[:15]):
        non_empty = [_clean_cell(cell) for cell in row if _clean_cell(cell)]
        row_str = " ".join(non_empty).lower()
        if len(non_empty) >= 3 and any(
            kw in row_str
            for kw in [
                "s. no", "s no", "s.no", "sl no", "sr. no", "s n o",
                "s n", "name of drug", "product", "batch", "manufactured by",
                "reason for failure",
            ]
        ):
            return idx, [_sanitize_header_key(cell) for cell in row if _clean_cell(cell)]
    for idx, row in enumerate(rows[:5]):
        non_empty = [_clean_cell(cell) for cell in row if _clean_cell(cell)]
        if len(non_empty) >= 2:
            return idx, [_sanitize_header_key(cell) for cell in row if _clean_cell(cell)]
    first_row = rows[0] if rows else []
    return 0, [_sanitize_header_key(cell) for cell in first_row if _clean_cell(cell)]


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


def _run_exact_legacy_parser(
    payload: dict[str, Any],
    filename: str,
    source_category: str | None = None,
) -> dict[str, Any] | None:
    del filename, source_category
    return None


def _is_banned_drugs_payload(payload: dict[str, Any]) -> bool:
    source_key = str(payload.get("s3_object_key") or payload.get("source_file") or "").casefold()
    path_parts = {part for part in PurePosixPath(source_key).parts}
    if path_parts.intersection({"banned", "banned_drugs", "banned-drugs"}):
        return True

    page_text = " ".join(
        str(page.get("text") or "")
        for page in payload.get("pages") or []
        if isinstance(page, dict)
    ).casefold()
    if "section 26a" in page_text and "prohibited" in page_text and "drugs" in page_text:
        return True

    table_text = " ".join(
        _clean_cell(cell).casefold()
        for table in payload.get("tables") or []
        if isinstance(table, dict)
        for row in _rows_from_table(table)
        for cell in row
    )
    return "section 26a" in table_text and "prohibited" in table_text and "drugs" in table_text


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


def _normalize_alert_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    key_map = {
        "s_no": ["s no", "s.no", "s. no", "s n o", "sl no", "sr. no", "sl.no", "s n"],
        "product_name": ["name of drugs", "product/drug name", "name of product", "name of drug", "product name"],
        "batch_no": ["batch no", "batch no.", "b. no.", "b no", "batch number"],
        "mfg_date": ["date of manufacture", "date of manu factur e", "manufacturing date", "manufact uring date", "manufa cturing date", "mfg date"],
        "exp_date": ["date of expiry", "expiry date", "exp date"],
        "mfg_by": ["manufactured by", "manufactured by as per label"],
        "reason": ["reason for failure", "reasons for failure", "nsq result", "sub-standard in"],
        "drawn_by": ["drawn by", "drawn by from state/cdsco zone", "reporting source"],
        "from_lab": ["from", "from name of laboratory", "reported by cdsco laboratory", "reported by state laboratory"],
        "remarks": ["remarks", "remark", "response of original manufacturer"],
    }

    for record in records:
        standard = {
            "S No": "",
            "Name of Drugs/medical device/cosmetics": "",
            "Batch No": "",
            "Date of Manufacture": "",
            "Date of Expiry": "",
            "Manufactured By": "",
            "Reason for failure": "",
            "Drawn By": "",
            "From": "",
            "Remarks": "",
        }

        for key, value in record.items():
            key_clean = str(key).lower().strip()
            val_str = str(value).strip()
            matched = False
            for std_key, aliases in key_map.items():
                if any(alias in key_clean for alias in aliases):
                    if std_key == "s_no":
                        standard["S No"] = val_str
                    elif std_key == "product_name":
                        standard["Name of Drugs/medical device/cosmetics"] = val_str
                    elif std_key == "batch_no":
                        standard["Batch No"] = val_str
                    elif std_key == "mfg_date":
                        standard["Date of Manufacture"] = val_str
                    elif std_key == "exp_date":
                        standard["Date of Expiry"] = val_str
                    elif std_key == "mfg_by":
                        standard["Manufactured By"] = val_str
                    elif std_key == "reason":
                        standard["Reason for failure"] = val_str
                    elif std_key == "drawn_by":
                        standard["Drawn By"] = val_str
                    elif std_key == "from_lab":
                        standard["From"] = val_str
                    elif std_key == "remarks":
                        standard["Remarks"] = val_str
                    matched = True
                    break

            if not matched and str(key).startswith("Column_"):
                suffix = str(key).split("_", 1)[1]
                if suffix.isdigit():
                    col_num = int(suffix)
                    mapping = {
                        1: "S No",
                        2: "Name of Drugs/medical device/cosmetics",
                        3: "Batch No",
                        4: "Date of Manufacture",
                        5: "Date of Expiry",
                        6: "Manufactured By",
                        7: "Reason for failure",
                        8: "Drawn By",
                        9: "From",
                        10: "Remarks",
                    }
                    standard[mapping.get(col_num, "Remarks")] = val_str
        normalized.append(standard)
    return normalized


def _classify_document(subfolder: str, filename: str, headers_list: list[list[str]], sample_text: str):
    text_sample = (filename + " " + sample_text).lower()
    header_str = " ".join(" ".join(_clean_cell(cell) for cell in header) for header in headers_list).lower() if headers_list else ""

    if "spurious" in header_str or "spurious" in text_sample or "manufacturer details" in header_str:
        return DOCUMENT_TYPES["Doc 4"]
    if "suspected drugs" in header_str or "adverse drug reaction" in header_str or "pvpi" in text_sample:
        return DOCUMENT_TYPES["Doc 2"]
    if ("drugs name" in header_str or "prohibited" in text_sample or "banned" in text_sample) and ("notification" in text_sample or "26a" in text_sample):
        return DOCUMENT_TYPES["Doc 1"]
    if "nsq result" in header_str and ("reporting by lab" in header_str or "state lab" in header_str or "reporting source" in header_str):
        return DOCUMENT_TYPES["Doc 3"]
    if "cdsco laboratory" in header_str or "reported by cdsco" in header_str:
        return DOCUMENT_TYPES["Doc 5"]
    if "drawn by" in header_str or "reason for failure" in header_str:
        return DOCUMENT_TYPES["Doc 6"]
    if "device" in text_sample or "catheter" in text_sample or "implant" in text_sample:
        return DOCUMENT_TYPES["Doc 7"]
    if "approved" in text_sample and "indication" in text_sample:
        return DOCUMENT_TYPES["Doc 8"]
    if "fdc" in text_sample and ("irrational" in text_sample or "prohibition" in text_sample):
        return DOCUMENT_TYPES["Doc 9"]
    if "sec" in text_sample or "tentative schedule" in text_sample:
        return DOCUMENT_TYPES["Doc 10"]
    if "noc" in text_sample or "import" in text_sample:
        return DOCUMENT_TYPES["Doc 11"]
    if "vaccine" in text_sample and "inspection" in text_sample:
        return DOCUMENT_TYPES["Doc 12"]
    if "pcr" in text_sample or "testing kit" in text_sample:
        return DOCUMENT_TYPES["Doc 13"]
    if "laboratory" in text_sample and "ivd" in text_sample:
        return DOCUMENT_TYPES["Doc 14"]
    if "fee" in text_sample or "faq" in text_sample:
        return DOCUMENT_TYPES["Doc 15"]
    if "g.s.r" in text_sample or "s.o." in text_sample:
        return DOCUMENT_TYPES["Doc 16"]
    return ("General Regulatory Document", "Administrative")


def _process_table_rows(raw_rows: list[list[Any]], clean_headers: list[str], current_record: dict[str, Any] | None = None):
    records: list[dict[str, Any]] = []
    for row in raw_rows:
        if _is_noise_row(row):
            continue

        row_cells = [_clean_cell(cell) for cell in row]
        row_str = " ".join(row_cells).strip()
        first_cell = row_cells[0] if row_cells else ""
        second_cell = row_cells[1] if len(row_cells) > 1 else ""

        remark_match = (
            re.search(r"^(remark|remarks)\s*:\s*(.*)", first_cell, re.IGNORECASE)
            or re.search(r"^(remark|remarks)\s*:\s*(.*)", second_cell, re.IGNORECASE)
            or re.search(r"^(remark|remarks)\s*:\s*(.*)", row_str, re.IGNORECASE)
        )

        if remark_match and current_record is not None and not _is_valid_anchor(first_cell):
            remark_text = remark_match.group(2).strip()
            if not remark_text and len(row_cells) > 1:
                remark_text = " ".join(
                    cell for cell in row_cells if cell and not cell.lower().startswith("remark")
                ).strip()
            current_record["Remark"] = remark_text
            continue

        if _is_valid_anchor(first_cell):
            record: dict[str, Any] = {}
            for idx, value in enumerate(row_cells):
                col_name = clean_headers[idx] if idx < len(clean_headers) else f"Column_{idx + 1}"
                record[col_name] = value
            records.append(record)
            current_record = record
        elif current_record is not None:
            for idx, value in enumerate(row_cells):
                if not value:
                    continue
                col_name = clean_headers[idx] if idx < len(clean_headers) else f"Column_{idx + 1}"
                if col_name in current_record:
                    current_record[col_name] = (current_record[col_name] + " " + value).strip()
                else:
                    current_record[col_name] = value

    has_remark_added = any("Remark" in record for record in records)
    if has_remark_added and "Remark" not in clean_headers and "Remarks" not in clean_headers:
        clean_headers.append("Remark")

    return clean_headers, records, current_record


def _process_single_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    document_id = str(payload.get("doc_id") or payload.get("document_id") or "doc_unknown")
    source_category = _source_category(payload)
    title = _document_title(payload, document_id)
    source_key = str(payload.get("s3_object_key") or payload.get("source_file") or f"{document_id}.pdf")
    filename = PurePosixPath(source_key).name
    tables = payload.get("tables") or []

    pvpi_result = _parse_pvpi_alert(payload)
    if pvpi_result is not None:
        return pvpi_result

    if _is_banned_drugs_payload(payload):
        banned_result = _run_exact_legacy_parser(payload, "banneddrugs", "banned_drugs")
        if banned_result is not None:
            return banned_result

    is_special_document = any(special_id.casefold() in filename.casefold() for special_id in SPECIAL_FILE_IDS)
    if tables or is_special_document:
        legacy_result = _run_exact_legacy_parser(payload, filename, source_category)
        if legacy_result is not None:
            return legacy_result

    all_records: list[dict[str, Any]] = []
    all_exact_columns: list[str] = []
    all_pages: set[int] = set()
    sample_text = " ".join(
        page.get("text") or "" for page in (payload.get("pages") or [])
    )
    headers_found: list[list[str]] = []
    master_headers: list[str] | None = None
    current_record: dict[str, Any] | None = None

    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = _rows_from_table(table)
        if not rows or not isinstance(rows, list):
            continue
        page_num = table.get("page") or 1
        all_pages.add(int(page_num))
        if _is_summary_table(rows):
            continue

        if master_headers is None:
            header_idx, clean_headers = _find_real_header_row(rows)
            master_headers = clean_headers
            headers_found.append(clean_headers)
            data_rows = rows[header_idx + 1:]
        else:
            first_row = " ".join(_clean_cell(cell) for cell in rows[0]).lower() if rows else ""
            if any(term in first_row for term in ["s no", "s n", "batch no", "product", "manufactured by", "name of drug"]):
                data_rows = rows[1:]
            else:
                data_rows = rows

        master_headers, records, current_record = _process_table_rows(data_rows, master_headers, current_record)
        if not all_exact_columns and master_headers:
            all_exact_columns = master_headers
        elif "Remark" in (master_headers or []) and "Remark" not in all_exact_columns and "Remarks" not in all_exact_columns:
            all_exact_columns.append("Remark")
        all_records.extend(records)

    doc_type, group_type = _classify_document(source_category, filename, headers_found, sample_text)

    if source_category in ["alerts", "nsq_json"] and doc_type in [
        DOCUMENT_TYPES["Doc 3"],
        DOCUMENT_TYPES["Doc 4"],
        DOCUMENT_TYPES["Doc 5"],
        DOCUMENT_TYPES["Doc 6"],
    ]:
        all_records = _normalize_alert_records(all_records)
        all_exact_columns = [
            "S No",
            "Name of Drugs/medical device/cosmetics",
            "Batch No",
            "Date of Manufacture",
            "Date of Expiry",
            "Manufactured By",
            "Reason for failure",
            "Drawn By",
            "From",
            "Remarks",
        ]

    structured_json = {
        "document_id": document_id,
        "source_file": source_key,
        "pdf_path": source_key,
        "source_category": source_category,
        "document_type": doc_type,
        "group_type": group_type,
        "title": title,
        "pages": sorted(all_pages),
        "total_rows": len(all_records),
        "exact_columns": all_exact_columns,
        "records": all_records,
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


def _read_event_bearing_source_keys(s3_client: Any, bucket: str, key: str) -> set[str]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    required_columns = {"bucket", "s3_object_key"}
    if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
        raise ValueError(
            "Classifier CSV must contain 'bucket' and 's3_object_key' columns"
        )
    return {
        source_key.strip()
        for row in reader
        if (row.get("bucket") or "").strip().casefold() == "event-bearing"
        if (source_key := (row.get("s3_object_key") or "").strip())
    }


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
    parser.add_argument("--limit", type=int, default=0, help="Optional file limit")
    args = parser.parse_args(argv)

    if not args.bucket:
        parser.error("--bucket is required")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    s3_client = boto3.client("s3", region_name=args.region)
    keys = _iter_s3_objects(s3_client, args.bucket, args.prefix)
    if args.doc_id:
        keys = [key for key in keys if key == args.doc_id]
    if args.limit:
        keys = keys[:args.limit]
    classifier_bucket = args.classifier_csv_bucket or args.bucket
    try:
        event_bearing_source_keys = _read_event_bearing_source_keys(
            s3_client, classifier_bucket, args.classifier_csv_key
        )
    except Exception as exc:
        parser.error(
            f"Could not load classifier CSV from s3://{classifier_bucket}/"
            f"{args.classifier_csv_key}: {exc}"
        )
    if not keys:
        print(
            f"No JSON files found in s3://{args.bucket}/{args.prefix}. "
            "Point --prefix to the extractor JSON output, currently "
            "medicine-data-storage/processed_files/extracted_json.",
            file=sys.stderr,
        )
        return 1

    parsed_keys: list[str] = []
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
                if not source_pdf_key or source_pdf_key not in event_bearing_source_keys:
                    skipped_count += 1
                    print(f"Skipped (not event-bearing): {s3_key}")
                    continue
                batch_payloads.append((s3_key, payload))
            except Exception as exc:
                failed += 1
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
                title = structured.get("title") or payload.get("pdf_title") or payload.get("title")
                output_key = _output_key_for_document(s3_key, args.prefix, args.s3_output_prefix, title)
                _write_json_to_s3(s3_client, args.s3_output_bucket, output_key, structured)
                parsed_keys.append(source_pdf_key or s3_key)
                print(f"Parsed {index}/{len(keys)}: {s3_key} -> s3://{args.s3_output_bucket}/{output_key}")
            except Exception as exc:
                failed += 1
                print(f"ERROR parsing {s3_key}: {exc}", file=sys.stderr)

    update_parsed_documents(parsed_keys)
    print(
        f"Parsing complete: {len(parsed_keys)} event-bearing documents parsed; "
        f"{skipped_count} non-event-bearing documents skipped"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
