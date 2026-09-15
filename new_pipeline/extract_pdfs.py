import os
import fitz  # PyMuPDF
from rapidocr_onnxruntime import RapidOCR
import csv
from pathlib import Path
import json

# Setup paths
BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
EXTRACTED_DIR = BASE_DIR / "extracted"
TRACKING_CSV = BASE_DIR / "extraction_tracking.csv"

# Initialize OCR
ocr = RapidOCR()

def init_tracking_file():
    if not TRACKING_CSV.exists():
        with open(TRACKING_CSV, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["file_path", "status", "error_message"])

def get_processed_files():
    processed = set()
    if TRACKING_CSV.exists():
        with open(TRACKING_CSV, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["status"] == "success":
                    processed.add(row["file_path"])
    return processed

def log_progress(file_path, status, error_message=""):
    with open(TRACKING_CSV, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([str(file_path), status, error_message])

def extract_text_and_ocr(pdf_path):
    extracted_data = {}
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        # Determine pages to extract (1st, 2nd, and last)
        # PyMuPDF uses 0-based indexing
        target_pages = set()
        if total_pages > 0:
            target_pages.add(0) # 1st page
        if total_pages > 1:
            target_pages.add(1) # 2nd page
        if total_pages > 2:
            target_pages.add(total_pages - 1) # Last page
            
        for page_num in sorted(list(target_pages)):
            page = doc.load_page(page_num)
            
            # 1. Try normal text extraction
            text = page.get_text()
            
            # 2. OCR Extraction
            # Render page to image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # 2x zoom for better OCR
            img_data = pix.tobytes("png")
            
            ocr_result, _ = ocr(img_data)
            ocr_text = ""
            if ocr_result:
                # ocr_result is a list of [box, text, confidence]
                ocr_text = "\n".join([line[1] for line in ocr_result])
                
            extracted_data[f"page_{page_num + 1}"] = {
                "extracted_text": text.strip(),
                "ocr_text": ocr_text.strip()
            }
            
        doc.close()
        return extracted_data, True, ""
    except Exception as e:
        return None, False, str(e)

def main():
    init_tracking_file()
    processed_files = get_processed_files()
    
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Find all PDFs in downloads folder
    pdf_files = list(DOWNLOADS_DIR.rglob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files.")
    
    for pdf_path in pdf_files:
        rel_path = pdf_path.relative_to(DOWNLOADS_DIR)
        
        if str(rel_path) in processed_files:
            continue
            
        print(f"Processing: {rel_path}")
        
        extracted_data, success, error_msg = extract_text_and_ocr(pdf_path)
        
        if success:
            # Save to extracted folder
            output_file = EXTRACTED_DIR / rel_path.with_suffix('.json')
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(extracted_data, f, indent=4, ensure_ascii=False)
                
            log_progress(str(rel_path), "success")
        else:
            print(f"Failed to process {rel_path}: {error_msg}")
            log_progress(str(rel_path), "failed", error_msg)

if __name__ == "__main__":
    main()
