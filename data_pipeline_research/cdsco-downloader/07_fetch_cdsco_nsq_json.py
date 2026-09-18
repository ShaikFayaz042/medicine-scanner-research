#!/usr/bin/env python3
"""
Fetch NSQ and Spurious drug data from CDSCO JSON API.
No PDFs. Saves JSON per month and combined history.
Source: https://cdscoonline.gov.in
"""

import sys
import json
import logging
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tqdm import tqdm

import cdsco_utils as cu

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE = "https://cdscoonline.gov.in"
OUT_DIR = cu.ensure_dir(cu.DOWNLOADS_ROOT / "nsq_json")

ENDPOINTS = {
    "nsq": "/CDSCO/filteredNsqDrugTable",
    "spurious": "/CDSCO/filteredSpuriousDrugTable",
}


def get_years(tab: str) -> list[str]:
    url = f"{BASE}/CDSCO/reportingYears"
    r = cu.SESSION.get(url, params={"tab": tab}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_months(year: str, tab: str) -> list[str]:
    url = f"{BASE}/CDSCO/publicReportingMonths"
    r = cu.SESSION.get(
        url, params={"year": year, "tab": tab}, timeout=30
    )
    r.raise_for_status()
    return r.json()


def fetch_month(tab: str, month_year: str) -> list[dict]:
    url = BASE + ENDPOINTS[tab]
    params = {"month": month_year, "source": "All", "tab": tab}
    r = cu.SESSION.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("aaData", []) if isinstance(data, dict) else data


def main():
    all_data = {}

    for tab in ["nsq", "spurious"]:
        log.info("Discovering months for %s …", tab)
        years = get_years(tab)
        months_by_year = {}
        for year in years:
            months = get_months(year, tab)
            months_by_year[year] = months

        records = []
        total = sum(len(m) for m in months_by_year.values())
        pbar = tqdm(total=total, desc=f"{tab} months")

        for year, months in months_by_year.items():
            for month in months:
                month_year = f"{month}-{year}"
                try:
                    rows = fetch_month(tab, month_year)
                    records.extend(rows)
                except Exception as exc:
                    log.error("Failed %s %s: %s", tab, month_year, exc)
                pbar.update(1)
                time.sleep(0.3)

        pbar.close()
        all_data[tab] = records
        log.info("%s: %d records", tab, len(records))

        # Save combined JSON
        out = OUT_DIR / f"{tab}_full_history.json"
        out.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Saved %s", out)

    # Also save a summary manifest
    manifest = {
        "nsq_records": len(all_data.get("nsq", [])),
        "spurious_records": len(all_data.get("spurious", [])),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (OUT_DIR / "_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    log.info("Done.")


if __name__ == "__main__":
    main()