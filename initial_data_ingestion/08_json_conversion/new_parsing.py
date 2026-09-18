import argparse
import os
import json
import re
import hashlib
from collections import defaultdict
from pathlib import Path

from special_alerts_parser import process_special_alerts

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = REPO_ROOT / "initial_data_ingestion"
RAW_DIR = BASE_DIR / "07_raw_extraction_output"
OUTPUT_DIR = BASE_DIR / "08_json_conversion" / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SPECIAL_FILE_IDS = ["3145", "3146", "3147", "3246", "3253", "11255", "2058", "4540", "7571", "7770", "7881", "banneddrugs", "514_Notice", "List-of-Drugs-Safety-Alerts"]

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
    "Doc 16": ("Doc 16: Gazette Notification Drug Prohibition Extraordinaries", "Banned Drugs")
}

def clean_cell(c):
    return re.sub(r'\s+', ' ', str(c).replace('\n', ' ')).strip()

def sanitize_header_key(h):
    c = clean_cell(h)
    c = re.sub(r'[\.\s]+\b', ' ', c)
    c = re.sub(r'[^a-zA-Z0-9\s/_\-&]', '', c).strip()
    return c if c else "Column"

def is_summary_table(rows):
    if not rows or len(rows) <= 6:
        table_text = " ".join([" ".join([clean_cell(c) for c in r if clean_cell(c)]) for r in rows]).lower()
        if "total number of samples" in table_text or "samples declared" in table_text:
            return True
    return False

def is_noise_row(row):
    row_str = " ".join([clean_cell(c) for c in row if str(c).strip()]).lower()
    if not row_str:
        return True
    if re.search(r'^page\s+\d+\s+of\s+\d+', row_str) or re.search(r'^\d+\s+of\s+\d+', row_str):
        return True
    if ("name of product" in row_str or "product/drug name" in row_str or "batch no" in row_str) and ("manufacturing date" in row_str or "expiry date" in row_str or "nsq result" in row_str):
        return True
    if "this report is issued" in row_str or "confidential" in row_str or "cdsco website" in row_str:
        return True
    return False

def is_valid_anchor(first_cell):
    cell_str = clean_cell(first_cell)
    if re.match(r'^\d+[\.\)]?$', cell_str):
        return True
    return False

def find_real_header_row(rows):
    for idx, r in enumerate(rows[:15]):
        non_empty = [clean_cell(c) for c in r if clean_cell(c)]
        r_str = " ".join(non_empty).lower()
        if len(non_empty) >= 3 and any(kw in r_str for kw in ["s. no", "s no", "s.no", "sl no", "sr. no", "s n o", "s n", "name of drug", "product", "batch", "manufactured by", "reason for failure"]):
            return idx, [sanitize_header_key(c) for c in r if clean_cell(c)]
    for idx, r in enumerate(rows[:5]):
        non_empty = [clean_cell(c) for c in r if clean_cell(c)]
        if len(non_empty) >= 2:
            return idx, [sanitize_header_key(c) for c in r if clean_cell(c)]
    first_r = rows[0] if rows else []
    return 0, [sanitize_header_key(c) for c in first_r if clean_cell(c)]

def normalize_alert_records(records):
    normalized_list = []
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
        "remarks": ["remarks", "remark", "response of original manufacturer"]
    }
    
    for r in records:
        std_rec = {
            "S No": "",
            "Name of Drugs/medical device/cosmetics": "",
            "Batch No": "",
            "Date of Manufacture": "",
            "Date of Expiry": "",
            "Manufactured By": "",
            "Reason for failure": "",
            "Drawn By": "",
            "From": "",
            "Remarks": ""
        }
        
        for k, v in r.items():
            k_clean = str(k).lower().strip()
            val_str = str(v).strip()
            
            matched = False
            for std_key, aliases in key_map.items():
                if any(alias in k_clean for alias in aliases):
                    if std_key == "s_no": std_rec["S No"] = val_str
                    elif std_key == "product_name": std_rec["Name of Drugs/medical device/cosmetics"] = val_str
                    elif std_key == "batch_no": std_rec["Batch No"] = val_str
                    elif std_key == "mfg_date": std_rec["Date of Manufacture"] = val_str
                    elif std_key == "exp_date": std_rec["Date of Expiry"] = val_str
                    elif std_key == "mfg_by": std_rec["Manufactured By"] = val_str
                    elif std_key == "reason": std_rec["Reason for failure"] = val_str
                    elif std_key == "drawn_by": std_rec["Drawn By"] = val_str
                    elif std_key == "from_lab": std_rec["From"] = val_str
                    elif std_key == "remarks": std_rec["Remarks"] = val_str
                    matched = True
                    break
                    
            if not matched and k.startswith("Column_"):
                col_num = int(k.split("_")[1]) if k.split("_")[1].isdigit() else 0
                if col_num == 1: std_rec["S No"] = val_str
                elif col_num == 2: std_rec["Name of Drugs/medical device/cosmetics"] = val_str
                elif col_num == 3: std_rec["Batch No"] = val_str
                elif col_num == 4: std_rec["Date of Manufacture"] = val_str
                elif col_num == 5: std_rec["Date of Expiry"] = val_str
                elif col_num == 6: std_rec["Manufactured By"] = val_str
                elif col_num == 7: std_rec["Reason for failure"] = val_str
                elif col_num == 8: std_rec["Drawn By"] = val_str
                elif col_num == 9: std_rec["From"] = val_str
                elif col_num == 10: std_rec["Remarks"] = val_str

        normalized_list.append(std_rec)
        
    return normalized_list

