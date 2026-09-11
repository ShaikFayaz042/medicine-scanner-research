"""
CDSCO Public Notices Page - HTTP Request Test
Target: https://cdsco.gov.in/opencms/opencms/en/Notifications/Public-Notices/
Purpose: Verify page structure — expect Pattern A (table of wrapped PDFs).
"""

import requests
from pathlib import Path
from bs4 import BeautifulSoup

URL = "https://cdsco.gov.in/opencms/opencms/en/Notifications/Public-Notices/"

OUTPUT_DIR = Path("websites/cdsco-public-notices/http-requests/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

print(f"[*] Fetching: {URL}")
resp = requests.get(URL, headers=HEADERS, timeout=30)

print(f"\n[+] Status      : {resp.status_code}")
print(f"[+] Size        : {len(resp.content):,} bytes")
print(f"[+] Content-Type: {resp.headers.get('Content-Type')}")

html_file = OUTPUT_DIR / "pn_page.html"
html_file.write_text(resp.text, encoding="utf-8")
print(f"[+] Saved to    : {html_file}")

html_lower = resp.text.lower()

print("\n[*] Structural counts:")
for label, needle in [
    ("<table>",                   "<table"),
    ("<iframe>",                  "<iframe"),
    ("<form>",                    "<form"),
    ("<select>",                  "<select"),
    (".pdf",                      ".pdf"),
    ("download_file_division",    "download_file_division"),
    ("num_id=",                   "num_id="),
    ("ajax",                      "ajax"),
    ("datatable",                 "datatable"),
]:
    print(f"    {label:28} : {html_lower.count(needle)}")

soup = BeautifulSoup(resp.text, "html.parser")
tables = soup.find_all("table")
print(f"\n[*] Tables found: {len(tables)}")
for i, t in enumerate(tables, 1):
    tid = t.get("id") or "(no id)"
    tbody = t.find("tbody")
    rows = tbody.find_all("tr") if tbody else []
    print(f"    [{i}] id={tid!r}  rows={len(rows)}")

# Sample a few PDF links
links = soup.find_all("a", href=True)
pdf_links = [
    a for a in links
    if "download_file_division" in a["href"] or ".pdf" in a["href"].lower()
]
print(f"\n[+] PDF-style links found: {len(pdf_links)}")
for a in pdf_links[:3]:
    print(f"    {a['href'][:100]}")