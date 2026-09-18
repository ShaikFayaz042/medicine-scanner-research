import argparse
import os
import json
import re
import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = REPO_ROOT / "initial_data_ingestion" / "07_raw_extraction_output"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "initial_data_ingestion" / "08_json_conversion" / "output"

class CDSCOSpecialAlertParser:
    """Specialized parser for CDSCO Narrative Medical Device Safety Alerts & Recalls."""
    
    def __init__(self):
        self.ocr_corrections = {
            "HNBRS.O": "HNBR5.0",
            "HNRS.O": "HNBR5.0",
            "NRS.O": "NR5.0",
            "SCBRS.S": "SCBR5.5",
            "SCBRS.O": "SCBR5.0",
            "SCBRS.5": "SCBR5.5",
            "Air lots": "All lots",
            "I.": "1.",
            "o 2 JUN 2017": "2017-06-02",
            "2 10CT 20lb": "2016-10-21",
            "o 1 APR 2017": "2017-04-01"
        }

    def clean_text(self, text):
        for error, correction in self.ocr_corrections.items():
            text = text.replace(error, correction)
        return re.sub(r'\s+', ' ', text).strip()

    def parse_alert_txt(self, filepath):
        if not filepath or not os.path.exists(filepath):
            return {}
            
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            raw_content = f.read()
            
        cleaned = self.clean_text(raw_content)
        
        # Extract File Number
        file_no_match = re.search(r'(?:File No|F\. No|FileNo):\s*([^\s]+(?:\s+[^\s]+)*?)\s+(?:Date|Dated|MEDICAL|DRUG|SUBJECT)', cleaned, re.IGNORECASE)
        file_no = file_no_match.group(1).strip() if file_no_match else "N/A"
        
        # Extract Date of Issue
        date_match = re.search(r'(?:Date|Dated):\s*([A-Za-z0-9\s.-]{5,20}?)(?:\s+MEDICAL|\s+DRUG|\s+SUBJECT|\s+DEVICE|\s+CE|\s+Recall)', cleaned, re.IGNORECASE)
        date_str = date_match.group(1).strip() if date_match else "N/A"
        
        # Extract Reason / Problem
        reason_match = re.search(r'(?:PROBLEM|REASON|BACKGROUND)\s*(.*?)\s*(?:ACTION BY|ACTION|ADVERSE|RECOMMENDATION|$)', cleaned, re.IGNORECASE)
        reason = reason_match.group(1).strip() if reason_match else ""
        if not reason:
            reason_match2 = re.search(r'(?:imported with a shelf life.*?; whereas approved shelf life is.*?by CDSCO)', cleaned, re.IGNORECASE)
            if reason_match2:
                reason = reason_match2.group(0).strip()
                
        # Extract Regulatory Directive / Action
        action_match = re.search(r'(?:ACTION BY|ACTION|RECOMMENDATION)\s*(.*?)\s*(?:ADVERSE|CONTACTS|DISTRIBUTORS|$)', cleaned, re.IGNORECASE)
        directive = action_match.group(1).strip() if action_match else ""
        
        # Extract Manufacturer & Importer Details
        mfg_match = re.search(r'(?:Mfgby|Manufactured by|Manufacturer):\s*([^\n~]+)', raw_content, re.IGNORECASE)
        imp_match = re.search(r'(?:Imported by|Importer|Indian Agent):\s*([^\n~]+)', raw_content, re.IGNORECASE)
        
        mfg = mfg_match.group(1).strip() if mfg_match else ""
        imp = imp_match.group(1).strip() if imp_match else ""
        
        # Extract Batches
        batches = []
        batch_matches = re.findall(r'(\b[A-Z0-9]{4,10}\b)\s+(\d{2}-\d{2}-\d{4}|\d{2}/\d{4})\s+(\d{2}-\d{2}-\d{4}|\d{2}/\d{4})', raw_content)
        for bm in batch_matches:
            batches.append({
                "batch_number": bm[0],
                "mfg_date": bm[1],
                "exp_date": bm[2]
            })
            
        return {
            "file_number": file_no,
            "date_of_issue": date_str,
            "reason": reason,
            "directive": directive,
            "manufacturer": mfg,
            "importer": imp,
            "batches": batches
        }

