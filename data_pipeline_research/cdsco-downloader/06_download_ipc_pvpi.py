#!/usr/bin/env python3
"""
Download all PDFs from IPC PvPI Drug Safety Alerts page.
Source: https://ipc.gov.in/.../drug-safety-alerts.html
Also supports the direct master PDF URL.
"""

import sys
import logging
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bs4 import BeautifulSoup
from tqdm import tqdm

import cdsco_utils as cu

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Replace with the actual PvPI page URL
SOURCE_URL = (
    "https://ipc.gov.in/images/pvpi/drug-safety-alerts.html"
)
# Optional: direct master PDF to always download
MASTER_PDF = (
    "https://ipc.gov.in/images/pvpi/"
    "List-of-Drugs-Safety-Alerts-issued-by-PvPI-from-"
    "March-2016-to-till-date---27.07.2026.pdf"
)

OUT_DIR = cu.ensure_dir(cu.DOWNLOADS_ROOT / "ipc_pvpi")


def download_url(url: str, referer: str | None = None) -> None:
    """Download a single PDF URL into OUT_DIR."""
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename.lower().endswith(".pdf"):
        return
    dest = OUT_DIR / filename
    if dest.exists():
        log.info("Skipping existing %s", dest.name)
        return
    ok = cu.download_pdf(url, dest, referer=referer)
    if ok:
        log.info("Downloaded %s", dest.name)
    else:
        log.error("Failed to download %s", url)
    time.sleep(cu.DELAY)


def main():
    records = []

    # 1. Master PDF (always)
    if MASTER_PDF:
        download_url(MASTER_PDF, referer=SOURCE_URL)
        records.append({
            "source": "ipc_pvpi",
            "type": "master",
            "pdf_url": MASTER_PDF,
            "local_path": str(OUT_DIR / Path(urlparse(MASTER_PDF).path).name),
        })

    # 2. All PDF links from the page
    log.info("Fetching %s", SOURCE_URL)
    resp = cu.SESSION.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.find_all("a", href=True)
    pdf_links = [
        urljoin(SOURCE_URL, a["href"].strip())
        for a in links
        if a["href"].strip().lower().endswith(".pdf")
    ]

    log.info("Found %d PDF links on page", len(pdf_links))
    for url in tqdm(pdf_links, desc="IPC PvPI"):
        download_url(url, referer=SOURCE_URL)
        records.append({
            "source": "ipc_pvpi",
            "type": "yearly",
            "pdf_url": url,
            "local_path": str(OUT_DIR / Path(urlparse(url).path).name),
        })

    cu.save_metadata(records, OUT_DIR / "_metadata.json")
    log.info("Done. %d PDFs processed.", len(records))


if __name__ == "__main__":
    main()