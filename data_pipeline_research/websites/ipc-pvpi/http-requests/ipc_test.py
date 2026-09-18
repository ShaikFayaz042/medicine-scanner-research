"""
IPC PvPI Drug Safety Alerts — HTTP Request Test (v2)

Target: https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html

Purpose:
  - Fetch the main page and save raw HTML.
  - Identify whether PDF links are present in static HTML
    or if JS rendering is required.
  - Extract and count:
      * All .pdf hrefs (with absolute URL resolution)
      * Year-wise "Drug Alerts YYYY" links
      * The master "List of Drugs Safety Alerts" PDF (if present)
  - Print a clear verdict on static vs. JS-rendered content.
"""

import re
from pathlib import Path
from urllib.parse import urljoin, unquote

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


def fetch_page(url: str) -> requests.Response:
    print(f"[*] Fetching: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        print(f"[!] Request failed: {exc}")
        raise SystemExit(1)

    print(f"[+] Status       : {resp.status_code}")
    print(f"[+] Size         : {len(resp.content):,} bytes")
    print(f"[+] Content-Type : {resp.headers.get('Content-Type')}")
    return resp


def extract_all_pdf_urls(html: str, base_url: str) -> list[str]:
    """Return absolute URLs for every .pdf link found in the HTML."""
    urls = []
    for m in re.finditer(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I):
        raw = m.group(1).strip()
        abs_url = urljoin(base_url, raw)
        urls.append(abs_url)
    return urls


def extract_year_links(html: str, base_url: str) -> list[dict]:
    """Find 'Drug Alerts YYYY' links on the main page."""
    pattern = (
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*'
        r'Drug\s+Alerts?\s+(\d{4})\s*</a>'
    )
    links = []
    seen = set()
    for m in re.finditer(pattern, html, re.I):
        raw_url, year = m.group(1), m.group(2)
        abs_url = urljoin(base_url, raw_url)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        links.append({"year": year, "url": abs_url})
    return links


def find_master_pdf(pdf_urls: list[str]) -> str | None:
    """Look for the master 'List of Drugs Safety Alerts' PDF."""
    for u in pdf_urls:
        fname = unquote(u.rsplit("/", 1)[-1].split("?")[0]).lower()
        if "list-of-drugs-safety-alerts" in fname or "list_of_drugs_safety_alerts" in fname:
            return u
    return None


def main() -> None:
    resp = fetch_page(URL)
    html = resp.text

    # Save raw HTML for offline analysis
    OUT_FILE.write_text(html, encoding="utf-8")
    print(f"[+] Saved to     : {OUT_FILE}")

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

    # --- All PDF URLs ---
    pdf_urls = extract_all_pdf_urls(html, URL)
    print(f"\n[+] PDF links found in static HTML: {len(pdf_urls)}")
    for u in pdf_urls[:20]:
        print(f"    {u}")
    if len(pdf_urls) > 20:
        print(f"    ... and {len(pdf_urls) - 20} more")

    # --- Year links ---
    year_links = extract_year_links(html, URL)
    print(f"\n[+] Year-wise 'Drug Alerts' links found: {len(year_links)}")
    for yl in year_links:
        print(f"    {yl['year']}: {yl['url']}")

    # --- Master PDF ---
    master = find_master_pdf(pdf_urls)
    if master:
        print(f"\n[✓] Master PDF found: {master}")
    else:
        print("\n[!] Master PDF (List of Drugs Safety Alerts) NOT found in static HTML.")

    # --- Verdict ---
    if pdf_urls:
        print("\n[✓] PDFs available in static HTML — no JS needed")
    elif year_links:
        print("\n[!] Year links found — follow them (may need JS for year pages)")
    else:
        print("\n[✗] No PDFs / year links in static HTML")
        print("    → Content is JS-rendered. Playwright will be needed.")
        print("    → Or use direct PDF URL (see parse script fallback).")


if __name__ == "__main__":
    main()