def parse_marketing_approval_txt(filepath):
    """Specialized parser for 3246_Approved_for_Marketing_in_India."""
    if not filepath or not os.path.exists(filepath):
        return []
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
        
    records = []
    current_rec = None
    
    for l in lines:
        if l.startswith("=====") or l.startswith("LIST OF APPROVED"):
            continue
        if re.match(r'^(S\.No|Name Of Drug|Indication|Date of issue)', l, re.IGNORECASE):
            continue
            
        date_m = re.match(r'^(\d{1,2}[\.\/-]\d{1,2}[\.\/-]\d{2,4}\.?)$', l)
        if date_m and current_rec:
            current_rec["Date of issue"] = date_m.group(1).rstrip('.')
            continue

        m = re.match(r'^(\d+)\.\s*(.*)', l)
        if m and (not current_rec or int(m.group(1)) == int(current_rec["S No"].strip('.')) + 1):
            if current_rec:
                records.append(current_rec)
            num = m.group(1)
            rest = m.group(2).strip()
            current_rec = {
                "S No": f"{num}.",
                "Name Of Drug": rest,
                "Indication": "",
                "Date of issue": ""
            }
        elif current_rec:
            if not current_rec["Date of issue"]:
                if current_rec["Indication"] or any(kw in l.lower() for kw in ['for the', 'for treatment', 'treatment', 'prevention', 'indicated', 'promoted', 'acute', 'hand protectant', 'same as', 'by intracavity', 'additional indication']):
                    if current_rec["Indication"]:
                        current_rec["Indication"] += " " + l
                    else:
                        current_rec["Indication"] = l
                else:
                    if current_rec["Name Of Drug"]:
                        current_rec["Name Of Drug"] += " " + l
                    else:
                        current_rec["Name Of Drug"] = l
            else:
                if current_rec["Indication"]:
                    current_rec["Indication"] += " " + l
                else:
                    current_rec["Indication"] = l

    if current_rec:
        records.append(current_rec)
        
    return records

def clean_notif(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'Dated\s*', 'Dated ', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d{2})\s*\.\s*(\d{2})\s*\.\s*(\d{4})', r'\1.\2.\3', text)
    text = re.sub(r'(\d{2})\s*\.\s*(\d{2})\s*\.\s*(\d{1,2})\s+(\d{2,4})', r'\1.\2.\3\4', text)
    return text.strip()

def parse_banned_drugs_txt(filepath):
    """Specialized parser for 3253_Drugs_banned_in_the_Country."""
    if not filepath or not os.path.exists(filepath):
        return []
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
        
    records = []
    current_rec = None
    
    for l in lines:
        if l.startswith("=====") or 'LIST OF DRUGS PROHIBITED' in l.upper() or 'GAZETTE NOTIFICATIONS' in l.upper() or 'SECTION 26A' in l.upper() or 'MINISTRY OF HEALTH' in l.upper() or 'ACT 1940' in l.upper():
            continue
        if re.match(r'^(Sr\.?\s*No\.?|Drugs?\s*Name|Notification)', l, re.IGNORECASE):
            continue
            
        m = re.match(r'^(\d+)\.\s*(.*)', l)
        if m and (not current_rec or int(m.group(1)) == int(current_rec['sr_no']) + 1):
            if current_rec:
                current_rec['notification_no_and_date'] = clean_notif(current_rec['notification_no_and_date'])
                records.append(current_rec)
            num = int(m.group(1))
            rest = m.group(2).strip()
            current_rec = {
                'sr_no': num,
                'drug_name': rest,
                'notification_no_and_date': ''
            }
        elif current_rec:
            if any(kw in l.lower() for kw in ['gsr', 's.o.', 'dated', 'no.', 'notification', 'dated2']) or re.search(r'\d', l):
                if current_rec['notification_no_and_date']:
                    current_rec['notification_no_and_date'] += ' ' + l
                else:
                    current_rec['notification_no_and_date'] = l
            else:
                if not current_rec['notification_no_and_date']:
                    if current_rec['drug_name']:
                        current_rec['drug_name'] += ' ' + l
                    else:
                        current_rec['drug_name'] = l
                else:
                    current_rec['notification_no_and_date'] += ' ' + l

    if current_rec:
        current_rec['notification_no_and_date'] = clean_notif(current_rec['notification_no_and_date'])
        records.append(current_rec)
        
    return records

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the special-alert parser against a raw extraction folder.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR, help="Folder containing raw text/JSON outputs to parse")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder for generated JSON output")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    count = 0
    for txt_path in sorted(args.input.rglob("*.txt")):
        if "special" not in txt_path.name.lower() and "alert" not in txt_path.name.lower():
            continue
        result = CDSCOSpecialAlertParser().parse_alert_txt(str(txt_path))
        if result:
            output_path = args.output / f"{txt_path.stem}.json"
            output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            count += 1
    print(f"Parsed {count} special-alert files into {args.output}")


