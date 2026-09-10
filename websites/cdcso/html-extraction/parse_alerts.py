"""
CDSCO HTML Extraction Experiment
Target: websites/cdcso/output/alerts_page.html (saved in previous experiment)
Purpose: Verify we can extract structured records (title, date, pdf_url, size)
         from the raw HTML using BeautifulSoup.
"""

import base64
import json
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- Paths ---
INPUT_HTML = Path("websites/cdcso/output/alerts_page.html")
OUTPUT_DIR = Path("websites/cdcso/html-extraction/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Base URL used to turn relative /opencms/... links into absolute URLs
BASE_URL = "https://cdsco.gov.in"

# --- Load the HTML ---
if not INPUT_HTML.exists():
    raise SystemExit(
        f"[!] Input HTML not found at {INPUT_HTML}.\n"
        f"    Run websites/cdcso/http-requests.py first."
    )

html = INPUT_HTML.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

# --- Locate the Alerts table ---
table = soup.find("table", id="example")
if table is None:
    raise SystemExit("[!] Could not find <table id='example'> in the HTML.")

rows = table.find("tbody").find_all("tr")
print(f"[*] Found {len(rows)} rows in the Alerts table.")

records = []
for row in rows:
    cells = row.find_all("td")
    if len(cells) < 5:
        continue  # skip malformed rows

    sno = cells[0].get_text(strip=True)
    title = cells[1].get_text(strip=True)
    release_date = cells[2].get_text(strip=True)

    # PDF link: <a href='/opencms/...download_file_division.jsp?num_id=XXXX='>
    anchor = cells[3].find("a")
    if anchor and anchor.get("href"):
        raw_href = anchor["href"].strip()
        pdf_url = urljoin(BASE_URL, raw_href)

        # Extract the num_id (Base64-encoded internal document ID)
        num_id_b64 = ""
        if "num_id=" in raw_href:
            num_id_b64 = raw_href.split("num_id=")[1].split("&")[0]

        # Try to decode it into the plain internal ID (useful for future dedup)
        document_id = None
        try:
            document_id = base64.b64decode(num_id_b64).decode("utf-8")
        except Exception:
            document_id = None
    else:
        raw_href = ""
        pdf_url = ""
        num_id_b64 = ""
        document_id = None

    pdf_size = cells[4].get_text(strip=True)

    records.append({
        "sno": sno,
        "title": title,
        "release_date": release_date,
        "pdf_url": pdf_url,
        "num_id_b64": num_id_b64,
        "document_id": document_id,
        "pdf_size": pdf_size,
    })

# --- Save as JSON ---
json_path = OUTPUT_DIR / "alerts.json"
json_path.write_text(
    json.dumps(records, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(f"[+] Saved {len(records)} records to: {json_path}")

# --- Print a preview of the first 5 rows ---
print("\n[*] Preview (first 5 records):")
for r in records[:5]:
    print("-" * 70)
    print(f"  S.No        : {r['sno']}")
    print(f"  Title       : {r['title'][:80]}")
    print(f"  Date        : {r['release_date']}")
    print(f"  Document ID : {r['document_id']}  (base64: {r['num_id_b64']})")
    print(f"  Size        : {r['pdf_size']}")
    print(f"  PDF URL     : {r['pdf_url']}")

# --- Sanity checks ---
print("\n[*] Sanity checks:")
missing_urls = sum(1 for r in records if not r["pdf_url"])
missing_dates = sum(1 for r in records if not r["release_date"])
missing_ids = sum(1 for r in records if not r["document_id"])
print(f"    Records without a PDF URL     : {missing_urls}")
print(f"    Records without a release date: {missing_dates}")
print(f"    Records without a document ID : {missing_ids}")
print(f"    Total records                 : {len(records)}")