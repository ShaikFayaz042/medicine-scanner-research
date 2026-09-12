#!/usr/bin/env python3
"""
Download the Banned Drugs PDF from CDSCO.
Source: https://cdsco.gov.in/opencms/opencms/en/BannedDrugs
"""

import sys
import logging
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bs4 import BeautifulSoup

import cdsco_utils as cu

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

SOURCE_URL = "https://cdsco.gov.in/opencms/opencms/en/BannedDrugs"
OUT_DIR = cu.ensure_dir(cu.DOWNLOADS_ROOT / "banned_drugs")


def main():
    log.info("Fetching %s", SOURCE_URL)
    resp = cu.SESSION.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    iframe = soup.find("iframe")
    if not iframe or not iframe.get("src"):
        raise SystemExit("No iframe found on Banned Drugs page")

    pdf_url = urljoin(SOURCE_URL, iframe["src"].strip())
    log.info("PDF URL: %s", pdf_url)

    dest = OUT_DIR / "banned_drugs.pdf"
    if dest.exists():
        log.info("Already exists: %s", dest)
    else:
        ok = cu.download_pdf(pdf_url, dest, referer=SOURCE_URL)
        if ok:
            log.info("Downloaded %s", dest)
        else:
            log.error("Download failed")

    # metadata
    cu.save_metadata([{
        "source": "banned_drugs",
        "pdf_url": pdf_url,
        "local_path": str(dest),
    }], OUT_DIR / "_metadata.json")


if __name__ == "__main__":
    main()