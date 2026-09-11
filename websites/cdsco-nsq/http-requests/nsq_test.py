"""
CDSCO NSQ Drugs Page - HTTP Request Experiment
Target: https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/
Purpose: Determine whether the NSQ table is server-rendered HTML,
         whether both tabs are present, and whether filters use AJAX.
"""

import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

URL = "https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/"

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
resp = requests.get(URL, headers=HEADERS, timeout=30)

print(f"\n[+] HTTP Status     : {resp.status_code}")
print(f"[+] Response Size   : {len(resp.content):,} bytes "
      f"({len(resp.content)/1024:.2f} KB)")
print(f"[+] Content-Type    : {resp.headers.get('Content-Type', 'N/A')}")
print(f"[+] Server          : {resp.headers.get('Server', 'N/A')}")

html_file = OUTPUT_DIR / "nsq_page.html"
html_file.write_text(resp.text, encoding="utf-8")
print(f"\n[+] Raw HTML saved  : {html_file}")

# --- Save raw HTML ---
html_lower = resp.text.lower()

print("\n[*] Structural counts:")
for label, needle in [
    ("<table>",       "<table"),
    ("<form>",        "<form"),
    ("<select>",      "<select"),
    ("<input>",       "<input"),
    ("<iframe>",      "<iframe"),
    (".pdf",          ".pdf"),
    ("download_file_division", "download_file_division"),
    ("ajax",          "ajax"),
    ("fetch(",        "fetch("),
    ("xhr",           "xhr"),
    ("$.get",         "$.get"),
    ("$.post",        "$.post"),
    ("datatable",     "datatable"),
]:
    print(f"    {label:28} : {html_lower.count(needle)}")

# --- Keywords ---
print("\n[*] Keyword presence:")
for kw in ["nsq", "spurious", "not of standard quality",
           "batch", "manufacturer", "reporting month",
           "select year", "select month", "reporting source",
           "apply filter", "pending states"]:
    print(f"    {kw!r:35} : {'FOUND' if kw in html_lower else 'not found'}")

# --- Inspect tables ---
soup = BeautifulSoup(resp.text, "html.parser")
tables = soup.find_all("table")
print(f"\n[*] Detailed table inspection ({len(tables)} tables):")
for i, t in enumerate(tables, 1):
    tid = t.get("id") or "(no id)"
    thead = t.find("thead")
    tbody = t.find("tbody")
    rows = tbody.find_all("tr") if tbody else []
    headers = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
    print(f"  [{i}] id={tid!r}  rows={len(rows)}")
    if headers:
        print(f"      headers: {headers}")

# --- Look for AJAX endpoint references in inline scripts ---
print("\n[*] Scanning inline <script> for URLs / endpoints:")
scripts = soup.find_all("script")
endpoint_hints = []
for s in scripts:
    txt = s.string or ""
    for token in ["/opencms", "/api/", ".jsp", ".do", "url:", "action:",
                  "ajax", "href :", "href:"]:
        if token.lower() in txt.lower():
            # crude: grab lines containing the token
            for line in txt.split("\n"):
                if token.lower() in line.lower() and len(line.strip()) > 5:
                    stripped = line.strip()
                    if len(stripped) < 200:
                        endpoint_hints.append(stripped)

if endpoint_hints:
    unique = list(dict.fromkeys(endpoint_hints))[:15]
    for h in unique:
        print(f"    {h}")
else:
    print("    (none found)")

# --- Save metadata ---
(OUTPUT_DIR / "nsq_response_metadata.txt").write_text(
    f"URL: {URL}\n"
    f"Status: {resp.status_code}\n"
    f"Size: {len(resp.content)} bytes\n"
    f"Content-Type: {resp.headers.get('Content-Type')}\n"
    f"Timestamp: {datetime.now().isoformat()}\n"
    f"Tables: {len(tables)}\n",
    encoding="utf-8",
)
print(f"\n[+] Metadata saved to: {OUTPUT_DIR / 'nsq_response_metadata.txt'}")