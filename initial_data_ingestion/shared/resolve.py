"""
Entity Resolution Module: Validates taxonomy, resolves entity keys,
applies missing data rules, and determines normalization status & review reasons.
"""

from typing import Dict, Any, List, Tuple, Optional
from .keys import (
    organization_key,
    product_key,
    batch_key,
    event_key,
    canonical,
    ingredient_key,
    build_ingredient_signature
)

# Taxonomy Vocabularies
ALLOWED_EVENT_TYPES = {
    "BANNED", "PROHIBITED", "NSQ", "SPURIOUS", "ADR", "RECALL",
    "APPROVAL", "NOC", "IMPORT_PERMISSION", "SAFETY_ADVISORY",
    "SUSPENSION", "WITHDRAWAL", "UNDER_INVESTIGATION", "OTHER"
}

ALLOWED_SCOPES = {
    "BATCH", "PRODUCT", "INGREDIENT", "COMBINATION", "DOCUMENT"
}

ALLOWED_PRODUCT_CATEGORIES = {
    "DRUG", "MEDICAL_DEVICE", "IVD_KIT", "VACCINE", "FDC", "COSMETIC"
}

ALLOWED_DOCUMENT_TYPES = {
    "BANNED_DRUGS", "PVPI_ADR", "NSQ_STATE", "SPURIOUS",
    "NSQ_CDSCO", "LEGACY_CDSCO", "MEDICAL_DEVICE",
    "APPROVED_DRUGS", "NOC_IMPORT_FDC", "MIXED_ALERT", "UNKNOWN"
}

ALLOWED_REVIEW_REASONS = {
    "missing_product_name",
    "missing_batch_number",
    "nsq_without_batch",
    "ambiguous_organization",
    "ambiguous_product",
    "invalid_date_format",
    "unparseable_row",
    "duplicate_fingerprint",
    "excluded_document_type"
}


def infer_event_type(doc_type: str, rec: Dict[str, Any]) -> str:
    """Infer regulatory event_type if missing."""
    ev_type = rec.get("event_type")
    if ev_type and str(ev_type).upper() in ALLOWED_EVENT_TYPES:
        return str(ev_type).upper()
    aliases = {
        "MARKETING_APPROVAL": "APPROVAL",
        "NOC_GRANTED": "NOC",
        "SAFETY_ALERT": "SAFETY_ADVISORY",
        "UNDER_REVIEW": "UNDER_INVESTIGATION",
        "QUALITY_ALERT": "NSQ",
    }
    if ev_type and str(ev_type).upper() in aliases:
        return aliases[str(ev_type).upper()]

    status_str = str(rec.get("status") or "").upper()
    if "SPURIOUS" in status_str:
        return "SPURIOUS"
    elif "NSQ" in status_str:
        return "NSQ"
    elif "PROHIBITED" in status_str or "BANNED" in status_str:
        return "BANNED"
    elif "APPROVED" in status_str:
        return "APPROVAL"

    dt_upper = str(doc_type or "").upper()
    if dt_upper in ("NSQ_STATE", "NSQ_CDSCO", "LEGACY_CDSCO"):
        return "NSQ"
    elif dt_upper == "BANNED_DRUGS":
        return "BANNED"
    elif dt_upper == "PVPI_ADR":
        return "ADR"
    elif dt_upper == "SPURIOUS":
        return "SPURIOUS"
    elif dt_upper == "APPROVED_DRUGS":
        return "APPROVAL"
    elif dt_upper == "MEDICAL_DEVICE":
        return "RECALL"
    elif dt_upper == "NOC_IMPORT_FDC":
        return "NOC"

    return "NSQ"


def infer_scope(rec: Dict[str, Any], doc_type: str = "") -> str:
    """Infer scope if missing or invalid."""
    scope_val = rec.get("scope")
    if scope_val and str(scope_val).upper() in ALLOWED_SCOPES:
        return str(scope_val).upper()

    event_type = str(rec.get("event_type") or "").upper()
    if event_type == "NSQ" or str(doc_type).upper() in {"NSQ_STATE", "NSQ_CDSCO", "LEGACY_CDSCO"}:
        return "BATCH"
    if rec.get("batch_number"):
        return "BATCH"
    elif rec.get("product_name"):
        return "PRODUCT"
    return "DOCUMENT"


