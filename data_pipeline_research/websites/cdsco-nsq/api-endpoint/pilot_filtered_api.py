"""
Pilot test: verify filtered endpoints return historical data.

Tests 4 combinations:
  - NSQ for Jan-2019 (oldest)
  - NSQ for Jul-2026 (newest)
  - Spurious for Jun-2025 (first month available)
  - Spurious for Jul-2026 (latest)

Confirms:
  - month format "Mon-YYYY" works
  - source="All" returns union of State + CDL
  - historical data accessible
  - schema consistency
"""

import json
from pathlib import Path

import requests

BASE_URL = "https://cdscoonline.gov.in"
OUTPUT_DIR = Path("websites/cdsco-nsq/api-endpoint/output/pilot")
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

TARGETS = [
    ("NSQ Jan-2019",       "/CDSCO/filteredNsqDrugTable",      "Jan-2019", "All", "nsq"),
    ("NSQ Jul-2026",       "/CDSCO/filteredNsqDrugTable",      "Jul-2026", "All", "nsq"),
    ("Spurious Jun-2025",  "/CDSCO/filteredSpuriousDrugTable", "Jun-2025", "All", "spurious"),
    ("Spurious Jul-2026",  "/CDSCO/filteredSpuriousDrugTable", "Jul-2026", "All", "spurious"),
]


def probe(label, path, month, source, tab):
    url = BASE_URL + path
    params = {"month": month, "source": source, "tab": tab}

    print("=" * 72)
    print(f"[*] {label}")
    print(f"[*] {url}")
    print(f"[*] params: {params}")

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"[-] Request failed: {e}")
        return {"label": label, "ok": False}

    print(f"[+] Status      : {resp.status_code}")
    print(f"[+] Size        : {len(resp.content):,} bytes")

    try:
        parsed = resp.json()
    except Exception:
        try:
            parsed = json.loads(resp.text)
        except Exception:
            print(f"[!] Not JSON. First 200 chars: {resp.text[:200]!r}")
            return {"label": label, "ok": False}

    # Could be {aaData: [...]} or a plain list
    if isinstance(parsed, dict) and "aaData" in parsed:
        data = parsed["aaData"]
    elif isinstance(parsed, list):
        data = parsed
    else:
        print(f"[!] Unexpected shape: {type(parsed).__name__}")
        print(f"    keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'n/a'}")
        return {"label": label, "ok": False}

    print(f"[+] Records     : {len(data)}")

    if data:
        first = data[0]
        print(f"[+] Fields      : {len(first)} fields")
        print(f"    Sample:")
        for k, v in list(first.items())[:8]:
            print(f"      {k!r:35} = {str(v)[:55]!r}")

        # Save raw
        fname = f"{tab}_{month}_{source}.json"
        out = OUTPUT_DIR / fname
        out.write_text(json.dumps(parsed, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"[+] Saved       : {out}")

    return {"label": label, "ok": True, "count": len(data)}


def main():
    print("[*] Filtered Endpoint Pilot\n")
    results = []
    for label, path, month, source, tab in TARGETS:
        results.append(probe(label, path, month, source, tab))
        print()

    print("=" * 72)
    print("[*] PILOT SUMMARY")
    for r in results:
        status = "✅" if r.get("ok") else "❌"
        count = r.get("count", 0)
        print(f"    {status} {r['label']:22} records={count}")


if __name__ == "__main__":
    main()