"""
CDSCO Public Notices - HTML Extraction with keyword filter.

Only keeps notices whose title suggests a drug safety / enforcement action.
Skips cosmetics, medical devices, SUGAM admin, ethics committees, etc.
"""

import base64
import json
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

INPUT_HTML = Path("websites/cdsco-public-notices/http-requests/output/pn_page.html")
OUTPUT_DIR = Path("websites/cdsco-public-notices/html-extraction/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://cdsco.gov.in"

# --- Full extraction. No relevance filtering applied. ---


def main():
    if not INPUT_HTML.exists():
        raise SystemExit(f"[!] {INPUT_HTML} not found. Run pn_test.py first.")

    html = INPUT_HTML.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # Public Notices uses the same table pattern as Alerts/FDC
    table = soup.find("table", id="example")
    if table is None:
        # Fallback: find the largest table
        tables = soup.find_all("table")
        if not tables:
            raise SystemExit("[!] No tables found in HTML.")
        table = max(tables, key=lambda t: len(t.find_all("tr")))

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")

    all_records = []
    kept_records = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        anchor = cells[3].find("a")
        if not (anchor and anchor.get("href")):
            continue

        raw_href = anchor["href"].strip()
        pdf_url = urljoin(BASE_URL, raw_href)

        num_id_b64 = ""
        document_id = None
        if "num_id=" in raw_href:
            num_id_b64 = raw_href.split("num_id=")[1].split("&")[0]
            try:
                document_id = int(base64.b64decode(num_id_b64).decode("utf-8"))
            except Exception:
                pass

        record = {
            "sno":                 cells[0].get_text(strip=True),
            "title":               cells[1].get_text(strip=True),
            "release_date":        cells[2].get_text(strip=True),
            "pdf_url":             pdf_url,
            "num_id_b64":          num_id_b64,
            "document_id":         document_id,
            "pdf_size_declared":   cells[4].get_text(strip=True),
        }
        all_records.append(record)

    (OUTPUT_DIR / "pn_all.json").write_text(
        json.dumps(all_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[*] Total rows parsed : {len(all_records)}")
    print(f"[+] All saved to : {OUTPUT_DIR / 'pn_all.json'}")
    print("\n[*] First few notices:")
    for r in all_records[:10]:
        print(f"    {r['release_date']}  {r['title'][:80]}")


if __name__ == "__main__":
    main()