"""
IPC PvPI Drug Safety Alerts — HTTP Request Test
Target: https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html
Purpose: Check if PDF links are present in static HTML or if JS rendering is needed.
"""

import re
from pathlib import Path

import requests

URL = "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html"

OUT_DIR = Path(__file__).resolve().parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "ipc_page.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

print(f"[*] Fetching: {URL}")

try:
    response = requests.get(URL, headers=HEADERS, timeout=30)
except requests.RequestException as exc:
    print(f"[!] Request failed: {exc}")
    raise SystemExit(1)

html = response.text

print(f"[+] Status      : {response.status_code}")
print(f"[+] Size        : {len(response.content):,} bytes")
print(f"[+] Content-Type: {response.headers.get('Content-Type')}")
print(f"[+] Saved to    : {OUT_FILE}")

OUT_FILE.write_text(html, encoding="utf-8")

# --- Structural counts ---
print("\n[*] Structural counts:")
patterns = {
    ".pdf (any)":          r"\.pdf",
    "Drug Alerts":         r"[Dd]rug\s+[Aa]lerts",
    "/images/pvpi/":       r"/images/pvpi/",
    "download_file":       r"download_file",
    "iframe":              r"<iframe\b",
    "table":               r"<table\b",
    "script (inline)":     r"<script\b",
    "2016":                r"2016",
    "2026":                r"2026",
}
for label, pat in patterns.items():
    count = len(re.findall(pat, html, re.I))
    print(f"    {label:22}: {count}")

# --- Extract all PDF URLs from raw HTML ---
pdf_urls = re.findall(
    r'href=["\']([^"\']*\.pdf[^"\']*)["\']',
    html, re.IGNORECASE
)
print(f"\n[+] PDF links found in static HTML: {len(pdf_urls)}")
for u in pdf_urls[:10]:
    print(f"    {u}")

# --- Extract all "Drug Alerts" links (year links) ---
year_links = re.findall(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*Drug\s+Alerts?\s+(\d{4})\s*</a>',
    html, re.IGNORECASE
)
print(f"\n[+] Year-wise 'Drug Alerts' links found: {len(year_links)}")
for url, year in year_links:
    print(f"    {year}: {url}")

# --- Verdict ---
if pdf_urls:
    print("\n[✓] PDFs available in static HTML — no JS needed")
elif year_links:
    print("\n[!] Year links found — follow them (may need JS for year pages)")
else:
    print("\n[✗] No PDFs / year links in static HTML")
    print("    → Content is JS-rendered. Playwright will be needed.")
    print("    → Or use direct PDF URL (see parse script fallback).")