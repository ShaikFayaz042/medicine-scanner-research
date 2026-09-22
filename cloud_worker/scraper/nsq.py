"""CDSCO NSQ and spurious-drug JSON API discovery."""
import re
from typing import Any

import requests

from cloud_worker.config import CDSCO_ONLINE_BASE_URL, USER_AGENT
from cloud_worker.scraper.json_handler import upload_json_artifact
from cloud_worker.scraper.records import DiscoveredRecord, make_data_record

API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{CDSCO_ONLINE_BASE_URL}/CDSCO/viewPublicNSQDrug",
}

ENDPOINTS = {
    "nsq": "/CDSCO/publicNsqDrugTable",
    "spurious": "/CDSCO/viewPublicSpuriousDrugData",
}


def _key_part(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _source_key(record_type: str, record: dict[str, Any]) -> str:
    parts = (
        _key_part(record.get("str_product_name") or record.get("product_name_from_dtl")),
        _key_part(record.get("str_batch_no")),
        _key_part(record.get("str_manufactured_by") or record.get("str_manufacturer_name")),
        _key_part(record.get("dt_reporting_month_year")),
    )
    return f"cdsco_{record_type}:" + "|".join(parts)


def _fetch_records(record_type: str) -> list[dict[str, Any]]:
    response = requests.get(
        CDSCO_ONLINE_BASE_URL + ENDPOINTS[record_type],
        headers=API_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("aaData"), list):
        raise RuntimeError(f"Unexpected CDSCO {record_type} API response shape")
    return [item for item in payload["aaData"] if isinstance(item, dict)]


def download_nsq_json() -> dict[str, dict[str, Any]]:
    """Fetch current NSQ and spurious payloads and upload them as JSON."""
    uploaded = {}
    for record_type in ENDPOINTS:
        records = _fetch_records(record_type)
        uploaded[record_type] = upload_json_artifact(
            "cdsco_nsq",
            record_type,
            {"source": "cdsco_nsq", "record_type": record_type, "aaData": records},
        )
    return uploaded


def scrape_nsq(
    *,
    include_spurious: bool = True,
    limit: int | None = None,
) -> list[DiscoveredRecord]:
    """Fetch current NSQ and optionally spurious records from the public API."""
    record_types = ["nsq", "spurious"] if include_spurious else ["nsq"]
    discovered: list[DiscoveredRecord] = []

    for record_type in record_types:
        for raw_record in _fetch_records(record_type):
            metadata = dict(raw_record)
            if record_type == "spurious":
                metadata["legal_status"] = "SPURIOUS_UNDER_INVESTIGATION"

            discovered.append(
                make_data_record(
                    source="cdsco_nsq",
                    source_key=_source_key(record_type, raw_record),
                    record_type="SPURIOUS_ALERT" if record_type == "spurious" else "NSQ_ALERT",
                    metadata=metadata,
                )
            )
            if limit is not None and len(discovered) >= limit:
                return discovered

    return discovered