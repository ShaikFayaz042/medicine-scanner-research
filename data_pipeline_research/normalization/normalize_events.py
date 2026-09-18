"""Emit regulatory_events rows from structured_raw records."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR,
    STRUCTURED_RAW,
    collapse_ws,
    classify_missing,
    load_all_configs,
    make_source_record_id,
    read_json,
    safe_str,
    resolve_event_mapping,
    utcnow_iso,
    write_jsonl,
)

DEFAULT_BY_RECORD_TYPE = {
    "NSQ": {"event_type": "QUALITY_FAILURE", "status": "NOT_OF_STANDARD_QUALITY", "scope": "BATCH"},
    "DRUG_ALERT": {"event_type": "QUALITY_FAILURE", "status": "NOT_OF_STANDARD_QUALITY", "scope": "BATCH"},
    "DRUG_ALERT_NARRATIVE": {"event_type": "DRUG_ALERT", "status": "ALERT", "scope": "PRODUCT"},
    "SPURIOUS": {"event_type": "SPURIOUS_ALERT", "status": "SPURIOUS", "scope": "BATCH"},
    "PVPI_SAFETY": {"event_type": "PHARMACOVIGILANCE_SAFETY_ALERT", "status": "SAFETY_ALERT", "scope": "PRODUCT"},
    "THEFT_RECALL": {"event_type": "THEFT_RECALL", "status": "RECALLED", "scope": "DOCUMENT"},
    "MEDICAL_DEVICE": {"event_type": "MEDICAL_DEVICE_ALERT", "status": "ALERT", "scope": "DOCUMENT"},
    "IVD_ALERT": {"event_type": "IVD_ALERT", "status": "ALERT", "scope": "DOCUMENT"},
    "GAZETTE_LEGAL": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
    "CIRCULAR": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
    "GUIDELINE": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
    "OTHER": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
}

DEFAULT_BY_DOCUMENT_TYPE = {
    "NSQ_ALERT": {"event_type": "QUALITY_FAILURE", "status": "NOT_OF_STANDARD_QUALITY", "scope": "BATCH"},
    "SPURIOUS_ALERT": {"event_type": "SPURIOUS_ALERT", "status": "SPURIOUS", "scope": "BATCH"},
    "DRUG_ALERT": {"event_type": "QUALITY_FAILURE", "status": "NOT_OF_STANDARD_QUALITY", "scope": "BATCH"},
    "FDC_PROHIBITED": {"event_type": "FDC_PROHIBITION", "status": "PROHIBITED", "legal_status": "PROHIBITED", "scope": "COMBINATION"},
    "FDC_NOTIFICATION": {"event_type": "FDC_NOTIFICATION", "status": None, "scope": "COMBINATION"},
    "GAZETTE_LEGAL": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
    "PVPI_SAFETY": {"event_type": "PHARMACOVIGILANCE_SAFETY_ALERT", "status": "SAFETY_ALERT", "scope": "PRODUCT"},
    "THEFT_RECALL": {"event_type": "THEFT_RECALL", "status": "RECALLED", "scope": "DOCUMENT"},
    "MEDICAL_DEVICE": {"event_type": "MEDICAL_DEVICE_ALERT", "status": "ALERT", "scope": "DOCUMENT"},
    "IVD_ALERT": {"event_type": "IVD_ALERT", "status": "ALERT", "scope": "DOCUMENT"},
    "CIRCULAR": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
    "GUIDELINE": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
    "OTHER": {"event_type": "DOCUMENT_ISSUANCE", "status": None, "scope": "DOCUMENT"},
}

STATUS_SCAN_FIELDS = {
    "NSQ_ALERT": ["reason", "nsq_result"],
    "DRUG_ALERT": ["reason", "nsq_result"],
    "SPURIOUS_ALERT": ["remarks"],
    "PVPI_SAFETY": ["adr"],
}


def iter_document_files(folder_dir: Path) -> list[Path]:
    return [path for path in sorted(folder_dir.glob("*.json")) if not path.name.startswith("_")]


def build_prose_event(folder: str, file: Path, rec: dict, document_type: str, policy: dict, idx: int) -> dict:
    detected = rec.get("detected") or {}
    raw_text = rec.get("raw_text") or ""
    actions = detected.get("actions") or [] if isinstance(detected, dict) else []
    quality_flags = detected.get("quality_flags") or [] if isinstance(detected, dict) else []
    return {
        "document_type": document_type,
        "scope": policy.get("scope", "DOCUMENT"),
        "event_type": policy.get("event_type_fallback", "DOCUMENT_ISSUANCE"),
        "status": policy.get("status"),
        "legal_status": None,
        "reason": None,
        "effective_date": None,
        "investigation_status": None,
        "sample_collected_by": None,
        "testing_lab": None,
        "legal_reference": None,
        "additional_data": {
            "raw_text": raw_text,
            "detected": detected,
            "review_required": policy.get("review_required", False),
            "extraction_status": "PROSE_ONLY",
            "hint_actions": actions,
            "hint_quality_flags": quality_flags,
            "_validation": {
                "reason": "NOT_APPLICABLE",
                "legal_reference": "NOT_APPLICABLE",
                "sample_collected_by": "NOT_APPLICABLE",
            },
        },
        "source_record_id": make_source_record_id(folder, file.name, idx),
        "_folder": folder,
        "_source_file": str(file.relative_to(STRUCTURED_RAW)).replace("\\", "/"),
        "_normalized_at": utcnow_iso(),
        "_record_type": rec.get("record_type"),
    }


def build_table_event(folder: str, file: Path, rec: dict, document_type: str, type_config: dict, status_mapping: dict, idx: int) -> dict:
    canonical = rec.get("canonical") or {}
    raw_data = rec.get("raw_data") or {}
    record_type = rec.get("record_type") or ""
    base = DEFAULT_BY_RECORD_TYPE.get(record_type) or DEFAULT_BY_DOCUMENT_TYPE.get(document_type) or {}
    event_type = base.get("event_type", "DOCUMENT_ISSUANCE")
    status = base.get("status")
    legal_status = base.get("legal_status")
    scope = base.get("scope", "DOCUMENT")
    investigation_status = None
    matched_priority = 0
    matched_phrase = "default"
    scan_fields = STATUS_SCAN_FIELDS.get(document_type, [])
    scan_text = " ".join(str(canonical.get(field) or "") for field in scan_fields if canonical.get(field))
    if scan_text:
        mapped = resolve_event_mapping(collapse_ws(scan_text), status_mapping)
        if mapped and mapped.get("event_type") and int(mapped.get("_matched_rule_priority") or 0) > 0:
            event_type = mapped["event_type"]
            status = mapped.get("status")
            legal_status = mapped.get("legal_status")
            if mapped.get("scope") in ("BATCH", "PRODUCT", "COMBINATION"):
                scope = mapped["scope"]
            investigation_status = mapped.get("investigation_status")
            matched_priority = mapped.get("_matched_rule_priority")
            matched_phrase = mapped.get("_matched_phrase")
    additional_data = {
        "raw_data": raw_data,
        "canonical": canonical,
        "record_type": rec.get("record_type"),
        "section": rec.get("section"),
        "prose": rec.get("prose", False),
        "review_required": False,
        "_matched_rule_priority": matched_priority,
        "_matched_phrase": matched_phrase,
    }
    for key in type_config.get("canonical_to_additional_data", []):
        if key in canonical:
            additional_data[key] = canonical[key]
    reason = safe_str(canonical.get("reason") or canonical.get("nsq_result"))
    sample_collected_by = safe_str(canonical.get("sample_collected_by") or canonical.get("reported_by") or canonical.get("drawn_by"))
    legal_reference = safe_str(canonical.get("notification_number") or canonical.get("legal_reference"))
    additional_data["_validation"] = {
        "reason": classify_missing(reason, applicable=scope in ("BATCH", "PRODUCT", "COMBINATION")),
        "legal_reference": classify_missing(legal_reference, applicable=event_type in ("FDC_PROHIBITION", "FDC_RESTRICTION", "PROHIBITION")),
        "sample_collected_by": classify_missing(sample_collected_by, applicable=scope == "BATCH"),
    }
    return {
        "document_type": document_type,
        "scope": scope,
        "event_type": event_type,
        "status": status,
        "legal_status": legal_status,
        "reason": reason,
        "effective_date": None,
        "investigation_status": investigation_status,
        "sample_collected_by": sample_collected_by,
        "testing_lab": safe_str(canonical.get("testing_lab") or canonical.get("lab")),
        "legal_reference": legal_reference,
        "additional_data": additional_data,
        "source_record_id": make_source_record_id(folder, file.name, idx),
        "_folder": folder,
        "_source_file": str(file.relative_to(STRUCTURED_RAW)).replace("\\", "/"),
        "_normalized_at": utcnow_iso(),
        "_record_type": record_type,
        "_raw_slots": {
            slot: safe_str(canonical.get(canonical_key))
            for canonical_key, slot in (type_config.get("canonical_to_slot") or {}).items()
            if canonical.get(canonical_key)
        },
    }


def build_empty_event(folder: str, file: Path, document_type: str, policy: dict) -> dict:
    return {
        "document_type": document_type,
        "scope": policy.get("scope", "DOCUMENT"),
        "event_type": policy.get("event_type_fallback", "DOCUMENT_ISSUANCE"),
        "status": policy.get("status"),
        "legal_status": None,
        "reason": None,
        "effective_date": None,
        "investigation_status": None,
        "sample_collected_by": None,
        "testing_lab": None,
        "legal_reference": None,
        "additional_data": {"review_required": policy.get("review_required", True), "extraction_status": "EMPTY"},
        "source_record_id": make_source_record_id(folder, file.name, -1),
        "_folder": folder,
        "_source_file": str(file.relative_to(STRUCTURED_RAW)).replace("\\", "/"),
        "_normalized_at": utcnow_iso(),
        "_record_type": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-per-folder",
        type=int,
        default=0,
        help="If > 0, write only the first N documents per folder to events.sample.jsonl",
    )
    args = parser.parse_args()
    if args.sample_per_folder < 0:
        parser.error("--sample-per-folder must be >= 0")
    configs = load_all_configs()
    field_mapping = configs["field_mapping"]
    status_mapping = configs["status_mapping"]
    rows: list[dict] = []

    for folder, document_type in field_mapping["folder_name_aliases"].items():
        folder_dir = STRUCTURED_RAW / folder
        if not folder_dir.is_dir():
            continue
        type_config = field_mapping["by_document_type"].get(document_type, {})
        prose_policy = type_config.get("prose_policy") or {}
        files = iter_document_files(folder_dir)
        if args.sample_per_folder > 0:
            files = files[:args.sample_per_folder]
        for file in files:
            try:
                data = read_json(file)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[error] {file}: {exc}")
                continue
            records = data.get("records") or []
            if not records:
                # No source record exists to anchor provenance, so do not emit
                # a synthetic event with an unresolvable source_record_id.
                continue
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                canonical = record.get("canonical") or {}
                is_prose = "raw_text" in record and "canonical" not in record
                if record.get("prose") and not any(canonical.values()):
                    is_prose = True
                if is_prose:
                    rows.append(build_prose_event(folder, file, record, document_type, prose_policy, index))
                else:
                    rows.append(build_table_event(folder, file, record, document_type, type_config, status_mapping, index))

    output = OUTPUT_DIR / ("events.sample.jsonl" if args.sample_per_folder > 0 else "events.jsonl")
    count = write_jsonl(rows, output)
    print(f"[ok] wrote {count} events -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
