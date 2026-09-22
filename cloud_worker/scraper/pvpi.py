"""IPC/PvPI Drug Safety Alerts static HTML crawler."""
import re
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from cloud_worker.config import IPC_PVPI_URL, USER_AGENT
from cloud_worker.scraper.records import DiscoveredRecord

DROP_HINTS = (
    "ip-reference-substances",
    "imp-rs",
    "reference-substances",
    "phytopharmaceutical",
    "supply-order",
    "prednisone",
    "impurity",
)
MASTER_HINT = "list-of-drugs-safety-alert"
PVPI_POSITIONS = (2,)


def _fetch(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def _pdf_links(
    html: str,
    page_url: str,
    require_alert_hint: bool,
    skip_master: bool = True,
) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = anchor["href"].strip()
        if ".pdf" not in raw_href.lower():
            continue
        pdf_url = urljoin(page_url, raw_href)
        lowered = pdf_url.casefold()
        if (skip_master and MASTER_HINT in lowered) or any(hint in lowered for hint in DROP_HINTS):
            continue
        text = anchor.get_text(" ", strip=True)
        if require_alert_hint and "alert" not in f"{lowered} {text.casefold()}":
            filename = unquote(urlsplit(pdf_url).path.rsplit("/", 1)[-1])
            if not re.match(r"dsa\d{4}", filename, re.I):
                continue
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        links.append((pdf_url, text))

    return links


def _year_links(html: str, page_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        match = re.search(r"Drug\s+Alerts?\s+(20\d{2})", text, re.I)
        if not match:
            continue
        url = urljoin(page_url, anchor["href"].strip())
        if url not in seen:
            seen.add(url)
            links.append((match.group(1), url))
    return links


def scrape_pvpi(limit: int | None = None) -> list[DiscoveredRecord]:
    """Discover selected alert PDFs from every PvPI year page."""
    main_html = _fetch(IPC_PVPI_URL)
    records: list[DiscoveredRecord] = []
    seen: set[str] = set()

    def add_pdf(pdf_url: str, title: str, year: str | None, kind: str) -> bool:
        if pdf_url in seen:
            return False
        seen.add(pdf_url)
        filename = unquote(urlsplit(pdf_url).path.rsplit("/", 1)[-1])
        records.append(
            {
                "source": "ipc_pvpi",
                "source_key": f"ipc_pvpi:{pdf_url}",
                "title": title or filename,
                "pdf_url": pdf_url,
                "document_type": "PVPI_SAFETY",
                "metadata": {"filename": filename, "year": year, "kind": kind},
            }
        )
        return limit is not None and len(records) >= limit

    year_links = _year_links(main_html, IPC_PVPI_URL)
    latest_year, latest_year_url = max(year_links, default=(None, None))
    if latest_year_url is None:
        return records

    year_html = _fetch(latest_year_url)
    alert_links = _pdf_links(year_html, latest_year_url, require_alert_hint=True)
    for position in PVPI_POSITIONS:
        if position <= len(alert_links):
            pdf_url, text = alert_links[position - 1]
            if add_pdf(pdf_url, text, latest_year, "monthly"):
                return records

    return records