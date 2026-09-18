"""
Verify the num_id linkage between spurious records and CDSCO documents.

Context:
- The spurious endpoint's unfiltered call returns a `num_id` integer
  (e.g. 12377)
- The Alerts/FDC pages use num_id (Base64-encoded) in their download URLs
- If these share the same internal ID space, we can cross-reference a
  structured spurious record to its underlying CDSCO document

Test: Base64-encode the spurious num_id, resolve via the standard
download endpoint, and confirm the target is a valid document.
"""

import base64
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://cdsco.gov.in"
OUTPUT_DIR = Path("websites/cdsco-nsq/api-endpoint/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Test cases drawn from actual spurious data we captured
TEST_CASES = [
    {
        "source":  "Spurious Jul-2026 (unfiltered)",
        "num_id":  12377,
        "product": "Buprenorphine Injection I.P. 2ml",
        "batch":   "LM1888",
    },
]

# Reference: known-good Alerts num_id (for a positive control)
CONTROL = {
    "source":  "Alerts page (known to work)",
    "num_id":  13487,
    "product": "Circular to all State/UT Licensing Authorities",
    "batch":   "N/A",
}


def check_one(case: dict) -> dict:
    print("=" * 72)
    print(f"[*] Source : {case['source']}")
    print(f"[*] Product: {case['product']}")
    print(f"[*] num_id : {case['num_id']}")

    encoded = base64.b64encode(str(case["num_id"]).encode()).decode()
    url = (
        f"{BASE_URL}/opencms/opencms/system/modules/"
        f"CDSCO.WEB/elements/download_file_division.jsp?num_id={encoded}"
    )
    print(f"[*] Base64 : {encoded}")
    print(f"[*] URL    : {url[:110]}...")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"[-] Request failed: {e}")
        return {"num_id": case["num_id"], "linked": False, "reason": str(e)}

    ctype = resp.headers.get("Content-Type", "N/A")
    print(f"[+] Status      : {resp.status_code}")
    print(f"[+] Content-Type: {ctype}")
    print(f"[+] Size        : {len(resp.content):,} bytes")
    print(f"[+] Magic bytes : {resp.content[:8]!r}")

    linked = False
    pdf_path = None
    inner_url = None

    # Case 1: direct PDF
    if resp.content.startswith(b"%PDF-"):
        print(f"[+] ✅ DIRECT PDF")
        linked = True
        pdf_path = OUTPUT_DIR / f"numid_{case['num_id']}.pdf"
        pdf_path.write_bytes(resp.content)

    # Case 2: iframe wrapper (this is what we expect)
    elif b"<iframe" in resp.content[:1000]:
        soup = BeautifulSoup(resp.text, "html.parser")
        iframe = soup.find("iframe")
        if iframe and iframe.get("src"):
            inner_url = urljoin(url, iframe["src"].strip())
            print(f"[+] ✅ WRAPPER — iframe found")
            print(f"       inner: {inner_url[:100]}...")

            try:
                inner_resp = requests.get(inner_url, headers=HEADERS, timeout=30)
                if inner_resp.content.startswith(b"%PDF-"):
                    print(f"[+] ✅ Real PDF retrieved: "
                          f"{len(inner_resp.content):,} bytes")
                    linked = True
                    pdf_path = OUTPUT_DIR / f"numid_{case['num_id']}.pdf"
                    pdf_path.write_bytes(inner_resp.content)
                else:
                    print(f"[!] Inner response not a PDF: "
                          f"{inner_resp.content[:100]!r}")
            except Exception as e:
                print(f"[!] Inner fetch failed: {e}")

    # Case 3: 404
    elif resp.status_code == 404:
        print(f"[-] ❌ 404 — no document exists at this num_id")

    else:
        print(f"[!] ❓ Unexpected response")
        print(f"     First 200 bytes: {resp.content[:200]!r}")

    return {
        "num_id": case["num_id"],
        "source": case["source"],
        "product": case["product"],
        "encoded": encoded,
        "status": resp.status_code,
        "content_type": ctype,
        "linked": linked,
        "pdf_saved": str(pdf_path) if pdf_path else None,
        "inner_url": inner_url,
    }


def main():
    print("[*] num_id Linkage Verification\n")

    # First, positive control — a known Alerts num_id
    print("[*] Running positive control with known-good Alerts num_id...")
    control_result = check_one(CONTROL)
    print()

    # Then the actual spurious test case(s)
    results = []
    for case in TEST_CASES:
        results.append(check_one(case))
        print()

    # Summary
    print("=" * 72)
    print("[*] SUMMARY")

    status = "✅" if control_result.get("linked") else "❌"
    print(f"    {status} [CONTROL]  num_id={CONTROL['num_id']:>6}  "
          f"{control_result.get('status')}  "
          f"linked={control_result.get('linked')}")

    for r in results:
        status = "✅" if r.get("linked") else "❌"
        print(f"    {status} [SPURIOUS] num_id={r['num_id']:>6}  "
              f"{r.get('status')}  linked={r.get('linked')}")

    # Verdict
    if control_result.get("linked") and results and all(r.get("linked") for r in results):
        print("\n[+] VERDICT: num_id space IS shared between spurious records "
              "and CDSCO documents.")
        print("[+] Cross-referencing is possible.")
    elif not control_result.get("linked"):
        print("\n[!] CONTROL failed — the download endpoint may have changed.")
        print("[!] Cannot conclude anything about spurious num_id yet.")
    else:
        print("\n[!] VERDICT: spurious num_id did NOT resolve to a document.")
        print("[!] The two ID spaces may be separate — needs further investigation.")

    # Save
    out = OUTPUT_DIR / "_num_id_linkage_test.json"
    out.write_text(
        json.dumps({
            "control": control_result,
            "spurious": results,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"\n[+] Result saved: {out}")


if __name__ == "__main__":
    main()