def classify_document(subfolder, filename, headers_list, sample_text):
    text_sample = (filename + " " + sample_text).lower()
    header_str = " ".join([" ".join([clean_cell(c) for c in h]) for h in headers_list]).lower() if headers_list else ""
    
    if "spurious" in header_str or "spurious" in text_sample or "manufacturer details" in header_str:
        return DOCUMENT_TYPES["Doc 4"]
    elif "suspected drugs" in header_str or "adverse drug reaction" in header_str or "pvpi" in text_sample:
        return DOCUMENT_TYPES["Doc 2"]
    elif ("drugs name" in header_str or "prohibited" in text_sample or "banned" in text_sample) and ("notification" in text_sample or "26a" in text_sample):
        return DOCUMENT_TYPES["Doc 1"]
    elif "nsq result" in header_str and ("reporting by lab" in header_str or "state lab" in header_str or "reporting source" in header_str):
        return DOCUMENT_TYPES["Doc 3"]
    elif "cdsco laboratory" in header_str or "reported by cdsco" in header_str:
        return DOCUMENT_TYPES["Doc 5"]
    elif "drawn by" in header_str or "reason for failure" in header_str:
        return DOCUMENT_TYPES["Doc 6"]
    elif "device" in text_sample or "catheter" in text_sample or "implant" in text_sample:
        return DOCUMENT_TYPES["Doc 7"]
    elif "approved" in text_sample and "indication" in text_sample:
        return DOCUMENT_TYPES["Doc 8"]
    elif "fdc" in text_sample and ("irrational" in text_sample or "prohibition" in text_sample):
        return DOCUMENT_TYPES["Doc 9"]
    elif "sec" in text_sample or "tentative schedule" in text_sample:
        return DOCUMENT_TYPES["Doc 10"]
    elif "noc" in text_sample or "import" in text_sample:
        return DOCUMENT_TYPES["Doc 11"]
    elif "vaccine" in text_sample and "inspection" in text_sample:
        return DOCUMENT_TYPES["Doc 12"]
    elif "pcr" in text_sample or "testing kit" in text_sample:
        return DOCUMENT_TYPES["Doc 13"]
    elif "laboratory" in text_sample and "ivd" in text_sample:
        return DOCUMENT_TYPES["Doc 14"]
    elif "fee" in text_sample or "faq" in text_sample:
        return DOCUMENT_TYPES["Doc 15"]
    elif "g.s.r" in text_sample or "s.o." in text_sample:
        return DOCUMENT_TYPES["Doc 16"]
    
    return ("General Regulatory Document", "Administrative")

def process_table_rows(raw_rows, clean_headers, current_record=None):
    records = []
    
    for row in raw_rows:
        if is_noise_row(row):
            continue
            
        row_cells = [clean_cell(c) for c in row]
        row_str = " ".join(row_cells).strip()
        first_cell = row_cells[0] if len(row_cells) > 0 else ""
        second_cell = row_cells[1] if len(row_cells) > 1 else ""
        
        remark_match = re.search(r'^(remark|remarks)\s*:\s*(.*)', first_cell, re.IGNORECASE) or \
                       re.search(r'^(remark|remarks)\s*:\s*(.*)', second_cell, re.IGNORECASE) or \
                       re.search(r'^(remark|remarks)\s*:\s*(.*)', row_str, re.IGNORECASE)
                       
        if remark_match and current_record is not None and not is_valid_anchor(first_cell):
            remark_text = remark_match.group(2).strip()
            if not remark_text and len(row_cells) > 1:
                remark_text = " ".join([c for c in row_cells if c and not c.lower().startswith("remark")]).strip()
            current_record["Remark"] = remark_text
            continue
            
        if is_valid_anchor(first_cell):
            record_dict = {}
            for idx, val in enumerate(row_cells):
                col_name = clean_headers[idx] if idx < len(clean_headers) else f"Column_{idx+1}"
                record_dict[col_name] = val
            records.append(record_dict)
            current_record = record_dict
        else:
            if current_record is not None:
                for idx, val in enumerate(row_cells):
                    if val:
                        col_name = clean_headers[idx] if idx < len(clean_headers) else f"Column_{idx+1}"
                        if col_name in current_record:
                            current_record[col_name] = (current_record[col_name] + " " + val).strip()
                        else:
                            current_record[col_name] = val
                            
    has_remark_added = any("Remark" in r for r in records)
    if has_remark_added and "Remark" not in clean_headers and "Remarks" not in clean_headers:
        clean_headers.append("Remark")
        
    return clean_headers, records, current_record

