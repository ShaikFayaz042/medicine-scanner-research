"""
Extraction Module: Reads parsed JSON inputs, extracts header metadata and raw records,
assigns source_record_id lineage, handles key name variations & combined fields,
and extracts additional_data.
"""

import os
import re
import json
import hashlib
from typing import Dict, Any, List, Tuple
from .keys import row_fingerprint, generate_source_record_id


def compute_file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of file content."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_document_type(filename: str, json_data: Dict[str, Any]) -> str:
    """Infer default document_type from filename or header metadata."""
    fn_lower = filename.lower()
    doc_type = json_data.get("document_type") or json_data.get("doc_type")
    if doc_type:
        dt_str = str(doc_type).upper()
        if "NOC" in dt_str or "IMPORT" in dt_str or "FDC" in dt_str:
            return "NOC_IMPORT_FDC"
        if "BANNED" in dt_str:
            return "BANNED_DRUGS"
        elif "PVPI" in dt_str or "SAFETY ALERTS" in dt_str or "PHARMACOVIGILANCE" in dt_str:
            return "PVPI_ADR"
        elif "SPURIOUS" in dt_str:
            return "SPURIOUS"
        elif "NSQ" in dt_str and "CDSCO" in dt_str:
            return "NSQ_CDSCO"
        elif "NSQ" in dt_str or "QUALITY" in dt_str:
            return "NSQ_STATE"
        elif "DEVICE" in dt_str or "IVD" in dt_str:
            return "MEDICAL_DEVICE"
        elif "APPROVED" in dt_str:
            return "APPROVED_DRUGS"

    if "banned" in fn_lower:
        return "BANNED_DRUGS"
    elif "pvpi" in fn_lower or "adr" in fn_lower:
        return "PVPI_ADR"
    elif "spurious" in fn_lower:
        return "SPURIOUS"
    elif "cdsco" in fn_lower and "nsq" in fn_lower:
        return "NSQ_CDSCO"
    elif "nsq" in fn_lower:
        return "NSQ_STATE"
    elif "device" in fn_lower or "ivd" in fn_lower:
        return "MEDICAL_DEVICE"
    elif "approved" in fn_lower:
        return "APPROVED_DRUGS"
    elif "noc" in fn_lower or "import" in fn_lower or "fdc" in fn_lower:
        return "NOC_IMPORT_FDC"
    return "UNKNOWN"


