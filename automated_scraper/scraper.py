"""CDSCO Alerts scraper — returns structured records from the live page."""
import base64
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from automated_scraper.config import CDSCO_ALERTS_URL, USER_AGENT

BASE_URL = "https://cdsco.gov.in"


def scrape_alerts(limit: int | None = None) -> list[dict]:
    """
    Fetch the CDSCO Alerts page and extract structured records.

    Args:
        limit: if provided, return only the first N records (newest first).

    Returns list of dicts:
        document_id, title, release_date, pdf_url,
        num_id_b64, pdf_size_declared
    """
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(CDSCO_ALERTS_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", id="example")
    if table is None:
        raise RuntimeError("Could not find <table id='example'> on CDSCO Alerts page.")

    rows = table.find("tbody").find_all("tr")
    records = []

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
                document_id = None

        if document_id is None:
            continue

        records.append({
            "document_id": document_id,
            "title": cells[1].get_text(strip=True),
            "release_date": cells[2].get_text(strip=True),
            "pdf_url": pdf_url,
            "num_id_b64": num_id_b64,
            "pdf_size_declared": cells[4].get_text(strip=True),
        })

        if limit is not None and len(records) >= limit:
            break

    return records