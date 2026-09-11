"""
CDSCO NSQ - API Endpoint Probe
Target: https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable
Purpose: Test the discovered JSON API endpoint directly.
"""

import json
from pathlib import Path
from datetime import datetime

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
    "X-Requested-With": "XMLHttpRequest",   # mark as AJAX
    "Referer": "https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug",
}

# --- Endpoints to probe ---
ENDPOINTS = [
    ("NSQ Table (all)",       "/CDSCO/publicNsqDrugTable",                {}),
    ("Spurious Table (all)",  "/CDSCO/viewPublicSpuriousDrugData",           {}),
    ("Reporting Years",       "/CDSCO/reportingYears",                    {"tab": "nsq"}),
    ("Reporting Months 2025", "/CDSCO/publicReportingMonths",             {"year": "2025", "tab": "nsq"}),
    ("Pending States",        "/CDSCO/statesPendingSubmission",           {}),
]


def probe(label: str, path: str, params: dict):
    url = BASE_URL + path
    print("=" * 72)
    print(f"[*] {label}")
    print(f"[*] URL: {url}")
    if params:
        print(f"[*] Params: {params}")

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"[-] Request failed: {e}")
        return {"label": label, "ok": False, "reason": str(e)}

    ctype = resp.headers.get("Content-Type", "N/A")
    print(f"[+] Status      : {resp.status_code}")
    print(f"[+] Content-Type: {ctype}")
    print(f"[+] Size        : {len(resp.content):,} bytes")

    # Try to parse JSON
    parsed = None
    try:
        parsed = resp.json()
    except Exception:
        try:
            # Some endpoints return JSON-stringified twice
            parsed = json.loads(resp.text)
        except Exception:
            pass

    if parsed is None:
        print(f"[!] Not JSON. First 200 chars:")
        print(f"    {resp.text[:200]!r}")
        return {"label": label, "ok": False, "reason": "not JSON"}

    print(f"[+] Top-level keys: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__}")

    # Save raw JSON
    fname = path.strip("/").replace("/", "_") + ".json"
    out_path = OUTPUT_DIR / fname
    out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Saved       : {out_path}")

    # Show aaData summary if present
    if isinstance(parsed, dict) and "aaData" in parsed:
        aa = parsed["aaData"]
        print(f"[+] aaData count: {len(aa)}")
        if aa:
            print(f"[+] First row keys: {list(aa[0].keys())}")
            print(f"\n    Sample first row:")
            for k, v in aa[0].items():
                print(f"      {k!r:35} = {str(v)[:60]!r}")
    elif isinstance(parsed, list):
        print(f"[+] List count  : {len(parsed)}")
        if parsed and isinstance(parsed[0], dict):
            print(f"[+] First item keys: {list(parsed[0].keys())}")
            print(f"    Sample: {parsed[0]}")

    return {"label": label, "ok": True, "path": str(out_path)}


def main():
    print("[*] NSQ API Probe\n")
    results = []
    for label, path, params in ENDPOINTS:
        results.append(probe(label, path, params))
        print()

    print("=" * 72)
    print("[*] SUMMARY")
    for r in results:
        status = "✅" if r["ok"] else "❌"
        print(f"    {status} {r['label']:25} {r.get('reason', 'ok')}")


if __name__ == "__main__":
    main()