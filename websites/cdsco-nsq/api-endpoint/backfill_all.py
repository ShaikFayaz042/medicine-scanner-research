"""
Full backfill of NSQ and Spurious drug records.

Reads the manifest of available (year, month) combinations and fetches
each one via the filtered endpoint. Combines all results into two files.

Estimated: 104 API calls, ~1 minute at 0.3s delay.
"""

import json
import time
from pathlib import Path

import requests

BASE_URL = "https://cdscoonline.gov.in"
MANIFEST_FILE = Path("websites/cdsco-nsq/api-endpoint/output/_available_months.json")
OUTPUT_DIR = Path("websites/cdsco-nsq/api-endpoint/output/backfill")
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

ENDPOINTS = {
    "nsq":      "/CDSCO/filteredNsqDrugTable",
    "spurious": "/CDSCO/filteredSpuriousDrugTable",
}


def main():
    if not MANIFEST_FILE.exists():
        raise SystemExit(f"[!] Manifest not found: {MANIFEST_FILE}\n"
                         f"    Run discover_months.py first.")

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    grand_total = 0
    summary = {}
    started = time.time()

    for tab in ["nsq", "spurious"]:
        if tab not in manifest:
            continue

        endpoint = BASE_URL + ENDPOINTS[tab]
        all_records = []
        call_count = 0
        empty_count = 0
        total_records = 0

        print(f"\n{'=' * 72}")
        print(f"[*] Backfilling: {tab}")
        print(f"[*] Endpoint  : {endpoint}")
        print(f"{'=' * 72}")

        for year in sorted(manifest[tab].keys()):
            for month in manifest[tab][year]:
                month_year = f"{month}-{year}"
                params = {"month": month_year, "source": "All", "tab": tab}

                try:
                    resp = requests.get(endpoint, headers=HEADERS,
                                        params=params, timeout=30)
                    parsed = resp.json()
                    data = parsed.get("aaData", []) if isinstance(parsed, dict) else parsed
                except Exception as e:
                    print(f"    {month_year:12}  ERROR: {e}")
                    time.sleep(0.3)
                    continue

                for r in data:
                    r["_backfill_tab"] = tab
                    r["_backfill_month"] = month_year

                all_records.extend(data)
                call_count += 1

                if not data:
                    empty_count += 1
                    print(f"    {month_year:12}    0 records (empty)")
                else:
                    print(f"    {month_year:12} {len(data):4} records")

                total_records += len(data)
                time.sleep(0.3)

        # Save combined history
        out = OUTPUT_DIR / f"{tab}_full_history.json"
        out.write_text(
            json.dumps(all_records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\n[+] {tab}: {total_records} records "
              f"across {call_count} API calls "
              f"({empty_count} empty months)")

        summary[tab] = {
            "total_records": total_records,
            "api_calls": call_count,
            "empty_months": empty_count,
            "output_file": str(out),
            "output_bytes": out.stat().st_size,
        }
        grand_total += total_records

    # Save summary
    summary_path = OUTPUT_DIR / "_backfill_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    elapsed = time.time() - started
    print(f"\n{'=' * 72}")
    print(f"[*] BACKFILL COMPLETE")
    print(f"[*] Grand total records : {grand_total}")
    print(f"[*] Total API calls     : {summary.get('nsq', {}).get('api_calls', 0) + summary.get('spurious', {}).get('api_calls', 0)}")
    print(f"[*] Elapsed             : {elapsed:.1f}s")
    print(f"[*] Summary saved       : {summary_path}")


if __name__ == "__main__":
    main()