def process_table_document(subfolder, filename, json_path, txt_path):
    if any(sp_id in filename for sp_id in SPECIAL_FILE_IDS):
        return process_special_alerts(subfolder, filename, json_path, txt_path)
        
    doc_id = "doc_" + hashlib.sha256((subfolder + "_" + filename).encode('utf-8')).hexdigest()[:10]
    pdf_name = filename + ".pdf" if not filename.endswith(".pdf") else filename
    pdf_path = f"01_downloads/{subfolder}/{pdf_name}"
    
    all_records = []
    all_exact_columns = []
    all_pages = set()
    sample_text = ""
    headers_found = []
    master_headers = None
    current_record = None
    
    if txt_path and os.path.exists(txt_path):
        try:
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as tf:
                sample_text = " ".join([l.strip() for l in tf.readlines()[:10]])
        except Exception:
            pass
            
    with open(json_path, "r", encoding="utf-8", errors="ignore") as jf:
        raw_data = json.load(jf)
        
    if not isinstance(raw_data, list):
        raw_data = [raw_data]
        
    for tbl in raw_data:
        if not isinstance(tbl, dict) or "rows" not in tbl:
            continue
            
        page = tbl.get("page", 1)
        raw_rows = tbl.get("rows", [])
        
        if not raw_rows or is_summary_table(raw_rows):
            continue
            
        all_pages.add(page)
            
        if master_headers is None:
            header_idx, clean_headers = find_real_header_row(raw_rows)
            master_headers = clean_headers
            headers_found.append(clean_headers)
            data_rows = raw_rows[header_idx + 1:]
        else:
            first_row_str = " ".join([clean_cell(c) for c in raw_rows[0]]).lower()
            if any(kw in first_row_str for kw in ["s no", "s n", "batch no", "product", "manufactured by", "name of drug"]):
                data_rows = raw_rows[1:]
            else:
                data_rows = raw_rows
                
        master_headers, records, current_record = process_table_rows(data_rows, master_headers, current_record)
        
        if not all_exact_columns and master_headers:
            all_exact_columns = master_headers
        elif "Remark" in master_headers and "Remark" not in all_exact_columns and "Remarks" not in all_exact_columns:
            all_exact_columns.append("Remark")
            
        all_records.extend(records)
        
    doc_type, group_type = classify_document(subfolder, filename, headers_found, sample_text)
    
    # Fallback to special alert parser if total_rows == 0 and txt_path exists
    if len(all_records) == 0 and txt_path and os.path.exists(txt_path):
        return process_special_alerts(subfolder, filename, json_path, txt_path)
        
    # Standardize Monthly Drug Alert record structures to 10-column schema
    if subfolder in ["alerts", "nsq_json"] and doc_type in [DOCUMENT_TYPES["Doc 3"], DOCUMENT_TYPES["Doc 4"], DOCUMENT_TYPES["Doc 5"], DOCUMENT_TYPES["Doc 6"]]:
        all_records = normalize_alert_records(all_records)
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
            "Remarks"
        ]

    structured_json = {
        "document_id": doc_id,
        "source_file": pdf_name,
        "pdf_path": pdf_path,
        "source_category": subfolder,
        "document_type": doc_type,
        "group_type": group_type,
        "pages": sorted(list(all_pages)),
        "total_rows": len(all_records),
        "exact_columns": all_exact_columns,
        "records": all_records
    }
    
    return structured_json

