#!/usr/bin/env python3
"""
Download every PDF from CDSCO Alerts page.
Source: https://cdsco.gov.in/opencms/opencms/en/Alerts/
"""

import sys
import logging
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bs4 import BeautifulSoup
from tqdm import tqdm

import cdsco_utils as cu

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

SOURCE_URL = "https://cdsco.gov.in/opencms/opencms/en/Alerts/"
OUT_DIR = cu.ensure_dir(cu.DOWNLOADS_ROOT / "alerts")


def main():
    log.info("Fetching %s", SOURCE_URL)
    resp = cu.SESSION.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", id="example")
    if not table:
        raise SystemExit("Table #example not found")

    rows = table.find("tbody").find_all("tr")
    records = []

    for row in tqdm(rows, desc="Alerts"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        title = cells[1].get_text(strip=True)
        release_date = cells[2].get_text(strip=True)

        anchor = cells[3].find("a")
        if not anchor or not anchor.get("href"):
            continue

        href = anchor["href"].strip()
        num_id_b64 = cu.extract_num_id_from_href(href)
        if not num_id_b64:
            log.warning("No num_id in href: %s", href)
            continue

        document_id = cu.base64_decode_num_id(num_id_b64)
        safe_title = cu.sanitize_filename(title)
        filename = f"{document_id or 'unknown'}_{safe_title}.pdf"
        dest = OUT_DIR / filename

        if dest.exists():
            log.info("Skipping existing %s", dest.name)
        else:
            pdf_bytes = cu.resolve_cdsco_pdf(
                num_id_b64, referer=SOURCE_URL
            )
            if pdf_bytes:
                dest.write_bytes(pdf_bytes)
                log.info("Downloaded %s", dest.name)
            else:
                log.error("Failed to download %s", title)
            time.sleep(cu.DELAY)

        records.append({
            "document_id": document_id,
            "num_id_b64": num_id_b64,
            "title": title,
            "release_date": release_date,
            "local_path": str(dest),
            "source": "alerts",
        })

    cu.save_metadata(records, OUT_DIR / "_metadata.json")
    log.info("Done. %d records processed.", len(records))


if __name__ == "__main__":
    main()