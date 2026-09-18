"""Download all configured CDSCO and IPC sources into the existing downloads folder.

Existing PDFs are skipped by default. Use --dry-run to inspect source pages
without writing files. This script does not move or delete existing downloads.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = PIPELINE_ROOT / "01_downloads"
CDSCO_BASE = "https://cdsco.gov.in"
CDSCO_WRAPPER = "/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp"
NSQ_BASE = "https://cdscoonline.gov.in"
DELAY = 0.5

SOURCES = {
    "alerts": "https://cdsco.gov.in/opencms/opencms/en/Alerts/",
    "fdc": "https://cdsco.gov.in/opencms/opencms/en/Drugs/FDC/",
    "public_notices": "https://cdsco.gov.in/opencms/opencms/en/Notifications/Public-Notices/",
    "gazette": "https://cdsco.gov.in/opencms/opencms/en/Notifications/Gazette-Notifications/",
    "banned_drugs": "https://cdsco.gov.in/opencms/opencms/en/BannedDrugs",
    "ipc_pvpi": "https://ipc.gov.in/images/pvpi/drug-safety-alerts.html",
    "nsq_json": NSQ_BASE,
}

IPC_MASTER = (
    "https://ipc.gov.in/images/pvpi/"
    "List-of-Drugs-Safety-Alerts-issued-by-PvPI-from-"
    "March-2016-to-till-date---27.07.2026.pdf"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("download_all_sources")


def safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\s.\-]", "", value)
    return re.sub(r"\s+", "_", value.strip())[:120] or "document"


def decode_id(value: str) -> int | None:
    try:
        return int(base64.b64decode(value).decode("utf-8"))
    except Exception:
        return None


def get_num_id(href: str) -> str | None:
    if "num_id=" not in href:
        return None
    return href.split("num_id=", 1)[1].split("&", 1)[0]


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    response = session.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response


def resolve_wrapped_pdf(session: requests.Session, num_id: str, referer: str) -> bytes | None:
    wrapper = f"{CDSCO_BASE}{CDSCO_WRAPPER}?num_id={num_id}"
    for attempt in range(1, 4):
        try:
            response = get(session, wrapper, headers={"Referer": referer})
            if response.content.startswith(b"%PDF-"):
                return response.content
            iframe = BeautifulSoup(response.text, "html.parser").find("iframe", src=True)
            if not iframe:
                log.warning("No iframe found for num_id=%s", num_id)
                return None
            inner = urljoin(wrapper, iframe["src"].strip())
            pdf = get(session, inner, headers={"Referer": wrapper})
            return pdf.content if pdf.content.startswith(b"%PDF-") else None
        except requests.RequestException as exc:
            log.warning("Wrapped PDF attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(2**attempt)
    return None


def save_metadata(source: str, records: list[dict], dry_run: bool, smoke_test: bool = False) -> None:
    if not dry_run:
        filename = "_metadata_smoke_test.json" if smoke_test else "_metadata.json"
        path = DOWNLOADS / source / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def save_wrapped(session: requests.Session, source: str, num_id: str, title: str, referer: str, dry_run: bool, metadata_only: bool = False) -> str:
    document_id = decode_id(num_id)
    destination = DOWNLOADS / source / f"{document_id or 'unknown'}_{safe_filename(title)}.pdf"
    if destination.exists():
        return "existing"
    if dry_run or metadata_only:
        return "planned"
    content = resolve_wrapped_pdf(session, num_id, referer)
    if not content:
        return "failed"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    time.sleep(DELAY)
    return "downloaded"


def table_source(session: requests.Session, source: str, url: str, dry_run: bool, table_id: str = "example", limit: int | None = None, metadata_only: bool = False) -> dict[str, int]:
    soup = BeautifulSoup(get(session, url).text, "html.parser")
    table = soup.find("table", id=table_id)
    if not table:
        raise RuntimeError(f"Table #{table_id} not found at {url}")
    stats = {"existing": 0, "planned": 0, "downloaded": 0, "failed": 0}
    records = []
    rows = table.find("tbody").find_all("tr") if table.find("tbody") else []
    for row in rows[:limit] if limit else rows:
        cells = row.find_all("td")
        anchor = cells[3].find("a", href=True) if len(cells) >= 5 else None
        num_id = get_num_id(anchor["href"].strip()) if anchor else None
        if not num_id:
            continue
        title = cells[1].get_text(strip=True)
        result = save_wrapped(session, source, num_id, title, url, dry_run, metadata_only)
        stats[result] += 1
        records.append({
            "source": source,
            "document_id": decode_id(num_id),
            "num_id_b64": num_id,
            "title": title,
            "release_date": cells[2].get_text(strip=True),
        })
    save_metadata(source, records, dry_run, smoke_test=limit is not None and not metadata_only)
    return stats


def fdc_source(session: requests.Session, dry_run: bool, limit: int | None = None, metadata_only: bool = False) -> dict[str, int]:
    soup = BeautifulSoup(get(session, SOURCES["fdc"]).text, "html.parser")
    stats = {"existing": 0, "planned": 0, "downloaded": 0, "failed": 0}
    records = []
    processed = 0
    for tab, table_id in [("Alerts", "example"), ("News", "example1"), ("Public Notices", "example2"), ("Gazette", "example3")]:
        table = soup.find("table", id=table_id)
        if not table:
            log.warning("FDC table %s not found", table_id)
            continue
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else []
        for row in rows:
            if limit and processed >= limit:
                break
            cells = row.find_all("td")
            anchor = cells[3].find("a", href=True) if len(cells) >= 5 else None
            num_id = get_num_id(anchor["href"].strip()) if anchor else None
            if not num_id:
                continue
            title = cells[1].get_text(strip=True)
            result = save_wrapped(session, "fdc", num_id, title, SOURCES["fdc"], dry_run, metadata_only)
            stats[result] += 1
            processed += 1
            records.append({"source": "fdc", "tab": tab, "document_id": decode_id(num_id), "title": title, "num_id_b64": num_id})
        if limit and processed >= limit:
            break
    save_metadata("fdc", records, dry_run, smoke_test=limit is not None and not metadata_only)
    return stats


def direct_pdf(session: requests.Session, source: str, url: str, dry_run: bool, filename: str | None = None, metadata_only: bool = False) -> str:
    destination = DOWNLOADS / source / (filename or Path(urlparse(url).path).name)
    if destination.exists():
        return "existing"
    if dry_run or metadata_only:
        return "planned"
    response = get(session, url, headers={"Referer": SOURCES[source]})
    if not response.content.startswith(b"%PDF-"):
        return "failed"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    time.sleep(DELAY)
    return "downloaded"


def banned_source(session: requests.Session, dry_run: bool, limit: int | None = None, metadata_only: bool = False) -> dict[str, int]:
    soup = BeautifulSoup(get(session, SOURCES["banned_drugs"]).text, "html.parser")
    iframe = soup.find("iframe", src=True)
    if not iframe:
        raise RuntimeError("Banned Drugs PDF iframe not found")
    url = urljoin(SOURCES["banned_drugs"], iframe["src"].strip())
    result = direct_pdf(session, "banned_drugs", url, dry_run, "banned_drugs.pdf", metadata_only)
    save_metadata("banned_drugs", [{"source": "banned_drugs", "pdf_url": url}], dry_run, smoke_test=limit is not None and not metadata_only)
    return {"existing": int(result == "existing"), "planned": int(result == "planned"), "downloaded": int(result == "downloaded"), "failed": int(result == "failed")}


def ipc_source(session: requests.Session, dry_run: bool, limit: int | None = None, metadata_only: bool = False) -> dict[str, int]:
    stats = {"existing": 0, "planned": 0, "downloaded": 0, "failed": 0}
    records = []
    if not limit or limit >= 1:
        result = direct_pdf(session, "ipc_pvpi", IPC_MASTER, dry_run, metadata_only=metadata_only)
        stats[result] += 1
        records.append({"source": "ipc_pvpi", "type": "master", "pdf_url": IPC_MASTER})
    soup = BeautifulSoup(get(session, SOURCES["ipc_pvpi"]).text, "html.parser")
    urls = sorted({urljoin(SOURCES["ipc_pvpi"], a["href"].strip()) for a in soup.find_all("a", href=True) if a["href"].strip().lower().endswith(".pdf")})
    for url in urls[: max(0, (limit or len(urls)) - 1)]:
        result = direct_pdf(session, "ipc_pvpi", url, dry_run, metadata_only=metadata_only)
        stats[result] += 1
        records.append({"source": "ipc_pvpi", "type": "yearly", "pdf_url": url})
    save_metadata("ipc_pvpi", records, dry_run, smoke_test=limit is not None and not metadata_only)
    return stats


def nsq_source(session: requests.Session, dry_run: bool, limit: int | None = None) -> dict[str, int]:
    stats = {"existing": 0, "planned": 0, "downloaded": 0, "failed": 0}
    if dry_run:
        stats["planned"] = 2
        return stats
    output = DOWNLOADS / "nsq_json"
    output.mkdir(parents=True, exist_ok=True)
    all_data = {}
    endpoints = {"nsq": "/CDSCO/filteredNsqDrugTable", "spurious": "/CDSCO/filteredSpuriousDrugTable"}
    for tab, endpoint in endpoints.items():
        years = get(session, f"{NSQ_BASE}/CDSCO/reportingYears", params={"tab": tab}).json()
        records = []
        months_processed = 0
        for year in years:
            months = get(session, f"{NSQ_BASE}/CDSCO/publicReportingMonths", params={"year": year, "tab": tab}).json()
            for month in months:
                if limit and months_processed >= limit:
                    break
                try:
                    data = get(session, NSQ_BASE + endpoint, params={"month": f"{month}-{year}", "source": "All", "tab": tab}).json()
                    records.extend(data.get("aaData", []) if isinstance(data, dict) else data)
                except requests.RequestException as exc:
                    log.error("Failed %s %s-%s: %s", tab, month, year, exc)
                months_processed += 1
                time.sleep(0.3)
            if limit and months_processed >= limit:
                break
        destination = output / f"{tab}_full_history.json"
        if destination.exists():
            stats["existing"] += 1
        else:
            destination.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
            stats["downloaded"] += 1
        all_data[tab] = records
    manifest_name = "_manifest_smoke_test.json" if limit is not None else "_manifest.json"
    (output / manifest_name).write_text(json.dumps({"nsq_records": len(all_data.get("nsq", [])), "spurious_records": len(all_data.get("spurious", [])), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2), encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Download all CDSCO and IPC sources")
    parser.add_argument("--sources", nargs="+", choices=sorted(SOURCES), default=sorted(SOURCES))
    parser.add_argument("--dry-run", action="store_true", help="Fetch/inspect sources without writing files")
    parser.add_argument("--limit", type=int, default=None, help="Maximum files/items per source; use 1 for a smoke test")
    parser.add_argument("--metadata-only", action="store_true", help="Refresh source metadata without downloading files")
    args = parser.parse_args()
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    handlers = {
        "alerts": lambda: table_source(session, "alerts", SOURCES["alerts"], args.dry_run, limit=args.limit, metadata_only=args.metadata_only),
        "fdc": lambda: fdc_source(session, args.dry_run, args.limit, args.metadata_only),
        "public_notices": lambda: table_source(session, "public_notices", SOURCES["public_notices"], args.dry_run, limit=args.limit, metadata_only=args.metadata_only),
        "gazette": lambda: table_source(session, "gazette", SOURCES["gazette"], args.dry_run, limit=args.limit, metadata_only=args.metadata_only),
        "banned_drugs": lambda: banned_source(session, args.dry_run, args.limit, args.metadata_only),
        "ipc_pvpi": lambda: ipc_source(session, args.dry_run, args.limit, args.metadata_only),
        "nsq_json": lambda: nsq_source(session, args.dry_run, args.limit),
    }
    failures = 0
    for source in args.sources:
        try:
            stats = handlers[source]()
            log.info("%s: %s", source, stats)
            failures += stats["failed"]
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            failures += 1
            log.error("%s failed: %s", source, exc)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