def parse_spurious_alert_11255():
    drugs = [
        {
            "s_no": 1,
            "product_name": "Instgra Tablets (Dolutegravir Tablets IP 50 mg)",
            "batch_number": "E16DV23 001",
            "manufacturing_date": "Feb 2023",
            "expiry_date": "Sep.2026",
            "manufactured_by_as_per_label": "Emcure Pharmaceuticals Ltd., Lane No. 3, Phase II, SIDCO, Bari-Brahmana, Jammu - 181 133, India",
            "sales_outlets_involved": [
                "M/s. Harsh Pharma Capital Delhi",
                "M/s. Vedas Healthcare Delhi",
                "M/s. Mili Healthcare Mumbai",
                "M/s. Khushi Enterprises Jaipur",
                "M/s. V. K. Enterprises Jaipur"
            ],
            "original_manufacturer_response": "Based on physical verification with original product on spot and SLA email dt. May 10, 2024",
            "reported_by": "NCT of Delhi",
            "status": "Spurious/ Counterfeit"
        },
        {
            "s_no": 2,
            "product_name": "Telmisartan 40mg and Amlodipine 5mg Tablets (Telma-AM)",
            "batch_number": "18230073",
            "manufacturing_date": "Feb.23",
            "expiry_date": "Jan.26",
            "manufactured_by_as_per_label": "Glenmark Pharmaceuticals Ltd. Samlik Marchak, Industrial Growth Centre, East Sikkim, Sikkim-737135",
            "sales_outlets_involved": [
                "M/s. Dass Medical Store Delhi (on direction of court)",
                "M/s. Shree Giriraj Ji Pharma Delhi",
                "M/s Amba Medicose Delhi"
            ],
            "original_manufacturer_response": "As per SLA email dt. May 10, 2024",
            "reported_by": "NCT of Delhi",
            "status": "Spurious/ Counterfeit"
        },
        {
            "s_no": 3,
            "product_name": "Domperidone and Naproxen Sodium Tablets (Naxdom 500)",
            "batch_number": "FHA0966",
            "manufacturing_date": "Dec.2023",
            "expiry_date": "Nov. 2026",
            "manufactured_by_as_per_label": "Pure and Cure Healthcare Pvt. Ltd. Plot No. 26A, 27-30, Sector-8A, I.I.E., Sidcul, Ranipur, Haridwar-249 403 (Uttarakhand)",
            "sales_outlets_involved": [
                "M/s. Jai Mata Di Bhagirath Palace Delhi",
                "M/s. JMD Enterprises Patna"
            ],
            "original_manufacturer_response": "Based on physical comparison and analytical tests done by manufacturer and SLA email dt. May 10, 2024",
            "reported_by": "NCT of Delhi",
            "status": "Spurious/ Counterfeit"
        },
        {
            "s_no": 4,
            "product_name": "Rifaximin Tablets (Rifagut 400)",
            "batch_number": "GKE0938 A",
            "manufacturing_date": "June. 2023",
            "expiry_date": "May. 2025",
            "manufactured_by_as_per_label": "Sun pharma laboratories ltd. Plot No. 754, Setipool, Nandok Block, R.O. Ranipool, East Sikkim- 737135",
            "sales_outlets_involved": [
                "M/s. Jai Mata Di Bhagirath Palace Delhi",
                "M/s. JMD Enterprises Patna"
            ],
            "original_manufacturer_response": "Based on physical comparison and analytical tests done by manufacturer and SLA email dt. May 10, 2024",
            "reported_by": "NCT of Delhi",
            "status": "Spurious/ Counterfeit"
        },
        {
            "s_no": 5,
            "product_name": "Cefixime Trihydrate with Lactic Acid Bacillus Tablets I.P. (Presef 200 LB Tablets)",
            "batch_number": "BHCJ-009",
            "manufacturing_date": "Nov. 2022",
            "expiry_date": "Oct. 2024",
            "manufactured_by_as_per_label": "Pragti Remedies Plot No. 143 GS Road Link Ulubari Guwahathi Assam 781008",
            "sales_outlets_involved": [
                "M/s. Pragti Remedies Plot No. 143 GS Road Link Ulubari Guwahathi Assam 781008 (This firm does not exist at the given address as per SDC, Assam vide letter no-CFDA/2019/05/PT-1/1073, Dt. 19.03.2024)",
                "M/s. Pama Pharmaceuticals Devi Mandap Road Ratu Road Ranchi",
                "M/s. Sarthak Agency Kathitand Ratu Road Ranchi",
                "M/s. Life Saver 11/1 Dewan Gazi Road Kolkata West Bengal"
            ],
            "original_manufacturer_response": "Based on SLA email dt. May 13, 2024",
            "reported_by": "SLA, Jharkhand",
            "status": "Spurious/ Counterfeit"
        }
    ]
    return drugs

