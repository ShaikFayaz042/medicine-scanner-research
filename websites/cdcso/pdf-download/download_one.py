"""
CDSCO PDF Download Experiment (v2)
Handles the common CDSCO pattern where download_file_division.jsp returns
an HTML wrapper containing an <iframe> that points to the real PDF.
"""

import base64
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Paths ---
ALERTS_JSON = Path("websites/cdcso/html-extraction/output/alerts.json")
OUTPUT_DIR = Path("websites/cdcso/pdf-download/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Targets ---
TARGET_DOCUMENT_IDS = ["13487", "12555"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# --- Load alerts ---
if not ALERTS_JSON.exists():
    raise SystemExit(f"[!] {ALERTS_JSON} not found. Run html-extraction first.")

alerts = json.loads(ALERTS_JSON.read_text(encoding="utf-8"))
by_id = {a["document_id"]: a for a in alerts}


def fetch_pdf(url: str, referer: str = None) -> bytes:
    """
    Fetch a URL and return PDF bytes.
    If the response is an HTML wrapper, parse out the iframe src and recurse once.
    """
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer

    resp = requests.get(url, headers=headers, timeout=60)
    ctype = resp.headers.get("Content-Type", "").lower()
    print(f"    [.] GET {url[:90]}... -> {resp.status_code} {ctype}")

    # Case 1: direct PDF
    if "application/pdf" in ctype or resp.content.startswith(b"%PDF-"):
        return resp.content

    # Case 2: HTML wrapper -> look for iframe
    if "text/html" in ctype:
        soup = BeautifulSoup(resp.text, "html.parser")
        iframe = soup.find("iframe")
        if iframe and iframe.get("src"):
            inner = iframe["src"].strip()
            inner_url = urljoin(url, inner)

            # If the iframe src is a PDF.js viewer, the real file is in a query param
            # e.g. /pdfjs/web/viewer.html?file=/opencms/.../foo.pdf
            if "file=" in inner_url:
                # crude but effective extraction
                file_part = inner_url.split("file=", 1)[1].split("&")[0]
                inner_url = urljoin(url, file_part)

            print(f"    [+] Found iframe -> {inner_url[:90]}...")
            return fetch_pdf(inner_url, referer=url)

        # No iframe: maybe the PDF URL is in a meta refresh or a link
        meta = soup.find("meta", attrs={"http-equiv": "refresh"})
        if meta and "url=" in meta.get("content", "").lower():
            target = meta["content"].split("url=", 1)[1]
            target_url = urljoin(url, target)
            print(f"    [+] Found meta refresh -> {target_url[:90]}...")
            return fetch_pdf(target_url, referer=url)

    raise RuntimeError(
        f"Could not find PDF. Content-Type={ctype}, "
        f"first bytes={resp.content[:80]!r}"
    )


for doc_id in TARGET_DOCUMENT_IDS:
    record = by_id.get(doc_id)
    if not record:
        print(f"[!] document_id {doc_id} not found — skipping")
        continue

    print("=" * 72)
    print(f"[*] document_id : {doc_id}")
    print(f"[*] Title       : {record['title'][:70]}")
    print(f"[*] Declared sz : {record['pdf_size']}")

    try:
        pdf_bytes = fetch_pdf(record["pdf_url"])
    except Exception as e:
        print(f"[-] FAILED: {e}")
        continue

    out_path = OUTPUT_DIR / f"{doc_id}.pdf"
    out_path.write_bytes(pdf_bytes)

    size = len(pdf_bytes)
    print(f"[+] Saved         : {out_path}  ({size:,} bytes)")
    print(f"[+] Magic bytes   : {pdf_bytes[:8]!r}")
    print(f"[+] Valid PDF?    : {'YES' if pdf_bytes.startswith(b'%PDF-') else 'NO'}")

    try:
        declared_kb = int("".join(c for c in record["pdf_size"] if c.isdigit()))
        actual_kb = round(size / 1024)
        diff = abs(actual_kb - declared_kb) / max(declared_kb, 1) * 100
        print(f"[+] Size check    : declared ~{declared_kb} KB, actual {actual_kb} KB "
              f"(diff {diff:.1f}%)")
    except ValueError:
        pass