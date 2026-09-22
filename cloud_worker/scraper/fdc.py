"""CDSCO Fixed Dose Combination source discovery."""
import base64
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from cloud_worker.config import CDSCO_FDC_URL, USER_AGENT
from cloud_worker.scraper.records import DiscoveredRecord, make_document_record

BASE_URL = "https://cdsco.gov.in"
SOURCE_POSITIONS = (5, 6)
FDC_TABLES = (
    ("Alerts", "example", "DRUG_ALERT"),
    ("News", "example1", "FDC_NOTIFICATION"),
    ("Public Notices", "example2", "FDC_NOTIFICATION"),
    ("Gazette Notifications", "example3", "GAZETTE_LEGAL"),
)


def scrape_fdc(
    limit: int | None = None,
    positions: tuple[int, ...] = SOURCE_POSITIONS,
) -> list[DiscoveredRecord]:
    """Fetch and extract all four FDC tables from one HTML response."""
    response = requests.get(
        CDSCO_FDC_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    records: list[DiscoveredRecord] = []

    for tab_name, table_id, document_type in FDC_TABLES:
        table = soup.find("table", id=table_id)
        tbody = table.find("tbody") if table is not None else None
        if tbody is None:
            continue

        for row_number, row in enumerate(tbody.find_all("tr"), start=1):
            if row_number not in positions:
                continue
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            anchor = cells[3].find("a")
            raw_href = anchor.get("href", "").strip() if anchor else ""
            if not raw_href or "num_id=" not in raw_href:
                continue

            num_id_b64 = raw_href.split("num_id=", 1)[1].split("&", 1)[0]
            try:
                document_id = int(base64.b64decode(num_id_b64).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, base64.binascii.Error):
                continue

            records.append(
                make_document_record(
                    source="cdsco_fdc",
                    source_key=f"cdsco:{document_id}",
                    document_id=document_id,
                    title=cells[1].get_text(strip=True),
                    release_date=cells[2].get_text(strip=True),
                    pdf_url=urljoin(BASE_URL, raw_href),
                    pdf_size_declared=cells[4].get_text(strip=True),
                    document_type=document_type,
                    metadata={"tab": tab_name, "num_id_b64": num_id_b64},
                )
            )

            if limit is not None and len(records) >= limit:
                return records

    return records