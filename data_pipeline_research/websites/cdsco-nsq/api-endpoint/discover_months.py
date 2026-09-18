"""
CDSCO NSQ - Discover which months actually have data.
Purpose: For each year and each tab, ask the API which months exist.
         Build a manifest of (year, month, tab) combos with data.
"""

import json
import time
from pathlib import Path

import requests

BASE_URL = "https://cdscoonline.gov.in"
OUTPUT_DIR = Path("websites/cdsco-nsq/api-endpoint/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug",
}


def get_years(tab: str) -> list[str]:
    url = f"{BASE_URL}/CDSCO/reportingYears"
    resp = requests.get(url, headers=HEADERS, params={"tab": tab}, timeout=30)
    return resp.json()


def get_months(year: str, tab: str) -> list[str]:
    url = f"{BASE_URL}/CDSCO/publicReportingMonths"
    resp = requests.get(url, headers=HEADERS,
                        params={"year": year, "tab": tab}, timeout=30)
    return resp.json()


def main():
    manifest = {}

    for tab in ["nsq", "spurious"]:
        print(f"\n{'=' * 72}")
        print(f"[*] Discovering months for tab: {tab}")
        print(f"{'=' * 72}")

        years = get_years(tab)
        print(f"[+] Years: {years}")

        manifest[tab] = {}

        for year in years:
            months = get_months(year, tab)
            manifest[tab][year] = months
            months_str = ", ".join(months) if months else "(none)"
            print(f"    {year}: {len(months):2} months  → {months_str}")
            time.sleep(0.3)  # be polite

    # Total
    print(f"\n{'=' * 72}")
    print("[*] MANIFEST SUMMARY")

    total_combos = 0
    for tab, years in manifest.items():
        count = sum(len(m) for m in years.values())
        total_combos += count
        print(f"    {tab:10} : {count:3} (year, month) combos across "
              f"{len(years)} years")

    print(f"\n    TOTAL fetchable batches: {total_combos}")

    # Save
    out_path = OUTPUT_DIR / "_available_months.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n[+] Manifest saved: {out_path}")


if __name__ == "__main__":
    main()