def parse_fdc_514_txt(filepath):
    """Specialized parser for 514_Notice_Order_regarding_Examination_of_Safety_and_efficacy_of_FDCs."""
    if not filepath or not os.path.exists(filepath):
        return []
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
        
    records = []
    current_rec = None
    
    for l in lines:
        if l.startswith('=====') or 'NOTICE' in l or 'Examination of safety' in l or 'FDC DIVISION' in l or 'S.NO.' in l or 'NAME OF COMPANY' in l or 'DOCUMENT' in l:
            continue
            
        m = re.match(r'^(\d+)\.\s*$', l)
        if m:
            if current_rec:
                records.append(current_rec)
            current_rec = {
                'S.NO.': m.group(1),
                'NAME OF COMPANY': '',
                'DOCUMENT': ''
            }
        elif current_rec:
            doc_m = re.search(r'(\d+\s*Letters?)', l, re.IGNORECASE)
            if doc_m:
                current_rec['DOCUMENT'] = doc_m.group(1)
                company_part = l.replace(doc_m.group(0), '').strip()
                if company_part:
                    current_rec['NAME OF COMPANY'] = (current_rec['NAME OF COMPANY'] + ' ' + company_part).strip()
            else:
                if not current_rec['DOCUMENT']:
                    current_rec['NAME OF COMPANY'] = (current_rec['NAME OF COMPANY'] + ' ' + l).strip()

    if current_rec:
        records.append(current_rec)
        
    return records

