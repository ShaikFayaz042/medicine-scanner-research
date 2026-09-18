"""
CDSCO FDC (Fixed Dose Combination) Page - HTTP Request Experiment
Target: https://cdsco.gov.in/opencms/opencms/en/Drugs/FDC/
Purpose: Determine if the FDC page is accessible via a direct HTTP request
         and whether PDF links (approved / prohibited FDC lists) are
         present in the initial HTML response.
"""

import requests
from pathlib import Path
from datetime import datetime

# --- Target ---
URL = "https://cdsco.gov.in/opencms/opencms/en/Drugs/FDC/"

# --- Output ---
OUTPUT_DIR = Path("websites/cdsco-fdc/http-requests/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Headers (same as existing CDSCO scraper) ---
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

print(f"[*] Sending GET request to: {URL}")
print(f"[*] Timeout: 30 seconds")

try:
    response = requests.get(URL, headers=HEADERS, timeout=30)

    # --- Response metadata ---
    print(f"\n[+] HTTP Status Code : {response.status_code}")
    print(f"[+] Response Size    : {len(response.content):,} bytes "
          f"({len(response.content) / 1024:.2f} KB)")
    print(f"[+] Content-Type     : {response.headers.get('Content-Type', 'N/A')}")
    print(f"[+] Server           : {response.headers.get('Server', 'N/A')}")

    # --- Save raw HTML ---
    html_file = OUTPUT_DIR / "fdc_page.html"
    html_file.write_text(response.text, encoding="utf-8")
    print(f"\n[+] Raw HTML saved to: {html_file}")

    # --- Structural checks ---
    html_lower = response.text.lower()

    table_count = html_lower.count("<table")
    print(f"\n[+] <table> elements : {table_count}")

    pdf_count = html_lower.count(".pdf")
    jsp_count = html_lower.count("download_file_division")
    print(f"[+] '.pdf' occurrences        : {pdf_count}")
    print(f"[+] 'download_file_division' : {jsp_count}")

    if pdf_count > 0 or jsp_count > 0:
        print("[+] PDF/document links appear to be present in the HTML.")
    else:
        print("[-] No PDF/document links found in HTML. May be JS-loaded.")

    # --- Keyword presence ---
    keywords = [
        "fdc", "fixed dose", "fixed-dose", "combination",
        "approved", "prohibited", "banned", "restricted",
        "not of standard", "nsq", "spurious", "substandard",
    ]
    print("\n[*] Keyword presence in HTML:")
    for kw in keywords:
        found = kw in html_lower
        print(f"    - {kw!r:30} : {'FOUND' if found else 'not found'}")

    # --- Count <a> tags pointing to files ---
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.text, "html.parser")
    all_links = soup.find_all("a", href=True)
    file_links = [
        a for a in all_links
        if ".pdf" in a["href"].lower()
        or "download_file_division" in a["href"].lower()
        or "upload" in a["href"].lower()
    ]
    print(f"\n[+] <a> tags total             : {len(all_links)}")
    print(f"[+] <a> tags pointing to files : {len(file_links)}")

    if file_links:
        print("\n[*] First 5 file links found:")
        for a in file_links[:5]:
            href = a["href"].strip()
            text = a.get_text(strip=True)[:60] or "(no text)"
            print(f"    - text: {text!r}")
            print(f"      href: {href[:110]}")

    # --- Save metadata ---
    meta_file = OUTPUT_DIR / "fdc_response_metadata.txt"
    meta_file.write_text(
        f"URL: {URL}\n"
        f"Status: {response.status_code}\n"
        f"Size: {len(response.content)} bytes\n"
        f"Content-Type: {response.headers.get('Content-Type')}\n"
        f"Server: {response.headers.get('Server')}\n"
        f"Timestamp: {datetime.now().isoformat()}\n"
        f"Table count: {table_count}\n"
        f"PDF count: {pdf_count}\n"
        f"download_file_division count: {jsp_count}\n"
        f"Total <a> tags: {len(all_links)}\n"
        f"File-pointing <a> tags: {len(file_links)}\n",
        encoding="utf-8",
    )
    print(f"\n[+] Metadata saved to: {meta_file}")

except requests.exceptions.Timeout:
    print("[-] Request timed out after 30 seconds.")
except requests.exceptions.ConnectionError as e:
    print(f"[-] Connection error: {e}")
except requests.exceptions.RequestException as e:
    print(f"[-] Request failed: {e}")