"""Self-contained parsed JSON to staging CSV normalizer."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


STAGING_FILES = (
    "regulatory_documents.csv",
    "raw_source_records.csv",
    "organizations.csv",
    "ingredients.csv",
    "products.csv",
    "product_ingredients.csv",
    "product_organizations.csv",
    "batches.csv",
    "regulatory_events.csv",
    "normalization_manifest.csv",
)


def _canonical(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"\b(pvt|private|ltd|limited|inc|corp|corporation|co|company)\b\.?", "", text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text)).strip()


def _key(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _field(record: dict[str, Any], *names: str) -> str:
    for name in names:
        if record.get(name) not in (None, ""):
            return str(record[name]).strip()
    normalized = {str(key).lower().replace("_", " "): key for key in record}
    for name in names:
        key = normalized.get(name.lower().replace("_", " "))
        if key is not None and record.get(key) not in (None, ""):
            return str(record[key]).strip()
    for key, value in record.items():
        key_text = str(key).lower().replace("_", " ")
        if value not in (None, "") and any(name.lower() in key_text for name in names):
            return str(value).strip()
    return ""


def _date_value(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.search(r"\b(\d{1,2})[-/](\d{4})\b", text)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return date(year, month, 1).isoformat()
    return text


def _records(data: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(data, list):
        return {}, [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        raise ValueError("Parsed JSON root must be an object or array")
    metadata = data.get("document_metadata") or {}
    header = {
        "source_organization": data.get("source_organization") or metadata.get("issuing_authority") or "CDSCO",
        "source_document_id": data.get("source_document_id") or data.get("document_id"),
        "document_title": metadata.get("title") or data.get("document_title"),
        "publication_date": data.get("publication_date") or metadata.get("date_of_issue"),
        "reporting_period": data.get("reporting_period"),
        "source_url": data.get("pdf_path"),
        "document_type": data.get("document_type") or data.get("record_type"),
    }
    for key in ("records", "aaData", "rows", "data", "items", "prohibited_drugs", "adr_alerts", "fdc_list"):
        if isinstance(data.get(key), list):
            return header, [item for item in data[key] if isinstance(item, dict)]
    return header, [data]


def _document_type(header: dict[str, Any], filename: str) -> str:
    value = str(header.get("document_type") or "").upper()
    if value in {"GENERAL REGULATORY DOCUMENT", "ADMINISTRATIVE", "REGULATORY DOCUMENT", "DOCUMENT"}:
        return "UNKNOWN"
    if value in {"NSQ", "NSQ_CDSCO"}:
        return "NSQ_CDSCO"
    if value == "SPURIOUS":
        return value
    if "BANNED" in value or "BANNED" in filename.upper():
        return "BANNED_DRUGS"
    if "PVPI" in value or "ADR" in value:
        return "PVPI_ADR"
    if "NSQ" in value or "NSQ" in filename.upper():
        return "NSQ_STATE"
    return value or "UNKNOWN"


def _normalize_record(document_id: str, document_type: str, record: dict[str, Any], index: int) -> dict[str, Any]:
    product = _field(record, "product_name", "product name", "drug_name", "name of drug", "str_product_name", "name")
    batch = _field(record, "batch_number", "batch_no", "batch no", "lot_no", "str_batch_no", "batch")
    manufacturer = _field(record, "manufacturer_name", "manufactured_by", "manufactured by", "str_manufactured_by", "manufacturer")
    reporting = _field(record, "reporting_organization", "reporting source", "str_reporting_source", "reported_by", "from")
    reason = _field(record, "reason", "reason for failure", "nsq_result", "str_nsq_result", "description", "result")
    document_id = str(document_id or "document")
    source_record_id = f"{document_id}:P{int(record.get('page_number') or record.get('page') or 1):02d}:T{int(record.get('table_number') or record.get('table') or 1):02d}:{index:02d}"
    product_key = _key("PROD", _canonical(product), _canonical(record.get("strength")), _canonical(record.get("dosage_form")), "DRUG") if product else ""
    manufacturer_key = _key("ORG", _canonical(manufacturer)) if manufacturer else ""
    batch_key = _key("BATCH", product_key, manufacturer_key, _canonical(batch)) if product_key and batch else ""
    event_type = "NSQ" if document_type in {"NSQ_CDSCO", "NSQ_STATE"} else "BANNED" if document_type == "BANNED_DRUGS" else "ADR" if document_type == "PVPI_ADR" else "OTHER"
    event_key = _key("EVT", document_id, source_record_id, event_type, record.get("event_date") or record.get("date"))
    source_text = str(record.get("source_text") or json.dumps(record, ensure_ascii=False))
    return {
        "source_record_id": source_record_id, "product_key": product_key, "product_name": product,
        "normalized_product_name": _canonical(product), "brand_name": _field(record, "brand_name", "brand"),
        "dosage_form": _field(record, "dosage_form"), "strength": _field(record, "strength"),
        "manufacturer_organization_key": manufacturer_key, "manufacturer_name": manufacturer,
        "manufacturer_address": _field(record, "manufacturer_address"), "reporting_organization_key": _key("ORG", _canonical(reporting)) if reporting else "",
        "reporting_organization_name": reporting, "batch_key": batch_key, "batch_number": batch,
        "manufacturing_date": _field(record, "manufacturing_date", "mfg_date"), "expiry_date": _field(record, "expiry_date", "exp_date"),
        "event_key": event_key, "event_type": event_type, "event_date": _date_value(record.get("event_date") or record.get("date")),
        "scope": "BATCH" if batch else "PRODUCT" if product else "DOCUMENT", "status": record.get("status") or event_type,
        "reason": reason, "action": record.get("action") or "", "legal_status": record.get("legal_status") or "",
        "page_number": record.get("page_number") or record.get("page") or 1, "source_location": record.get("source_location") or f"Page {index}",
        "extraction_method": record.get("extraction_method") or "TEXT", "source_text": source_text, "raw_json": record,
        "normalization_status": "COMPLETE" if product else "NEEDS_REVIEW", "validation_status": "PENDING",
        "review_reason": "" if product else "missing_product_name", "error_message": "",
    }


def _write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def run_pipeline(input_filepath: str, output_dir: str, load_db_flag: bool = False, db_uri: str | None = None) -> int:
    del load_db_flag, db_uri
    input_path = Path(input_filepath)
    if not input_path.is_file():
        return 1
    data = json.loads(input_path.read_text(encoding="utf-8", errors="replace"))
    header, records = _records(data)
    header["filename"] = input_path.name
    header["source_document_id"] = header.get("source_document_id") or input_path.name
    header["source_url"] = header.get("source_url") or str(input_path)
    document_type = _document_type(header, input_path.name)
    header["document_type"] = document_type
    normalized = [_normalize_record(str(header["source_document_id"]), document_type, record, index) for index, record in enumerate(records, start=1)]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "regulatory_documents.csv", ["source_organization", "source_document_id", "filename", "document_title", "publication_date", "reporting_period", "source_url", "file_hash", "document_type"], [[header.get("source_organization", "CDSCO"), header["source_document_id"], header["filename"], header.get("document_title") or header["filename"], _date_value(header.get("publication_date")), header.get("reporting_period") or "", header["source_url"], "", document_type]])
    _write_csv(output / "raw_source_records.csv", ["source_document_id", "source_record_id", "page_number", "source_location", "extraction_method", "source_text", "raw_json"], [[header["source_document_id"], row["source_record_id"], row["page_number"], row["source_location"], row["extraction_method"], row["source_text"], json.dumps(row["raw_json"], ensure_ascii=False)] for row in normalized])
    organizations = {}
    for row in normalized:
        for key, name, address in ((row["manufacturer_organization_key"], row["manufacturer_name"], row["manufacturer_address"]), (row["reporting_organization_key"], row["reporting_organization_name"], "")):
            if key and name:
                organizations[key] = [key, name, _canonical(name), address, "", "India"]
    _write_csv(output / "organizations.csv", ["organization_key", "organization_name", "normalized_name", "address", "state", "country"], list(organizations.values()))
    _write_csv(output / "ingredients.csv", ["ingredient_key", "ingredient_name", "normalized_name", "cas_number"], [])
    products = {row["product_key"]: [row["product_key"], row["product_name"], row["normalized_product_name"], row["brand_name"], row["dosage_form"], row["strength"], "DRUG"] for row in normalized if row["product_key"]}
    _write_csv(output / "products.csv", ["product_key", "product_name", "normalized_name", "brand_name", "dosage_form", "strength", "product_category"], list(products.values()))
    _write_csv(output / "product_ingredients.csv", ["product_key", "ingredient_key", "ingredient_strength"], [])
    _write_csv(output / "product_organizations.csv", ["product_key", "organization_key", "role"], [[row["product_key"], row["manufacturer_organization_key"], "MANUFACTURER"] for row in normalized if row["product_key"] and row["manufacturer_organization_key"]])
    _write_csv(output / "batches.csv", ["batch_key", "product_key", "organization_key", "batch_number", "manufacturing_date", "expiry_date"], [[row["batch_key"], row["product_key"], row["manufacturer_organization_key"], row["batch_number"], row["manufacturing_date"], row["expiry_date"]] for row in normalized if row["batch_key"]])
    _write_csv(output / "regulatory_events.csv", ["event_key", "source_document_id", "source_record_id", "event_type", "event_date", "scope", "product_key", "batch_key", "manufacturer_organization_key", "reporting_organization_key", "status", "reason", "action", "legal_status", "additional_data"], [[row["event_key"], header["source_document_id"], row["source_record_id"], row["event_type"], row["event_date"], row["scope"], row["product_key"], row["batch_key"], row["manufacturer_organization_key"], row["reporting_organization_key"], row["status"], row["reason"], row["action"], row["legal_status"], json.dumps(row["raw_json"], ensure_ascii=False)] for row in normalized])
    _write_csv(output / "normalization_manifest.csv", ["source_record_id", "source_document_id", "source_file", "source_page", "source_row", "source_document_type", "organization_key", "product_key", "batch_key", "event_key", "normalization_status", "validation_status", "review_reason", "error_message"], [[row["source_record_id"], header["source_document_id"], header["filename"], row["page_number"], row["source_location"], document_type, row["manufacturer_organization_key"], row["product_key"], row["batch_key"], row["event_key"], row["normalization_status"], row["validation_status"], row["review_reason"], row["error_message"]] for row in normalized])
    return 0