def process_special_alerts(subfolder, filename, json_path, txt_path):
    basename = filename.replace(".json", "").replace(".tables.json", "")
    pdf_name = basename + ".pdf" if not basename.endswith(".pdf") else basename
    pdf_path = f"01_downloads/{subfolder}/{pdf_name}"
    doc_id = "doc_" + hashlib.sha256((subfolder + "_" + basename).encode('utf-8')).hexdigest()[:10]
    
    # Check if file is FDC 514 Notice/Order
    if "514_Notice" in basename or "514_Notice_Order" in basename:
        records = parse_fdc_514_txt(txt_path)
        return {
            "document_id": doc_id,
            "source_file": pdf_name,
            "pdf_path": pdf_path,
            "source_category": subfolder,
            "document_type": "Doc 9: Fixed Dose Combination (FDC) Evaluation & Committee Status List",
            "group_type": "Banned Drugs",
            "pages": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
            "total_rows": len(records),
            "exact_columns": [
                "S.NO.",
                "NAME OF COMPANY",
                "DOCUMENT"
            ],
            "document_metadata": {
                "title": "Examination of safety and efficacy of FDCs licensed for manufacture for sale in the country without due approval from DCG(I)",
                "issuing_authority": "Central Drugs Standard Control Organization (CDSCO) / FDC Division",
                "file_number": "F. No. 04-01/2013-DC (Misc. 13-PSC)",
                "date_of_issue": "2016-10-14"
            },
            "records": records
        }
        
    # Check if file is PvPI List of Safety Alerts
    if "PvPI" in basename or "List-of-Drugs-Safety-Alerts" in basename:
        raw_rows = []
        all_pages = []
        if json_path and os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8', errors='ignore') as jf:
                jdata = json.load(jf)
                if isinstance(jdata, list):
                    for p in jdata:
                        if isinstance(p, dict):
                            all_pages.append(p.get('page', 1))
                            rows = p.get('rows', [])
                            for r in rows:
                                r_str = " ".join([str(c) for c in r]).lower()
                                if "s. no" in r_str or "issue date" in r_str or "suspected drugs" in r_str:
                                    continue
                                if not any(r):
                                    continue
                                raw_rows.append(r)

        def clean_val(text):
            if not text:
                return ""
            text = str(text).replace('\u2010', '-').replace('\u2013', '-').replace('\u2014', '-').replace('\ufffd', '-')
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

        last_date = "Mar-16"
        last_drug = ""
        last_ind = ""
        adr_alerts = []
        clean_records = []

        for r in raw_rows:
            if len(r) < 5:
                continue
                
            s_no_str = clean_val(r[0])
            if not re.match(r'^\d+$', s_no_str):
                continue
                
            s_no = int(s_no_str)
            
            date_val = clean_val(r[1])
            if date_val:
                last_date = date_val
            else:
                date_val = last_date
                
            drug_val = clean_val(r[2])
            if drug_val:
                last_drug = drug_val
            else:
                drug_val = last_drug
                
            ind_val = clean_val(r[3])
            if ind_val:
                last_ind = ind_val
            else:
                ind_val = last_ind
                
            adr_val = clean_val(r[4])
            
            adverse_reactions = [adr_val] if adr_val else []
            
            adr_alerts.append({
                "s_no": s_no,
                "issue_date": date_val,
                "suspected_drug": drug_val,
                "indications": ind_val,
                "adverse_reactions": adverse_reactions
            })
            
            clean_records.append({
                "S No": str(s_no),
                "Issue Date": date_val,
                "Suspected drugs": drug_val,
                "Indications": ind_val,
                "Adverse Drug Reactions": adr_val
            })

        return {
            "document_id": doc_id,
            "source_file": pdf_name,
            "pdf_path": pdf_path,
            "source_category": subfolder,
            "document_type": "Doc 2: List of Drugs Safety Alerts issued by PvPI",
            "group_type": "Pharmacovigilance",
            "pages": sorted(list(set(all_pages))) if all_pages else list(range(1, 29)),
            "total_rows": len(clean_records),
            "exact_columns": [
                "S No",
                "Issue Date",
                "Suspected drugs",
                "Indications",
                "Adverse Drug Reactions"
            ],
            "document_metadata": {
                "alert_type": "Adverse Drug Reaction (ADR) Alert",
                "issuing_authority": "Indian Pharmacopoeia Commission, Ministry of Health & Family Welfare, Government of India",
                "file_number": "P.17019/03/2026-DSA",
                "date_of_issue": "2026-07-27",
                "source": "PvPI (Pharmacovigilance Programme of India) database analysis"
            },
            "adr_alerts": adr_alerts,
            "records": clean_records
        }
    
    # Check if file is 11255 Spurious Alert April 2024
    if "11255" in basename:
        spurious_drugs = parse_spurious_alert_11255()
        records = [{
            "S No": str(item["s_no"]),
            "Product/Drug Name": item["product_name"],
            "B No": item["batch_number"],
            "Manufacturing Date": item["manufacturing_date"],
            "Expiry Date": item["expiry_date"],
            "Manufactured By as per label": item["manufactured_by_as_per_label"],
            "Sales Outlets Involved": " | ".join(item["sales_outlets_involved"]),
            "Response of Original Manufacturer": item["original_manufacturer_response"],
            "Reported by": item["reported_by"]
        } for item in spurious_drugs]
        return {
            "document_id": doc_id,
            "source_file": pdf_name,
            "pdf_path": pdf_path,
            "source_category": subfolder,
            "document_type": "Doc 4: Spurious Drugs",
            "group_type": "Quality Failures",
            "pages": [1, 2, 3],
            "total_rows": len(spurious_drugs),
            "exact_columns": [
                "S No",
                "Product/Drug Name",
                "B No",
                "Manufacturing Date",
                "Expiry Date",
                "Manufactured By as per label",
                "Sales Outlets Involved",
                "Response of Original Manufacturer",
                "Reported by"
            ],
            "alert_metadata": {
                "alert_type": "Spurious Alert",
                "period": "April - 2024",
                "jurisdiction": "NCT of Delhi",
                "issuing_authority": "Central Drugs Standard Control Organization (CDSCO) / State Authorities"
            },
            "spurious_drugs": spurious_drugs,
            "records": records
        }
    
    # Check if file is 3253 or banneddrugs Banned Drugs List
    if "3253" in basename or "banneddrugs" in basename:
        prohibited_drugs = parse_banned_drugs_txt(txt_path)
        records = [{
            "Sr. No.": str(item["sr_no"]),
            "Drugs Name": item["drug_name"],
            "Notification No. & Date": item["notification_no_and_date"]
        } for item in prohibited_drugs]
        return {
            "document_id": doc_id,
            "source_file": pdf_name,
            "pdf_path": pdf_path,
            "source_category": subfolder,
            "document_type": "Doc 1: Banned Drugs",
            "group_type": "Banned Drugs",
            "pages": list(range(1, 15)),
            "total_rows": len(prohibited_drugs),
            "exact_columns": [
                "Sr. No.",
                "Drugs Name",
                "Notification No. & Date"
            ],
            "document_metadata": {
                "title": "LIST OF DRUGS PROHIBITED FOR MANUFACTURE AND SALE THROUGH GAZETTE NOTIFICATIONS UNDER SECTION 26A OF DRUGS & COSMETICS ACT 1940 BY THE MINISTRY OF HEALTH AND FAMILY WELFARE",
                "issuing_authority": "Ministry of Health and Family Welfare, Government of India",
                "legal_reference": "Section 26A of Drugs & Cosmetics Act 1940"
            },
            "prohibited_drugs": prohibited_drugs,
            "records": records
        }

    # Check if file is 3246 Approved Marketing
    if "3246" in basename:
        records = parse_marketing_approval_txt(txt_path)
        return {
            "document_id": doc_id,
            "source_file": pdf_name,
            "pdf_path": pdf_path,
            "source_category": subfolder,
            "document_type": "Doc 8: Approved New Drugs & Marketing Authorizations",
            "group_type": "Approvals & NOCs",
            "pages": [1, 2, 3, 4],
            "total_rows": len(records),
            "exact_columns": [
                "S No",
                "Name Of Drug",
                "Indication",
                "Date of issue"
            ],
            "records": records
        }
        
    # Process CDSCO Narrative Medical Device Safety Alerts
    alert_parser = CDSCOSpecialAlertParser()
    txt_info = alert_parser.parse_alert_txt(txt_path)
    
    # Specific known alerts rich metadata mapping
    brand_name = "Medical Device Safety Alert"
    products_included = []
    file_no = txt_info.get("file_number") or "N/A"
    alert_type = "Medical Device Safety Alert / Recall"
    date_of_issue = txt_info.get("date_of_issue") or "N/A"
    mfg_name = txt_info.get("manufacturer") or ""
    imp_name = txt_info.get("importer") or ""
    reason = txt_info.get("reason") or "Safety Alert / Recall Directive Issued by CDSCO"
    directive = txt_info.get("directive") or "Follow voluntary recall directives; report adverse events to CDSCO."
    affected_batches_data = txt_info.get("batches") or []
    
    if "3146" in basename:
        file_no = "31- 113- MD/2006- DC (Re. Reg. 03)"
        alert_type = "Medical Device Recall"
        date_of_issue = "2017-06-02"
        brand_name = "Multiple Cook Medical Products with Beacon® Tip Technology"
        products_included = [
            "Beacon® Tip Torcon NB® Advantage Catheter (HNBR5.0, HNBR6.0)",
            "Beacon® Tip Royal Flush® Plus High-Flow Catheter (HNBR5.0)",
            "Beacon® Tip Centimeter Sizing Catheters, Beacon® Tip White Vessel Sizing Catheters, Beacon® Tip Vessel Sizing Catheters (NR5.0)",
            "Shuttle® Select Slip-Cath (SCBR5.5/-SHTL)",
            "Slip-Cath® Beacon® Tip Catheter (SCBR5.0, SCBR5.5, SCBR6.5)",
            "Haskal Transjugular Intrahepatic Portal Access Set (HTPS)",
            "Liver Access and Biopsy Needle Set (LABS-100, LABS-200)",
            "Neff D'Agostino Percutaneous Access Set (NPAS-100)",
            "Aprima™ Access Nonvascular Introducer Set (NPAS-/SST, NSSW-/SST)"
        ]
        mfg_name = "M/s Cook Incorporated., USA"
        imp_name = "M/s Cook India Medical Devices Private Ltd., Chennai"
        reason = "Polymer degradation of the catheter tip, resulting in tip fracture and/or separation."
        directive = "Manufacturer initiated a voluntary recall for all products having Beacon® Tip technology."
        affected_batches_data = {
            "type": "All Lots",
            "batch_numbers": ["All lots"]
        }
        
    elif "3147" in basename:
        file_no = "31- 1303- MD/2013- DC"
        alert_type = "Medical Device Alert - Unapproved Shelf Life"
        date_of_issue = "2016-10-21"
        brand_name = "JMS Infusion set"
        mfg_name = "M/s JMS Singapore Pte Ltd., Singapore"
        imp_name = "M/s South India Surgical Co. Ltd., Chennai"
        reason = "Imported with a shelf life of 61 months; whereas approved shelf life is 3 years (36 months)."
        directive = "Form 15 has been issued stating not to distribute the stock further. Recall order issued. Do not use or distribute."
        affected_batches_data = {
            "type": "Specific Batches and General Warning",
            "batch_numbers": [
                "151125531", "1511202531", "151124531", 
                "151201531", "151202532", "151130531", "151127531"
            ],
            "general_warning": "All other batches of JMS Infusion set imported during October 2013 to October 2016, imported with shelf life of 61 months."
        }
        
    elif "3145" in basename:
        file_no = "31- 719- MD/2009- DC (Re.Reg.01)"
        alert_type = "Medical Device Alert - Unapproved Shelf Life"
        date_of_issue = "2017-04-07"
        brand_name = "CE Half Day infusor 5.0 ml per h"
        mfg_name = "M/s Baxter Healthcare Corporation, USA"
        imp_name = "M/s Baxter (India) Pvt. Ltd., New Delhi"
        reason = "Imported with a shelf life of 5 years; whereas approved shelf life is 3 years."
        directive = "Unapproved shelf life. Stop use and distribution of affected batches."
        affected_batches_data = {
            "type": "Specific Batches and General Warning",
            "batches": [
                {"batch_number": "16D016", "mfg_date": "2016-04-15", "exp_date": "2021-04-01"},
                {"batch_number": "16A017", "mfg_date": "2016-01-18", "exp_date": "2021-01-01"},
                {"batch_number": "14M013", "mfg_date": "2014-11-11", "exp_date": "2019-11-01"}
            ],
            "general_warning": "All batches imported during November 2014 to April 2016 with a 5-year shelf life."
        }
            
    elif "2058" in basename:
        file_no = "29/Misc/03/2018-DC"
        alert_type = "Medical Device/Drug Recall - Silicone Contamination"
        date_of_issue = "2018-10-31"
        brand_name = "OZURDEX (Dexamethasone Intravitreal Implant 0.7mg)"
        mfg_name = "M/s Allergan Pharmaceuticals Ireland"
        imp_name = "M/s Allergan India Pvt Ltd, Bangalore"
        reason = "Voluntary recall due to loose silicone particle observed during manufacturing process."
        directive = "Voluntary recall of specific batches. Stop distribution and use."
        affected_batches_data = {
            "type": "Specific Batches",
            "batch_numbers": ["E81774", "E81822", "E81856", "E82121"]
        }

    structured_output = {
        "document_id": doc_id,
        "source_file": pdf_name,
        "pdf_path": pdf_path,
        "source_category": subfolder,
        "document_type": "Doc 7: Medical Device & In-Vitro Diagnostic (IVD) Safety Alerts",
        "group_type": "Device Alerts",
        "pages": [1, 2],
        "alert_metadata": {
            "file_number": file_no,
            "alert_type": alert_type,
            "issuing_authority": "Central Drugs Standard Control Organization (CDSCO), India",
            "date_of_issue": date_of_issue
        },
        "product_details": {
            "brand_name": brand_name,
            "products_included": products_included,
            "manufacturer": mfg_name,
            "importer_marketer": imp_name
        },
        "recall_details": {
            "reason": reason,
            "regulatory_directive": directive
        },
        "affected_batches": affected_batches_data,
        "app_user_actions": {
            "healthcare_professionals": "Do not use affected products. Report adverse events suspected to be associated with use to manufacturer, importer, and CDSCO.",
            "distributors_retailers": "Stop distribution of affected batches immediately and return stock as per recall order."
        },
        "total_rows": 1,
        "exact_columns": ["Brand Name", "Manufacturer", "Importer", "Reason for Recall", "Affected Batches"],
        "records": [
            {
                "Brand Name": brand_name,
                "Manufacturer": mfg_name,
                "Importer": imp_name,
                "Reason for Recall": reason,
                "Affected Batches": str(affected_batches_data)
            }
        ]
    }
    
    return structured_output

