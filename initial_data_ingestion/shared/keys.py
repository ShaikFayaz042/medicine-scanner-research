"""
Deterministic Canonical Key Generators & Text Canonicalization
"""

import hashlib
import re
from typing import Optional, Dict, Any, List


def sha_key(*parts) -> str:
    """Generate SHA-256 hex string from piped normalized parts."""
    raw = "|".join(str(p or "").strip().lower() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical(text: Optional[str]) -> str:
    """
    Conservative text canonicalization.
    - Lowercase & strip
    - Remove common corporate suffixes (pvt, ltd, inc, corp, etc.)
    - Convert non-alphanumeric characters to space
    - Collapse multiple spaces
    """
    if not text:
        return ""

    text = str(text).lower().strip()
    text = re.sub(
        r'\b(pvt|private|ltd|limited|inc|corp|corporation|co|company)\b\.?',
        '',
        text
    )
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def organization_key(name: str, state: Optional[str] = None) -> str:
    """
    Generate organization key.
    If state is available, key incorporates state; otherwise uses unknown state prefix.
    """
    c_name = canonical(name)
    c_state = canonical(state)
    if c_state:
        return sha_key("ORG", c_name, c_state)
    return sha_key("ORG_UNKNOWN_STATE", c_name)


def product_key(
    name: str,
    strength: Optional[str] = None,
    dosage_form: Optional[str] = None,
    category: str = "DRUG",
    ingredient_signature: Optional[str] = None
) -> str:
    """
    Generate product key.
    Manufacturer is EXCLUDED from product identity.
    """
    return sha_key(
        "PROD",
        canonical(name),
        canonical(strength or ""),
        canonical(dosage_form or ""),
        canonical(category or "DRUG"),
        ingredient_signature or ""
    )


def ingredient_key(name: str) -> str:
    """Generate ingredient key from canonical active ingredient name."""
    return sha_key("ING", canonical(name))


def build_ingredient_signature(ingredient_keys: List[str]) -> str:
    """Generate sorted deterministic signature for multi-ingredient / FDC products."""
    sorted_keys = sorted(k for k in ingredient_keys if k)
    if not sorted_keys:
        return ""
    return sha_key("SIG", *sorted_keys)


def batch_key(
    product_key_val: Optional[str],
    organization_key_val: Optional[str],
    batch_number: str
) -> str:
    """
    Generate batch key.
    Requires product key, manufacturer organization key, and batch number.
    """
    return sha_key(
        "BATCH",
        product_key_val or "",
        organization_key_val or "",
        canonical(batch_number)
    )


def event_key(
    source_document_id: str,
    source_record_id: str,
    event_type: str,
    event_date: Optional[str] = None,
    event_subtype: Optional[str] = None
) -> str:
    """
    Generate event key.
    Deterministic key based on source document, record lineage ID, event type, date, and subtype.
    """
    return sha_key(
        "EVT",
        str(source_document_id or ""),
        str(source_record_id or ""),
        canonical(event_type),
        str(event_date or ""),
        canonical(event_subtype or "")
    )


def row_fingerprint(rec: Dict[str, Any]) -> str:
    """Generate row-level content fingerprint for duplicate/lineage tracking."""
    prod = rec.get("product_name") or rec.get("drug_name") or rec.get("title") or rec.get("name") or ""
    batch = rec.get("batch_number") or rec.get("batch_no") or rec.get("lot_no") or ""
    mfg = rec.get("manufactured_by") or rec.get("manufacturer") or rec.get("company_name") or ""
    reason = rec.get("reason") or rec.get("nsq_result") or rec.get("reason_for_nsq") or rec.get("description") or ""
    return sha_key(prod, batch, mfg, reason)


def generate_source_record_id(
    doc_id: Any,
    page_num: int = 1,
    table_num: int = 1,
    fingerprint: str = "",
    occurrence: int = 1
) -> str:
    """
    Format lineage source_record_id:
    <document_id>:P<page:02d>:T<table:02d>:<fingerprint[:8]>:<occurrence:02d>
    """
    fp_short = (fingerprint or "00000000")[:8]
    p = max(1, page_num or 1)
    t = max(1, table_num or 1)
    occ = max(1, occurrence or 1)
    return f"{doc_id}:P{p:02d}:T{t:02d}:{fp_short}:{occ:02d}"