def process_nsq_json_file(file_path, filename):
    subfolder = "nsq_json"
    doc_id = "doc_" + hashlib.sha256((subfolder + "_" + filename).encode('utf-8')).hexdigest()[:10]
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        records = json.load(f)
        
    all_records = []
    for idx, rec in enumerate(records, 1):
        if "spurious" in filename:
            rec_dict = {
                "S.No": str(idx),
                "Name of Product": rec.get("product_name_from_dtl"),
                "Batch No": rec.get("str_batch_no"),
                "Manufacturing Dates": f"Manufacturing Date: {rec.get('dt_manufacturing_date')} Expiry Date: {rec.get('dt_expiry_date')}",
                "Manufacturer Details": f"Manufacturer Name: {rec.get('str_manufactured_by')} Manufactured By: {rec.get('str_manufactured_by')}",
                "Reporting Source": rec.get("str_reporting_source"),
                "Reporting by Lab/State": rec.get("str_reported_by_lab_or_state"),
                "Reporting Month & Year": rec.get("dt_reporting_month_year"),
                "Remarks": f"{rec.get('str_nsq_remarks', '')} {rec.get('str_firm_reply', '')}".strip()
            }
        else:
            rec_dict = {
                "S.No": str(idx),
                "Name of Product": rec.get("str_product_name"),
                "Batch No": rec.get("str_batch_no"),
                "Manufacturing Date": rec.get("dt_manufacturing_date"),
                "Expiry Date": rec.get("dt_expiry_date"),
                "Manufactured By": rec.get("str_manufactured_by"),
                "NSQ Result": rec.get("str_nsq_result"),
                "Reporting Source": rec.get("str_reporting_source"),
                "Reporting by Lab/State": rec.get("str_reported_by_lab_or_state"),
                "Reporting Month & Year": rec.get("dt_reporting_month_year")
            }
        all_records.append(rec_dict)
        
    doc_type = "Doc 4: Spurious Drugs" if "spurious" in filename else "Doc 3: NSQ Drugs"
    exact_cols = list(all_records[0].keys()) if all_records else []
    
    return {
        "document_id": doc_id,
        "source_file": filename,
        "pdf_path": f"07_raw_extraction_output/nsq_json/{filename}",
        "source_category": subfolder,
        "document_type": doc_type,
        "group_type": "Quality Failures",
        "pages": [1],
        "total_rows": len(all_records),
        "exact_columns": exact_cols,
        "records": all_records
    }

def run_parsing_pipeline():
    print("=== STARTING PARSING PIPELINE WITH SPECIAL ALERTS PARSER INTEGRATION ===")
    processed_count = 0
    manifest = []
    
    for root, dirs, files in os.walk(RAW_DIR):
        rel_sub = os.path.relpath(root, RAW_DIR)
        if rel_sub == ".":
            continue
            
        out_subfolder = os.path.join(OUTPUT_DIR, rel_sub)
        os.makedirs(out_subfolder, exist_ok=True)
        
        if rel_sub == "nsq_json":
            for f in files:
                if f.endswith(".json") and f != "_manifest.json":
                    fpath = os.path.join(root, f)
                    parsed_doc = process_nsq_json_file(fpath, f)
                    out_path = os.path.join(out_subfolder, f)
                    with open(out_path, "w", encoding="utf-8") as out_f:
                        json.dump(parsed_doc, out_f, indent=2)
                    processed_count += 1
                    manifest.append({
                        "document_id": parsed_doc["document_id"],
                        "filename": f,
                        "subfolder": rel_sub,
                        "document_type": parsed_doc["document_type"],
                        "total_rows": parsed_doc["total_rows"]
                    })
            continue
            
        bases = defaultdict(dict)
        for f in files:
            if f == "_manifest.json":
                continue
            if f.endswith(".tables.json"):
                bases[f[:-12]]["json"] = os.path.join(root, f)
            elif f.endswith(".json"):
                bases[f[:-5]]["json"] = os.path.join(root, f)
            elif f.endswith(".txt"):
                bases[f[:-4]]["txt"] = os.path.join(root, f)
                
        for base, fdict in bases.items():
            json_file = fdict.get("json")
            txt_file = fdict.get("txt")
            
            if json_file:
                parsed_doc = process_table_document(rel_sub, base, json_file, txt_file)
                out_path = os.path.join(out_subfolder, base + ".json")
                with open(out_path, "w", encoding="utf-8") as out_f:
                    json.dump(parsed_doc, out_f, indent=2)
                processed_count += 1
                manifest.append({
                    "document_id": parsed_doc["document_id"],
                    "filename": base + ".json",
                    "subfolder": rel_sub,
                    "document_type": parsed_doc["document_type"],
                    "total_rows": parsed_doc["total_rows"]
                })

    manifest_path = os.path.join(BASE_DIR, "08_json_conversion", "output", "_parsing_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump({
            "total_documents_parsed": processed_count,
            "documents": manifest
        }, mf, indent=2)

    print(f"=== PARSING COMPLETE: Processed {processed_count} structured JSON documents. ===")

def main() -> None:
    global RAW_DIR, OUTPUT_DIR

    parser = argparse.ArgumentParser(description="Parse raw extraction output JSON/TXT files into structured documents.")
    parser.add_argument("--input", type=Path, default=RAW_DIR, help="Directory with raw extraction output (default: initial_data_ingestion/07_raw_extraction_output)")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Directory where parsed JSON files are written (default: initial_data_ingestion/08_json_conversion/output)")
    args = parser.parse_args()

    RAW_DIR = args.input.resolve()
    OUTPUT_DIR = args.output.resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_parsing_pipeline()


if __name__ == "__main__":
    main()