def infer_action(event_type: str, value: str | None) -> tuple[str, str]:
    """Return an explicit action or a conservative event-type action fallback."""
    if value and value.strip():
        return value.strip(), "EXTRACTED"
    actions = {
        "BANNED": "BAN",
        "PROHIBITED": "PROHIBITION",
        "RECALL": "RECALL",
        "SUSPENSION": "SUSPENSION",
        "WITHDRAWAL": "WITHDRAWAL",
        "APPROVAL": "APPROVAL",
        "NOC": "IMPORT_PERMISSION",
        "ADR": "SAFETY_ALERT",
        "NSQ": "QUALITY_ALERT",
        "SPURIOUS": "QUALITY_ALERT",
    }
    action = actions.get(event_type, "")
    return action, "INFERRED" if action else "MISSING"


def resolve_record(
    doc_id: Any,
    doc_type: str,
    extracted_rec: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Resolve single extracted record into canonical keys, validate against taxonomies,
    and assign normalization_status and review_reason.
    """
    prod_name = extracted_rec.get("product_name") or ""
    batch_no = extracted_rec.get("batch_number") or ""
    mfg_name = extracted_rec.get("manufacturer_name") or ""
    mfg_state = extracted_rec.get("manufacturer_state") or None
    rep_name = extracted_rec.get("reporting_organization_name") or ""
    rep_state = extracted_rec.get("reporting_organization_state") or None
    role_names = {
        "MANUFACTURER": (mfg_name, mfg_state),
        "IMPORTER": (extracted_rec.get("importer_name") or "", mfg_state),
        "APPLICANT": (extracted_rec.get("applicant_name") or "", mfg_state),
        "MARKETING_AUTHORIZATION_HOLDER": (
            extracted_rec.get("marketing_authorization_holder_name") or "",
            mfg_state,
        ),
    }
    
    category = str(extracted_rec.get("product_category") or "DRUG").upper()
    if category not in ALLOWED_PRODUCT_CATEGORIES:
        category = "DRUG"

    ev_type = infer_event_type(doc_type, extracted_rec)
    scope_val = infer_scope(extracted_rec, doc_type)
    action, action_source = infer_action(ev_type, extracted_rec.get("action"))

    parsed_ingredients = extracted_rec.get("ingredients") or []
    ingredient_keys = [ingredient_key(item["name"]) for item in parsed_ingredients if item.get("name")]
    ingredient_signature = build_ingredient_signature(ingredient_keys)
    if len(ingredient_keys) > 1 and category == "DRUG":
        category = "FDC"

    # Key Resolution
    mfg_org_key = organization_key(mfg_name, mfg_state) if mfg_name else None
    rep_org_key = organization_key(rep_name, rep_state) if rep_name else None

    prod_key = product_key(
        name=prod_name,
        strength=extracted_rec.get("strength"),
        dosage_form=extracted_rec.get("dosage_form"),
        category=category,
        ingredient_signature=ingredient_signature
    ) if prod_name else None

    btch_key = batch_key(
        product_key_val=prod_key,
        organization_key_val=mfg_org_key,
        batch_number=batch_no
    ) if (prod_key and batch_no) else None

    evt_key = event_key(
        source_document_id=str(doc_id),
        source_record_id=extracted_rec["source_record_id"],
        event_type=ev_type,
        event_date=extracted_rec.get("event_date")
    )

    # Check Excluded Document Types (Doc 9, Doc 10, Doc 12, Doc 13, Doc 14, Doc 15, Doc 16)
    EXCLUDED_PREFIXES = ("Doc 9:", "Doc 10:", "Doc 12:", "Doc 13:", "Doc 14:", "Doc 15:", "Doc 16:")
    is_excluded_doc = str(doc_type or "").startswith(EXCLUDED_PREFIXES)

    # Status & Review Reason Decision Logic
    norm_status = "COMPLETE"
    review_reason = None

    if is_excluded_doc:
        norm_status = "IGNORED"
        review_reason = "excluded_document_type"
    elif not prod_name:
        norm_status = "NEEDS_REVIEW"
        review_reason = "missing_product_name"
    elif scope_val == "BATCH" and not batch_no:
        norm_status = "NEEDS_REVIEW"
        review_reason = "missing_batch_number" if ev_type != "NSQ" else "nsq_without_batch"

    resolved = {
        "source_record_id": extracted_rec["source_record_id"],
        "source_document_id": str(doc_id),
        
        # Entity Keys
        "product_key": prod_key,
        "batch_key": btch_key,
        "manufacturer_organization_key": mfg_org_key,
        "reporting_organization_key": rep_org_key,
        "organization_roles": {
            role: organization_key(name, state) if name else None
            for role, (name, state) in role_names.items()
        },
        "organization_role_details": {
            role: {
                "key": organization_key(name, state) if name else None,
                "name": name,
                "address": extracted_rec.get(
                    {
                        "IMPORTER": "importer_address",
                        "APPLICANT": "applicant_address",
                        "MARKETING_AUTHORIZATION_HOLDER": "marketing_authorization_holder_address",
                    }.get(role, "manufacturer_address"),
                    "",
                ) or "",
                "state": state or "",
            }
            for role, (name, state) in role_names.items()
        },
        "event_key": evt_key,
        
        # Canonical / Normalized Data
        "product_name": prod_name,
        "brand_name": extracted_rec.get("brand_name") or "",
        "normalized_product_name": canonical(prod_name),
        "product_category": category,
        "ingredients": [
            {**item, "ingredient_key": key}
            for item, key in zip(parsed_ingredients, ingredient_keys)
        ],
        "dosage_form": extracted_rec.get("dosage_form") or "",
        "strength": extracted_rec.get("strength") or "",
        
        "batch_number": batch_no,
        "manufacturing_date": extracted_rec.get("manufacturing_date"),
        "expiry_date": extracted_rec.get("expiry_date"),
        
        "manufacturer_name": mfg_name,
        "manufacturer_address": extracted_rec.get("manufacturer_address") or "",
        "normalized_manufacturer_name": canonical(mfg_name),
        "manufacturer_state": mfg_state,
        "importer_name": extracted_rec.get("importer_name") or "",
        "applicant_name": extracted_rec.get("applicant_name") or "",
        "marketing_authorization_holder_name": extracted_rec.get("marketing_authorization_holder_name") or "",
        "country": extracted_rec.get("country") or "India",
        
        "reporting_organization_name": rep_name,
        "reporting_organization_address": extracted_rec.get("reporting_organization_address") or "",
        "normalized_reporting_organization_name": canonical(rep_name),
        "reporting_organization_state": rep_state or "",
        
        "event_type": ev_type,
        "event_date": extracted_rec.get("event_date"),
        "scope": scope_val,
        "status": extracted_rec.get("status") or ev_type,
        "reason": extracted_rec.get("reason"),
        "action": action,
        "legal_status": extracted_rec.get("legal_status"),
        "additional_data": {
            **(extracted_rec.get("additional_data") or {}),
            "_pipeline": {
                "event_type_source": extracted_rec.get("event_type_source", "EXTRACTED" if extracted_rec.get("event_type") else "INFERRED"),
                "event_date_source": extracted_rec.get("event_date_source", "EXTRACTED" if extracted_rec.get("event_date") else "MISSING"),
                "action_source": action_source,
            },
        },
        
        # Lineage details
        "page_number": extracted_rec.get("page_number", 1),
        "source_location": extracted_rec.get("source_location", "Page 1"),
        "extraction_method": extracted_rec.get("extraction_method", "TEXT"),
        "source_text": extracted_rec.get("source_text", ""),
        "raw_json": extracted_rec.get("raw_json", {}),
        
        # Staging & Reconciliation Flags
        "normalization_status": norm_status,
        "validation_status": "PENDING",
        "review_reason": review_reason,
        "error_message": None
    }

    return resolved
