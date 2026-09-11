"""
CDSCO NSQ Drugs - Iframe Source Test
Target: https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug
Purpose: Determine whether the NSQ data is in the iframe HTML,
         or if it's loaded dynamically via AJAX.
"""

import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

URL = "https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug"

OUTPUT_DIR = Path("websites/cdsco-nsq/http-requests/output")
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
    print(f"[+] Response Size   : {len(resp.content):,} bytes")
    print(f"[+] Content-Type    : {resp.headers.get('Content-Type', 'N/A')}")
    print(f"[+] Server          : {resp.headers.get('Server', 'N/A')}")

    html_file = OUTPUT_DIR / "nsq_iframe_page.html"
    html_file.write_text(resp.text, encoding="utf-8")
    print(f"[+] Raw HTML saved  : {html_file}")

    html_lower = resp.text.lower()

    print("\n[*] Structural counts:")
    for label, needle in [
        ("<table>",       "<table"),
        ("<form>",        "<form"),
        ("<select>",      "<select"),
        ("<input>",       "<input"),
        ("<iframe>",      "<iframe"),
        ("ajax",          "ajax"),
        ("fetch(",        "fetch("),
        ("xhr",           "xhr"),
        ("$.get",         "$.get"),
        ("$.post",        "$.post"),
        ("url:",          "url:"),
        ("datatable",     "datatable"),
    ]:
        print(f"    {label:20} : {html_lower.count(needle)}")

    print("\n[*] Keyword presence:")
    for kw in ["nsq", "spurious", "batch", "manufacturer",
               "select year", "select month", "apply filter",
               "pending states", "datatable"]:
        print(f"    {kw!r:25} : {'FOUND' if kw in html_lower else 'not found'}")

    # Inspect tables
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    print(f"\n[*] Tables found: {len(tables)}")
    for i, t in enumerate(tables, 1):
        tid = t.get("id") or "(no id)"
        tbody = t.find("tbody")
        rows = tbody.find_all("tr") if tbody else []
        print(f"  [{i}] id={tid!r}  rows={len(rows)}")

    # Scan scripts for endpoints
    print("\n[*] Endpoint hints in <script> tags:")
    for s in soup.find_all("script"):
        txt = s.string or ""
        for token in ["url", "action", "ajax", "fetch", "/CDSCO/", ".do", ".json"]:
            if token.lower() in txt.lower():
                for line in txt.split("\n"):
                    if token.lower() in line.lower() and len(line.strip()) > 10:
                        print(f"    {line.strip()[:150]}")
                break

    (OUTPUT_DIR / "nsq_iframe_metadata.txt").write_text(
        f"URL: {URL}\n"
        f"Status: {resp.status_code}\n"
        f"Size: {len(resp.content)} bytes\n"
        f"Tables: {len(tables)}\n",
        encoding="utf-8",
    )
    print(f"\n[+] Metadata saved.")

except requests.exceptions.RequestException as e:
    print(f"[-] Request failed: {e}")