"""CDSCO Banned Drugs single-PDF discovery and hash tracking."""
import hashlib
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from cloud_worker.config import CDSCO_BANNED_DRUGS_URL, USER_AGENT
from cloud_worker.scraper.records import DiscoveredRecord


def scrape_banned_drugs() -> DiscoveredRecord:
    """Fetch the current banned-drugs PDF and return its content hash."""
    headers = {"User-Agent": USER_AGENT}
    page = requests.get(CDSCO_BANNED_DRUGS_URL, headers=headers, timeout=30)
    page.raise_for_status()

    soup = BeautifulSoup(page.text, "html.parser")
    iframe = soup.find("iframe")
    if iframe is None or not iframe.get("src"):
        raise RuntimeError("Could not find the Banned Drugs PDF iframe.")

    pdf_url = urljoin(CDSCO_BANNED_DRUGS_URL, iframe["src"].strip())
    pdf = requests.get(pdf_url, headers=headers, timeout=60)
    pdf.raise_for_status()
    if not pdf.content.startswith(b"%PDF-"):
        raise RuntimeError("Banned Drugs iframe did not return a PDF.")

    content_hash = hashlib.sha256(pdf.content).hexdigest()
    return {
        "source": "cdsco_banned_drugs",
        "source_key": f"cdsco_banned_drugs:{content_hash}",
        "title": "CDSCO List of Drugs Prohibited for Manufacture and Sale",
        "pdf_url": pdf_url,
        "document_type": "FDC_PROHIBITED",
        "metadata": {
            "content_hash": content_hash,
            "file_size_bytes": len(pdf.content),
            "legal_statuses": [
                "PROHIBITED",
                "STAYED",
                "QUASHED",
                "REVOKED_WITH_CONDITIONS",
            ],
        },
    }