def find_records_array(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Locate records array in JSON root."""
    if isinstance(data, list):
        return data

    for key in ["records", "prohibited_drugs", "adr_alerts", "rows", "data", "fdc_list", "items"]:
        if key in data and isinstance(data[key], list):
            return data[key]

    return [data]


def load_parsed_json(filepath: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Load JSON from filepath.
    Returns: (header_metadata, records_list)
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        data = json.load(f)

    filename = os.path.basename(filepath)
    file_hash = compute_file_hash(filepath)

    if isinstance(data, list):
        header_metadata = {
            "filename": filename,
            "source_organization": "CDSCO",
            "source_document_id": filename,
            "document_title": filename,
            "publication_date": None,
            "reporting_period": None,
            "source_url": filepath,
            "file_hash": file_hash,
            "document_type": detect_document_type(filename, {})
        }
        records = data
    elif isinstance(data, dict):
        doc_meta = data.get("document_metadata") or {}
        header_metadata = {
            "filename": filename,
            "source_organization": data.get("source_organization") or doc_meta.get("issuing_authority") or "CDSCO",
            "source_document_id": data.get("document_id") or data.get("source_document_id") or filename,
            "document_title": doc_meta.get("title") or data.get("document_title") or filename,
            "publication_date": doc_meta.get("date_of_issue") or data.get("publication_date"),
            "reporting_period": data.get("reporting_period"),
            "source_url": data.get("pdf_path") or filepath,
            "file_hash": file_hash,
            "document_type": detect_document_type(filename, data)
        }
        records = find_records_array(data)
    else:
        raise ValueError(f"Unsupported JSON root type in {filepath}: {type(data)}")

    return header_metadata, records


def extract_combined_batch_info(combined_str: str) -> Tuple[str, str, str, str]:
    """
    Parse combined batch/date/manufacturer string.
    Returns: (batch_no, mfg_date, exp_date, mfg_name)
    """
    if not combined_str:
        return "", "", "", ""

    batch_no, mfg_date, exp_date, mfg_name = "", "", "", ""

    # Match Batch Number
    b_match = re.search(r'(?:B\.?\s*No\.?|Batch\s*No\.?|Lot\s*No\.?)\s*:?\s*([A-Za-z0-9\-_/]+)', combined_str, re.IGNORECASE)
    if b_match:
        batch_no = b_match.group(1).strip()

    # Match Mfg Date
    m_match = re.search(r'(?:Mfg\.?\s*(?:dt|date)?|Manufactur(?:e|ing)\s*Date)\s*:?\s*([0-9]{2}/[0-9]{4}|[A-Za-z]{3}-?[0-9]{2,4}|[0-9]{4}-[0-9]{2})', combined_str, re.IGNORECASE)
    if m_match:
        mfg_date = m_match.group(1).strip()

    # Match Exp Date
    e_match = re.search(r'(?:Exp\.?\s*(?:dt|date)?|Expiry\s*Date)\s*:?\s*([0-9]{2}/[0-9]{4}|[A-Za-z]{3}-?[0-9]{2,4}|[0-9]{4}-[0-9]{2})', combined_str, re.IGNORECASE)
    if e_match:
        exp_date = e_match.group(1).strip()

    # Match Manufacturer Name
    mfg_match = re.search(r'(?:Mfd\.?\s*by|Manufactured\s*By|M/s\.?)\s*:?\s*(.+)', combined_str, re.IGNORECASE)
    if mfg_match:
        mfg_name = mfg_match.group(1).strip()

    return batch_no, mfg_date, exp_date, mfg_name


def clean_organization_name(value: str) -> str:
    """Remove common OCR/table spillover from an organization cell."""
    if not value:
        return ""
    cleaned = re.sub(r'^\s*(?:m/s\.?|m s\.?|messrs\.?)[\s:.-]*', '', str(value), flags=re.IGNORECASE)
    cleaned = re.split(r'\b(?:b\.?\s*no\.?|batch\s*no\.?|lot\s*no\.?|mfg\.?\s*(?:dt|date)?|exp(?:iry)?\.?\s*(?:dt|date)?|label claims?)\b', cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned = re.split(r'\s*[,;|]\s*(?:address|plot|road|village|district|state)\b', cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    return re.sub(r'\s+', ' ', cleaned).strip(' ,;:-')


def parse_formulation(product_name: str) -> Tuple[List[Dict[str, str]], str, str]:
    """Extract conservative ingredient, strength, and dosage-form fields."""
    text = str(product_name or '').strip()
    if not text:
        return [], '', ''
    dosage_match = re.search(r'\b(tablets?(?:\s+or\s+capsules?)?|capsules?(?:\s+or\s+tablets?)?|injections?|syrups?|suspensions?|solutions?|creams?|ointments?|powders?|drops?)\b', text, re.IGNORECASE)
    dosage_form = dosage_match.group(1).upper() if dosage_match else ''
    strength_matches = re.findall(r'\b\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?\s*(?:mg|mcg|g|ml|%|iu)\b', text, re.IGNORECASE)
    strength = ' + '.join(s.strip() for s in strength_matches)
    ingredient_text = re.sub(r'^\s*(?:fixed\s*dose\s*combination(?:s)?\s*of|fdc\s*of)\s+', '', text, flags=re.IGNORECASE)
    ingredient_text = re.sub(r'\b(?:tablets?|capsules?|injections?|syrups?|suspensions?|solutions?|creams?|ointments?|powders?|drops?)\b.*$', '', ingredient_text, flags=re.IGNORECASE).strip(' ,;:-')
    ingredient_text = re.sub(r'\b(?:hard\s+gelatin|film\s+coated|coated)\b', '', ingredient_text, flags=re.IGNORECASE)
    ingredient_text = re.sub(r'\b\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?\s*(?:mg|mcg|g|ml|%|iu)\b', '', ingredient_text, flags=re.IGNORECASE)
    parts = re.split(r'\s*(?:\+|\bwith\b|\band\b|,)\s*', ingredient_text, flags=re.IGNORECASE)
    parts = [re.sub(r'\s*\b(?:ip|bp|usp)\b\.?', '', p, flags=re.IGNORECASE).strip(' .') for p in parts]
    parts = [p for p in parts if p and not re.fullmatch(r'\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|%)?', p, flags=re.IGNORECASE)]
    is_combination = bool(re.search(r'\+|\bwith\b|\band\b', ingredient_text, re.IGNORECASE))
    if not is_combination and len(parts) != 1:
        parts = []
    ingredients = [{'name': p, 'strength': strength_matches[i] if i < len(strength_matches) else ''} for i, p in enumerate(parts)]
    return ingredients, dosage_form, strength


def get_field_by_candidates(rec: Dict[str, Any], candidate_keywords: List[str]) -> str:
    """
    Robust field extraction:
    1. Exact key match
    2. Case-insensitive exact key match
    3. Keyword contained in key name
    """
    rec_keys = list(rec.keys())

    # 1. Exact match
    for kw in candidate_keywords:
        if kw in rec and rec[kw] is not None:
            val = str(rec[kw]).strip()
            if val:
                return val

    # 2. Case-insensitive exact match
    rec_lower_map = {k.lower().strip(): k for k in rec_keys}
    for kw in candidate_keywords:
        kw_lower = kw.lower().strip()
        if kw_lower in rec_lower_map:
            actual_key = rec_lower_map[kw_lower]
            if rec[actual_key] is not None:
                val = str(rec[actual_key]).strip()
                if val:
                    return val

    # 3. Keyword contained in key name
    for k in rec_keys:
        if rec[k] is None or not str(rec[k]).strip():
            continue
        k_clean = k.lower().replace("_", " ").replace("-", " ")
        for kw in candidate_keywords:
            kw_clean = kw.lower().replace("_", " ").replace("-", " ")
            if kw_clean in k_clean:
                return str(rec[k]).strip()

    # 4. Normalized alphanumeric match (stripping spaces/punct for OCR typos like "Dr ug" or "Dru g")
    for k in rec_keys:
        if rec[k] is None or not str(rec[k]).strip():
            continue
        k_alpha = re.sub(r'[^a-z0-9]', '', k.lower())
        if not k_alpha:
            continue
        for kw in candidate_keywords:
            kw_alpha = re.sub(r'[^a-z0-9]', '', kw.lower())
            if kw_alpha and (kw_alpha in k_alpha or k_alpha in kw_alpha):
                return str(rec[k]).strip()

    return ""


def extract_record_lineage(
    doc_id: Any,
    records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Iterate over raw records and assign source_record_id & normalized fields."""
    fingerprint_counters: Dict[str, int] = {}
    extracted_records: List[Dict[str, Any]] = []

    product_key_candidates = [
        "suspected drugs", "suspected drug", "suspected_drug", "suspected_drugs",
        "product_name", "drug_name", "drugs_name", "drug name", "drugs name",
        "name of drugs", "name of drug", "name of product", "product name",
        "brand_name", "brand name", "name of fdc", "name of vaccine", "vaccine name",
        "name of devices", "material name", "name of the drug", "name of the drugs"
    ]

    batch_key_candidates = [
        "batch_number", "batch_no", "batch no", "batch number", "lot_no", "lot no",
        "batch", "lot", "affected batches", "b no", "model no", "model number"
    ]

    mfg_key_candidates = [
        "manufactured_by", "manufactured by", "manufacture d by", "manufacturer",
        "manufacturer name", "company_name", "name of company", "name of the firm",
        "mfg_by", "importer", "applicant", "name of the importer"
    ]

    reason_key_candidates = [
        "reason for failure", "reasons for failure", "reason for nsq", "nsq result",
        "sub-standard in", "reason for recall", "reason", "description",
        "adverse drug reactions", "indications", "intended use", "result"
    ]

    reporting_org_candidates = [
        "reporting_organization", "reported_by", "reported by", "reporting source",
        "reporting by lab/state", "drawn by", "drawn by from", "from", "lab_name",
        "from name of laboratory", "testing laboratory", "testing facility", "declared by"
    ]

    combined_batch_candidates = [
        "batch no/date of manufacture/date of expiry/manufactured by",
        "batch no/ date of manufacture/ date of expiry/ manufactured by",
        "batch no., mfg date, exp date, manufactured by",
        "b no d/m d/e name of the mfg & address",
        "batch details"
    ]

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            continue

        fp = row_fingerprint(rec)
        occ = fingerprint_counters.get(fp, 0) + 1
        fingerprint_counters[fp] = occ

        page_num = int(rec.get("page_number") or rec.get("page") or 1)
        table_num = int(rec.get("table_number") or rec.get("table") or 1)
        src_loc = rec.get("source_location") or f"Page {page_num}, Row {idx}"

        src_rec_id = generate_source_record_id(
            doc_id=doc_id,
            page_num=page_num,
            table_num=table_num,
            fingerprint=fp,
            occurrence=occ
        )

        product_name = get_field_by_candidates(rec, product_key_candidates)
        batch_number = get_field_by_candidates(rec, batch_key_candidates)
        manufacturer = clean_organization_name(get_field_by_candidates(rec, mfg_key_candidates))
        mfg_date = get_field_by_candidates(rec, ["manufacturing date", "mfg date", "date of manufacture", "manufacturing_date", "mfg_date"])
        exp_date = get_field_by_candidates(rec, ["expiry date", "exp date", "date of expiry", "expiry_date", "exp_date"])

        # Check combined batch field if batch or manufacturer is missing
        combined_val = get_field_by_candidates(rec, combined_batch_candidates)
        if combined_val:
            c_batch, c_mfg_date, c_exp_date, c_mfg = extract_combined_batch_info(combined_val)
            if not batch_number and c_batch:
                batch_number = c_batch
            if not mfg_date and c_mfg_date:
                mfg_date = c_mfg_date
            if not exp_date and c_exp_date:
                exp_date = c_exp_date
            if not manufacturer and c_mfg:
                manufacturer = c_mfg

        # Fallback & overflow cleanup for drug name in prohibited_drugs / banned list notifications
        notification_val = get_field_by_candidates(rec, ["notification_no_and_date", "Notification No & Date", "Notification No. & Date", "Notification"])
        if notification_val:
            notif_match = re.search(r'\b(?:G\.?S\.?R\.?\s*(?:NO\.?|No\.?|NO)?|S\.O\.?\s*\d+|S\.O\.?|SO)\b', notification_val, flags=re.IGNORECASE)
            if notif_match and notif_match.start() > 0:
                prefix_clean = re.sub(r'^\d+[\.\)]\s*', '', notification_val[:notif_match.start()].strip()).strip()
                if prefix_clean:
                    if not product_name:
                        product_name = prefix_clean
                    elif not product_name.endswith(prefix_clean) and prefix_clean not in product_name:
                        product_name = f"{product_name} {prefix_clean}".strip()
            elif not product_name:
                parts = re.split(r'\b(?:S\.O\.|G\.S\.R\.|GSR|S\.O|SO|Dated)\b', notification_val, flags=re.IGNORECASE)
                candidate_prod = parts[0].strip()
                if len(candidate_prod) > 2 and not candidate_prod.isdigit():
                    product_name = candidate_prod

        reason = get_field_by_candidates(rec, reason_key_candidates)
        reporting_org = get_field_by_candidates(rec, reporting_org_candidates)
        state_val = rec.get("state") or rec.get("state_name") or ""
        country_val = rec.get("country") or "India"

        additional_data = {}
        for k, v in rec.items():
            if v is not None and str(v).strip() != "":
                additional_data[k] = v

        ingredients, parsed_dosage_form, parsed_strength = parse_formulation(product_name)
        extracted_item = {
            "source_record_id": src_rec_id,
            "page_number": page_num,
            "source_location": src_loc,
            "extraction_method": rec.get("extraction_method") or "TEXT",
            "source_text": rec.get("source_text") or json.dumps(rec, ensure_ascii=False),
            "raw_json": rec,
            
            "product_name": product_name,
            "dosage_form": rec.get("dosage_form") or parsed_dosage_form,
            "strength": rec.get("strength") or parsed_strength,
            "ingredients": ingredients,
            "product_category": rec.get("product_category") or "DRUG",
            
            "batch_number": batch_number,
            "manufacturing_date": mfg_date or None,
            "expiry_date": exp_date or None,
            
            "manufacturer_name": manufacturer,
            "manufacturer_state": state_val,
            "reporting_organization_name": reporting_org,
            "reporting_organization_state": state_val,
            "country": country_val,
            
            "event_type": rec.get("event_type"),
            "event_date": rec.get("event_date") or rec.get("date"),
            "scope": rec.get("scope"),
            "status": rec.get("status") or ("NSQ" if reason else ""),
            "reason": reason,
            "action": rec.get("action") or "",
            "legal_status": rec.get("legal_status") or rec.get("notification_no_and_date") or rec.get("Notification No & Date") or "",
            "additional_data": additional_data
        }

        extracted_records.append(extracted_item)

    return extracted_records
