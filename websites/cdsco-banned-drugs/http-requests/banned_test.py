"""
CDSCO Banned Drugs Page - HTTP Request Experiment
Target: https://cdsco.gov.in/opencms/opencms/en/BannedDrugs
Purpose: Determine how the banned drugs list is published
         (single PDF? multiple? table? embedded?).
"""

import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

URL = "https://cdsco.gov.in/opencms/opencms/en/BannedDrugs"

OUTPUT_DIR = Path("websites/cdsco-banned-drugs/http-requests/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

try:
    resp = requests.get(URL, headers=HEADERS, timeout=30)

    print(f"\n[+] HTTP Status     : {resp.status_code}")
    print(f"[+] Response Size   : {len(resp.content):,} bytes "
          f"({len(resp.content)/1024:.2f} KB)")
    print(f"[+] Content-Type    : {resp.headers.get('Content-Type', 'N/A')}")
    print(f"[+] Server          : {resp.headers.get('Server', 'N/A')}")

    html_file = OUTPUT_DIR / "banned_page.html"
    html_file.write_text(resp.text, encoding="utf-8")
    print(f"\n[+] Raw HTML saved  : {html_file}")

    html_lower = resp.text.lower()

    table_count = html_lower.count("<table")
    pdf_count = html_lower.count(".pdf")
    jsp_count = html_lower.count("download_file_division")
    print(f"\n[+] <table> elements        : {table_count}")
    print(f"[+] '.pdf' occurrences      : {pdf_count}")
    print(f"[+] 'download_file_division': {jsp_count}")

    keywords = [
        "banned", "prohibited", "section 26a", "26a",
        "drugs and cosmetics act", "gazette",
        "fixed dose", "fdc", "nsq", "spurious",
    ]
    print("\n[*] Keyword presence in HTML:")
    for kw in keywords:
        print(f"    - {kw!r:30} : {'FOUND' if kw in html_lower else 'not found'}")

    soup = BeautifulSoup(resp.text, "html.parser")
    all_links = soup.find_all("a", href=True)
    file_links = [
        a for a in all_links
        if ".pdf" in a["href"].lower()
        or "download_file_division" in a["href"].lower()
        or "upload" in a["href"].lower()
    ]

    print(f"\n[+] <a> tags total            : {len(all_links)}")
    print(f"[+] <a> tags pointing to files: {len(file_links)}")

    if file_links:
        print("\n[*] ALL file links found:")
        for i, a in enumerate(file_links, 1):
            href = a["href"].strip()
            text = a.get_text(strip=True)[:70] or "(no text)"
            print(f"  [{i:2}] text: {text!r}")
            print(f"       href: {href[:120]}")

    (OUTPUT_DIR / "banned_response_metadata.txt").write_text(
        f"URL: {URL}\n"
        f"Status: {resp.status_code}\n"
        f"Size: {len(resp.content)} bytes\n"
        f"Content-Type: {resp.headers.get('Content-Type')}\n"
        f"Server: {resp.headers.get('Server')}\n"
        f"Timestamp: {datetime.now().isoformat()}\n"
        f"Table count: {table_count}\n"
        f"PDF count: {pdf_count}\n"
        f"download_file_division count: {jsp_count}\n"
        f"Total <a> tags: {len(all_links)}\n"
        f"File-pointing <a> tags: {len(file_links)}\n",
        encoding="utf-8",
    )
    print(f"\n[+] Metadata saved to: {OUTPUT_DIR / 'banned_response_metadata.txt'}")

except requests.exceptions.RequestException as e:
    print(f"[-] Request failed: {e}")