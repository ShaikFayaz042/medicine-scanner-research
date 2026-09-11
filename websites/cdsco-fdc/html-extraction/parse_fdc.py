"""
CDSCO FDC Page - HTML Extraction Experiment
Input:  websites/cdsco-fdc/http-requests/output/fdc_page.html
Output: 4 JSON files (one per tab)
Purpose: Prove we can extract all four FDC tabs from a single HTTP fetch.
"""

import base64
import json
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# --- Paths ---
INPUT_HTML = Path("websites/cdsco-fdc/http-requests/output/fdc_page.html")
OUTPUT_DIR = Path("websites/cdsco-fdc/html-extraction/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://cdsco.gov.in"

# --- Tab definition: (tab label, HTML table id, output filename) ---
TABS = [
    ("Alerts",                "example",  "fdc_alerts.json"),
    ("News",                  "example1", "fdc_news.json"),
    ("Public Notices",        "example2", "fdc_public_notices.json"),
    ("Gazette Notifications", "example3", "fdc_gazette.json"),
]

if not INPUT_HTML.exists():
    raise SystemExit(
        f"[!] {INPUT_HTML} not found.\n"
        f"    Run websites/cdsco-fdc/http-requests/fdc_test.py first."
    )

html = INPUT_HTML.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

print(f"[*] Parsing: {INPUT_HTML}")
print(f"[*] Looking for {len(TABS)} tables...\n")

summary = []

for tab_label, table_id, out_name in TABS:
    table = soup.find("table", id=table_id)
    if table is None:
        print(f"    [!] Table #{table_id} ({tab_label}) not found — skipping")
        summary.append({"tab": tab_label, "table_id": table_id, "rows": 0, "file": None})
        continue

    tbody = table.find("tbody")
    if tbody is None:
        print(f"    [!] Table #{table_id} ({tab_label}) has no <tbody>")
        summary.append({"tab": tab_label, "table_id": table_id, "rows": 0, "file": None})
        continue

    rows = tbody.find_all("tr")
    records = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        sno = cells[0].get_text(strip=True)
        title = cells[1].get_text(strip=True)
        release_date = cells[2].get_text(strip=True)

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
                document_id = None

        if document_id is None:
            continue

        pdf_size = cells[4].get_text(strip=True)

        records.append({
            "tab": tab_label,
            "sno": sno,
            "document_id": document_id,
            "title": title,
            "release_date": release_date,
            "pdf_url": pdf_url,
            "num_id_b64": num_id_b64,
            "pdf_size_declared": pdf_size,
        })

    # Save per-tab JSON
    out_path = OUTPUT_DIR / out_name
    out_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary.append({
        "tab": tab_label,
        "table_id": table_id,
        "rows": len(records),
        "file": str(out_path),
    })

    print(f"    [+] {tab_label:25} (table #{table_id:9}) : "
          f"{len(records):3} rows → {out_name}")

# --- Combined summary ---
total = sum(s["rows"] for s in summary)
print(f"\n[+] Total rows extracted: {total}")

# --- Sanity: list new document_ids across tabs ---
print("\n[*] Sample (first 2 per tab):")
for tab_label, table_id, out_name in TABS:
    path = OUTPUT_DIR / out_name
    if not path.exists():
        continue
    recs = json.loads(path.read_text(encoding="utf-8"))
    for r in recs[:2]:
        print(f"    [{tab_label}]  {r['document_id']}  "
              f"{r['release_date']}  {r['title'][:55]}")

# --- Save overall summary ---
summary_path = OUTPUT_DIR / "_summary.json"
summary_path.write_text(json.dumps({
    "source_html": str(INPUT_HTML),
    "tabs": summary,
    "total_rows": total,
}, indent=2), encoding="utf-8")
print(f"\n[+] Summary saved to: {summary_path}")