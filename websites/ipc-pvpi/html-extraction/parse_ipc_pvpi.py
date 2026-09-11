"""
IPC PvPI Drug Safety Alerts — Extraction

Strategy:
  1. Extract PDF links from the static main page HTML
  2. Follow each "Drug Alerts YYYY" year link and extract PDFs from
     that year page
  3. Filter out non-drug-alert PDFs (reference substances, forms,
     guidance docs from the sidebar menu)
  4. Merge + dedupe by absolute URL

The page is Joomla-based, static HTML only. No JS rendering needed.
Confirmed by ipc_test.py (HTTP 200, all PDFs visible in HTML).

Fixes applied (v2):
  - Added is_drug_alert() filter. The main page's navigation sidebar
    links to several non-DSA PDFs (IP reference substances list,
    supply order forms, phytopharmaceutical guidance). Those were
    leaking into ipc_pdfs.json. Now filtered out.
  - Dropped probe_direct_pdfs() — it was a fallback that never
    triggered in practice and duplicated the master PDF already
    found in static HTML.
"""

import json
import re
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests

INPUT_HTML = Path("websites/ipc-pvpi/http-requests/output/ipc_page.html")
OUTPUT_DIR = Path("websites/ipc-pvpi/html-extraction/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE_URL = (
    "https://www.ipc.gov.in/"
    "mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


# --- Filter ---

# Substrings that indicate a true PvPI Drug Safety Alert PDF.
KEEP_URL_HINTS = [
    "/pvpi/",              # canonical location of PvPI PDFs
    "drug_safety_alert",
    "drug-safety-alert",
    "drugs_safety_alert",
    "drugs-safety-alert",
    "drug_alert",          # older naming
    "drug-alert",
    "dsa",                 # dsa_may_2019.pdf etc. — but only as filename
    "monthly_drug_safety_alert",
]

# Substrings that always indicate NOT a drug safety alert, even if
# another hint matches.
DROP_URL_HINTS = [
    "ip-reference-substances",
    "imp-rs",
    "reference-substances",
    "phytopharmaceutical",
    "supply-order",
    "prednisone",
    "impurity",
]


def is_drug_alert(pdf_url: str) -> bool:
    """Decide if a PDF URL is a PvPI Drug Safety Alert.

    The main page's left navigation and sidebar link to unrelated
    PDFs (IP reference substances, forms, guidance). Those are
    served from /images/, /images/pdf/, etc., and their filenames
    don't contain the DSA keyword patterns.
    """
    u = pdf_url.lower()
    fname = u.rsplit("/", 1)[-1]

    # Hard reject
    for drop in DROP_URL_HINTS:
        if drop in u:
            return False

    # Canonical /pvpi/ path — always a drug alert
    if "/pvpi/" in u:
        return True

    # Filename patterns
    for keep in KEEP_URL_HINTS:
        if keep == "dsa":
            # "dsa" as filename prefix only (dsa_may_2019.pdf)
            if fname.startswith("dsa"):
                return True
            continue
        if keep in u:
            return True

    return False


# --- Extractors ---

def extract_pdfs(html: str, page_url: str) -> list[dict]:
    """Find all .pdf hrefs in HTML, resolve to absolute URLs, filter."""
    found = []
    seen = set()
    for m in re.finditer(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I):
        raw = m.group(1).strip()
        url = urljoin(page_url, raw)
        if url in seen:
            continue
        seen.add(url)

        if not is_drug_alert(url):
            continue

        # Filename from URL, URL-decoded so "%20" becomes " "
        fname = unquote(url.split("/")[-1].split("?")[0])

        found.append({
            "pdf_url":  url,
            "filename": fname,
        })
    return found


def extract_year_links(html: str, page_url: str) -> list[dict]:
    """Find 'Drug Alerts YYYY' links on the main page."""
    found = []
    seen = set()
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*Drug\s+Alerts?\s+(\d{4})\s*</a>',
        html, re.I
    ):
        raw_url, year = m.group(1), m.group(2)
        url = urljoin(page_url, raw_url)
        if url in seen:
            continue
        seen.add(url)
        found.append({"year": year, "url": url})
    return found


# --- Main ---

def main():
    if not INPUT_HTML.exists():
        raise SystemExit(f"[!] {INPUT_HTML} not found. Run ipc_test.py first.")

    html = INPUT_HTML.read_text(encoding="utf-8", errors="ignore")

    print("[*] Extracting from saved HTML...")
    pdfs = extract_pdfs(html, PAGE_URL)
    year_links = extract_year_links(html, PAGE_URL)

    print(f"[*] Relevant PDFs in static HTML: {len(pdfs)}")
    print(f"[*] Year links in static HTML   : {len(year_links)}")

    # --- Follow year links ---
    year_pdfs = []
    if year_links:
        print(f"\n[*] Following {len(year_links)} year link(s)...")
        for yl in year_links:
            print(f"    {yl['year']}: {yl['url']}")
            try:
                r = requests.get(yl["url"], headers=HEADERS, timeout=20)
            except Exception as exc:
                print(f"       -> error: {exc}")
                continue

            if r.status_code != 200:
                print(f"       -> HTTP {r.status_code}")
                continue

            y_pdfs = extract_pdfs(r.text, yl["url"])
            for p in y_pdfs:
                p["year"] = yl["year"]
                p["source"] = "year_page"
            year_pdfs.extend(y_pdfs)
            print(f"       -> {len(y_pdfs)} PDF(s)")

    # --- Merge + dedupe by URL ---
    all_pdfs: dict[str, dict] = {}

    for p in pdfs:
        p.setdefault("source", "main_page")
        p.setdefault("year", "")
        all_pdfs[p["pdf_url"]] = p

    for p in year_pdfs:
        # Prefer year_page entry over main_page entry if same URL,
        # because year_page has the year attached.
        all_pdfs[p["pdf_url"]] = p

    all_pdfs_list = sorted(
        all_pdfs.values(),
        key=lambda p: (p.get("year") or "0", p["filename"]),
        reverse=True,
    )

    # --- Save ---
    out_json = OUTPUT_DIR / "ipc_pdfs.json"
    out_json.write_text(
        json.dumps(all_pdfs_list, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Master PDF is a specific one
    master_pdf = next(
        (p for p in all_pdfs_list
         if "list-of-drugs-safety-alerts" in p["filename"].lower()),
        None,
    )

    print(f"\n[*] Total unique Drug Safety Alert PDFs: {len(all_pdfs_list)}")
    if master_pdf:
        print(f"[*] Master PDF found: {master_pdf['filename']}")
    print(f"[+] Saved to: {out_json}")

    print("\n[*] Sample of extracted PDFs (top 15):")
    for p in all_pdfs_list[:15]:
        src = p.get("source", "?")
        year = p.get("year") or "?"
        print(f"    [{src}/{year}] {p['filename']}")


if __name__ == "__main__":
    main()