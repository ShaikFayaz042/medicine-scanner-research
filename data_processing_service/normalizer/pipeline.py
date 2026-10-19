"""Self-contained parsed JSON to staging CSV normalizer."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime
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

# Values allowed by the regulatory_documents.document_type CHECK constraint.
DOCUMENT_TYPE_ENUM = {
    "BANNED_DRUGS", "PVPI_ADR", "NSQ_STATE", "SPURIOUS", "NSQ_CDSCO", "LEGACY_CDSCO",
    "MEDICAL_DEVICE", "APPROVED_DRUGS", "NOC_IMPORT_FDC", "MIXED_ALERT", "UNKNOWN",
}
# Parser document types ("Doc N: ...") mapped onto that enum.
PARSER_DOCUMENT_TYPES = {
    1: "BANNED_DRUGS", 2: "PVPI_ADR", 3: "NSQ_STATE", 4: "SPURIOUS", 5: "NSQ_CDSCO", 6: "LEGACY_CDSCO",
    7: "MEDICAL_DEVICE", 8: "APPROVED_DRUGS", 9: "BANNED_DRUGS", 10: "UNKNOWN", 11: "NOC_IMPORT_FDC",
    12: "UNKNOWN", 13: "APPROVED_DRUGS", 14: "UNKNOWN", 15: "UNKNOWN", 16: "BANNED_DRUGS", 17: "MIXED_ALERT",
}
EVENT_TYPE_BY_DOCUMENT = {
    "NSQ_CDSCO": "NSQ", "NSQ_STATE": "NSQ", "LEGACY_CDSCO": "NSQ", "SPURIOUS": "SPURIOUS",
    "BANNED_DRUGS": "BANNED", "PVPI_ADR": "ADR", "MEDICAL_DEVICE": "SAFETY_ADVISORY",
    "APPROVED_DRUGS": "APPROVAL", "NOC_IMPORT_FDC": "NOC", "MIXED_ALERT": "OTHER",
}
# Record wording that decides the event type within mixed documents (checked in order).
EVENT_TYPE_BY_KEYWORD = (
    ("SPURIOUS", re.compile(r"\b(?:spurious|falsified|counterfeit)\b", re.I)),
    ("RECALL", re.compile(r"\brecall", re.I)),
    ("PROHIBITED", re.compile(r"\bprohibit", re.I)),
)

PRODUCT_FIELDS = ("product_name", "Name of Drugs/medical device/cosmetics", "name of drug", "product name",
                  "drug_name", "str_product_name", "suspected drug", "drugs name", "name")
BATCH_FIELDS = ("batch_number", "Batch No", "batch_no", "batch no", "lot_no", "str_batch_no", "batch")
MANUFACTURER_FIELDS = ("manufacturer_name", "Manufactured By", "manufactured_by", "manufactured by",
                       "str_manufactured_by", "manufacturer")
REPORTING_FIELDS = ("reporting_organization", "From", "reporting source", "str_reporting_source", "reported_by",
                    "Drawn By")
REASON_FIELDS = ("reason", "Reason for failure", "nsq_result", "str_nsq_result", "Adverse Drug Reactions",
                 "description", "result", "Subject")
MFG_DATE_FIELDS = ("manufacturing_date", "Date of Manufacture", "mfg_date", "str_mfg_date")
EXPIRY_FIELDS = ("expiry_date", "Date of Expiry", "exp_date", "str_exp_date")
EVENT_DATE_FIELDS = ("event_date", "date", "dt_reporting_month_year", "issue_date", "Issue Date")
MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _canonical(value: Any) -> str:
    """Organization names: lowercase, punctuation-free, with company suffixes dropped."""
    text = str(value or "").lower().strip()
    text = re.sub(r"\b(pvt|private|ltd|limited|inc|corp|corporation|co|company)\b\.?", "", text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text)).strip()


def _product_canonical(value: Any) -> str:
    """Product names keep every word; dropping company suffixes turned "Co-trimoxazole" into "trimoxazole"."""
    text = str(value or "").lower().strip()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+%.\s]", " ", text)).strip()


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


def _exact_field(record: dict[str, Any], *names: str) -> str:
    """Like _field, without the substring fallback ("date" must not match "Date of Manufacture")."""
    lowered = {str(key).lower().replace("_", " "): key for key in record}
    for name in names:
        key = name if name in record else lowered.get(name.lower().replace("_", " "))
        if key is not None and record.get(key) not in (None, ""):
            return str(record[key]).strip()
    return ""


# What alerts print when the label gave no value: "Not Mentioned", "Not stated", "Not Specified", "null", "NA".
PLACEHOLDER = re.compile(
    r"^(?:not\s+(?:mentioned|stated|specified|known|available|given|provided|applicable)\b.*|n\.?\s*a\.?|nil|null|none|unknown|[-\u2013\u2014]+)$",
    re.I,
)


def _known(value: str) -> str:
    """The value, or "" when it only says the value is missing (no batch / organization named "Not Mentioned")."""
    return "" if PLACEHOLDER.match(value.strip(" .:")) else value


def _date_value(value: Any) -> str:
    """ISO date from the formats CDSCO uses; month-only dates become the first of the month.

    Handles 2025-01-15, 15.01.2025, 15/01/2025, 01/2024, Jul-24, Feb.2023, "Aug 2026", "2025-Jul-18",
    "22nd May, 2025" and "2025-06". Unrecognized text is returned unchanged (the ingester stores NULL).
    """
    text = str(value or "").strip().rstrip(".")
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if match := re.fullmatch(r"(\d{4})-(\d{2})", text):
        return _safe_date(int(match.group(1)), int(match.group(2)), 1) or text
    if match := re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", text):
        return _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1))) or text
    if match := re.search(r"\b(\d{4})-([A-Za-z]{3})[A-Za-z]*-(\d{1,2})\b", text):
        month = MONTHS.get(match.group(2).lower())
        return _safe_date(int(match.group(1)), month, int(match.group(3))) or text if month else text
    if match := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[A-Za-z]*,?\s+(\d{4})\b", text):
        month = MONTHS.get(match.group(2).lower())
        return _safe_date(int(match.group(3)), month, int(match.group(1))) or text if month else text
    if match := re.search(r"\b(\d{1,2})[-/](\d{4})\b", text):
        return _safe_date(int(match.group(2)), int(match.group(1)), 1) or text
    if match := re.search(r"\b([A-Za-z]{3})[A-Za-z]*[\s.\-/,]*(\d{4}|\d{2})\b", text):
        month = MONTHS.get(match.group(1).lower())
        if month:
            year = int(match.group(2))
            return _safe_date(year + 2000 if year < 100 else year, month, 1) or text
    return text


def _safe_date(year: int, month: int | None, day: int) -> str:
    try:
        return date(year, month or 0, day).isoformat()
    except (TypeError, ValueError):
        return ""


def _records(data: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(data, list):
        return {}, [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        raise ValueError("Parsed JSON root must be an object or array")
    metadata = data.get("document_metadata") or {}
    scraper = data.get("scraper_metadata") if isinstance(data.get("scraper_metadata"), dict) else {}
    header = {
        "source_organization": data.get("source_organization") or metadata.get("issuing_authority") or "CDSCO",
        "source_document_id": data.get("source_document_id") or data.get("document_id"),
        "document_title": metadata.get("title") or data.get("document_title") or data.get("title") or scraper.get("title"),
        "publication_date": (
            data.get("publication_date") or metadata.get("date_of_issue") or data.get("release_date")
            or scraper.get("release_date") or data.get("reporting_period")
        ),
        "reporting_period": data.get("reporting_period"),
        "source_url": data.get("pdf_path"),
        "document_type": data.get("document_type") or data.get("record_type"),
        "classifier_review": data.get("classifier_review"),
    }
    for key in ("records", "aaData", "rows", "data", "items", "prohibited_drugs", "adr_alerts", "fdc_list"):
        if isinstance(data.get(key), list):
            return header, [item for item in data[key] if isinstance(item, dict)]
    return header, [data]


def _document_type(header: dict[str, Any], filename: str) -> str:
    """Map a parsed document type onto the regulatory_documents.document_type CHECK values."""
    value = str(header.get("document_type") or "").strip()
    upper = value.upper()
    if match := re.match(r"DOC\s*(\d+)\b", upper):
        return PARSER_DOCUMENT_TYPES.get(int(match.group(1)), "UNKNOWN")
    if upper in DOCUMENT_TYPE_ENUM:
        return upper
    if upper in {"NSQ", "NSQ_FILE"}:
        return "NSQ_CDSCO"
    if upper in {"SPURIOUS", "SPURIOUS_FILE"}:
        return "SPURIOUS"
    if "BANNED" in upper or "BANNED" in filename.upper():
        return "BANNED_DRUGS"
    if "PVPI" in upper or "ADR" in upper:
        return "PVPI_ADR"
    if "NSQ" in upper or "NSQ" in filename.upper():
        return "NSQ_STATE"
    return "UNKNOWN"


def _event_type(document_type: str, record: dict[str, Any]) -> str:
    text = " ".join(str(value) for value in record.values() if isinstance(value, str))
    for event_type, pattern in EVENT_TYPE_BY_KEYWORD:
        if pattern.search(text) and document_type not in {"BANNED_DRUGS", "PVPI_ADR"}:
            return event_type
    return EVENT_TYPE_BY_DOCUMENT.get(document_type, "OTHER")


def _int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_record(
    document_id: str,
    document_type: str,
    record: dict[str, Any],
    index: int,
    header: dict[str, Any] | None = None,
) -> dict[str, Any]:
    header = header or {}
    product = _field(record, *PRODUCT_FIELDS)
    batch = _known(_field(record, *BATCH_FIELDS))
    manufacturer = _known(_field(record, *MANUFACTURER_FIELDS))
    reporting = _field(record, *REPORTING_FIELDS)
    reason = _field(record, *REASON_FIELDS)
    notification = _field(record, "Notification No. & Date", "notification")
    document_id = str(document_id or "document")
    page = _int(record.get("page_number") or record.get("page"), 1)
    source_record_id = f"{document_id}:P{page:02d}:T{_int(record.get('table_number') or record.get('table'), 1):02d}:{index:02d}"
    product_key = _key("PROD", _product_canonical(product), _product_canonical(record.get("strength")), _product_canonical(record.get("dosage_form")), "DRUG") if product else ""
    manufacturer_key = _key("ORG", _canonical(manufacturer)) if manufacturer and not re.fullmatch(r"(?i)under investigation", manufacturer) else ""
    batch_key = _key("BATCH", product_key, manufacturer_key, _product_canonical(batch)) if product_key and batch else ""
    event_type = _event_type(document_type, record)
    raw_event_date = _exact_field(record, *EVENT_DATE_FIELDS)
    event_date = _date_value(raw_event_date) or _date_value(header.get("publication_date"))
    event_key = _key("EVT", document_id, source_record_id, event_type, raw_event_date)
    source_text = str(record.get("source_text") or json.dumps(record, ensure_ascii=False))
    classifier_review = header.get("classifier_review") or {}

    # Records are VALID when they identify a product, or when a product-less record still documents a
    # regulatory action (notification circulars). Anything else needs review and is not ingested.
    if product:
        normalization_status, validation_status, review_reason = "COMPLETE", "VALID", ""
    elif notification or reason:
        normalization_status, validation_status, review_reason = "COMPLETE", "VALID", "document_level_record"
    else:
        normalization_status, validation_status, review_reason = "NEEDS_REVIEW", "NEEDS_REVIEW", "missing_product_name"
    if classifier_review:
        reasons = ",".join(classifier_review.get("reasons") or []) or "flagged"
        review_reason = "; ".join(part for part in (review_reason, f"classifier_review:{reasons}") if part)

    return {
        "source_record_id": source_record_id, "product_key": product_key, "product_name": product,
        "normalized_product_name": _product_canonical(product), "brand_name": _field(record, "brand_name", "brand"),
        "dosage_form": _field(record, "dosage_form"), "strength": _field(record, "strength"),
        "manufacturer_organization_key": manufacturer_key, "manufacturer_name": manufacturer if manufacturer_key else "",
        "manufacturer_address": _field(record, "manufacturer_address"), "reporting_organization_key": _key("ORG", _canonical(reporting)) if reporting else "",
        "reporting_organization_name": reporting, "batch_key": batch_key, "batch_number": batch,
        "manufacturing_date": _date_value(_field(record, *MFG_DATE_FIELDS)), "expiry_date": _date_value(_field(record, *EXPIRY_FIELDS)),
        "event_key": event_key, "event_type": event_type, "event_date": event_date,
        "scope": "BATCH" if batch_key else "PRODUCT" if product else "DOCUMENT", "status": record.get("status") or event_type,
        "reason": reason, "action": record.get("action") or "", "legal_status": record.get("legal_status") or notification,
        "page_number": page, "source_location": record.get("source_location") or f"Page {page}, row {index}",
        "extraction_method": record.get("extraction_method") or "TEXT", "source_text": source_text, "raw_json": record,
        "normalization_status": normalization_status, "validation_status": validation_status,
        "review_reason": review_reason, "error_message": "",
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
    normalized = [_normalize_record(str(header["source_document_id"]), document_type, record, index, header) for index, record in enumerate(records, start=1)]
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
