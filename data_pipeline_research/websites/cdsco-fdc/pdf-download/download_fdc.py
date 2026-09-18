"""
CDSCO FDC - PDF Download Experiment
Purpose: Prove the existing iframe-wrapper resolver works for FDC PDFs
         across ALL FOUR tabs (Alerts, News, Public Notices, Gazette Notifications).
Targets: 5 PDFs covering all 4 tabs.
"""

import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Paths ---
EXTRACTION_DIR = Path("websites/cdsco-fdc/html-extraction/output")
OUTPUT_DIR = Path("websites/cdsco-fdc/pdf-download/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Targets: (source_json_file, document_id, tab_label) ---
# Covering all 4 tabs. Gazette Notifications prioritized (legal authority).
TARGETS = [
    # Alerts tab (closes the coverage gap)
    ("fdc_alerts.json",         14567, "Alerts"),
    ("fdc_alerts.json",         3251,  "Alerts"),
    # Gazette Notifications
    ("fdc_gazette.json",        14519, "Gazette Notifications"),
    ("fdc_gazette.json",        3170,  "Gazette Notifications"),
    # News
    ("fdc_news.json",           14514, "News"),
    ("fdc_news.json",           12087, "News"),
    # Public Notices
    ("fdc_public_notices.json", 13292, "Public Notices"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch_pdf_bytes(url: str, referer: str | None = None) -> bytes:
    """Follow wrapper -> iframe -> real PDF. Returns PDF bytes."""
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer

    resp = requests.get(url, headers=headers, timeout=60)
    ctype = resp.headers.get("Content-Type", "").lower()
    print(f"    [.] GET {url[:80]}... -> {resp.status_code} {ctype}")

    if "application/pdf" in ctype or resp.content.startswith(b"%PDF-"):
        return resp.content

    if "text/html" in ctype:
        soup = BeautifulSoup(resp.text, "html.parser")
        iframe = soup.find("iframe")
        if iframe and iframe.get("src"):
            inner = iframe["src"].strip()
            inner_url = urljoin(url, inner)
            if "file=" in inner_url:
                file_part = inner_url.split("file=", 1)[1].split("&")[0]
                inner_url = urljoin(url, file_part)
            print(f"    [+] iframe -> {inner_url[:80]}...")
            return _fetch_pdf_bytes(inner_url, referer=url)

    raise RuntimeError(
        f"Could not resolve PDF. Content-Type={ctype}, "
        f"first bytes={resp.content[:80]!r}"
    )


def find_record(json_file: str, document_id: int) -> dict | None:
    """Look up a record by document_id inside an extraction JSON."""
    path = EXTRACTION_DIR / json_file
    if not path.exists():
        print(f"    [!] {path} not found")
        return None
    records = json.loads(path.read_text(encoding="utf-8"))
    for r in records:
        if r["document_id"] == document_id:
            return r
    return None


def main():
    print(f"[*] FDC PDF Download Test")
    print(f"[*] Targets: {len(TARGETS)} (covering all 4 tabs)\n")

    results = []

    for json_file, doc_id, tab_label in TARGETS:
        record = find_record(json_file, doc_id)
        if not record:
            print(f"[!] document_id {doc_id} not found in {json_file}")
            results.append({
                "document_id": doc_id, "tab": tab_label,
                "ok": False, "reason": "not found",
            })
            continue

        print("=" * 72)
        print(f"[*] document_id : {doc_id}")
        print(f"[*] Tab         : {record['tab']}")
        print(f"[*] Title       : {record['title'][:65]}")
        print(f"[*] Declared sz : {record['pdf_size_declared']}")

        try:
            pdf_bytes = _fetch_pdf_bytes(record["pdf_url"])
        except Exception as e:
            print(f"[-] FAILED: {e}")
            results.append({
                "document_id": doc_id, "tab": tab_label,
                "ok": False, "reason": str(e),
            })
            continue

        out_path = OUTPUT_DIR / f"{doc_id}.pdf"
        out_path.write_bytes(pdf_bytes)
        size = len(pdf_bytes)
        is_pdf = pdf_bytes.startswith(b"%PDF-")

        print(f"[+] Saved         : {out_path}")
        print(f"[+] Size          : {size:,} bytes ({size/1024:.1f} KB)")
        print(f"[+] Magic bytes   : {pdf_bytes[:8]!r}")
        print(f"[+] Valid PDF?    : {'YES' if is_pdf else 'NO'}")

        results.append({
            "document_id": doc_id,
            "tab": tab_label,
            "ok": is_pdf,
            "size_bytes": size,
            "path": str(out_path),
        })

    # --- Summary ---
    print("\n" + "=" * 72)
    ok = sum(1 for r in results if r["ok"])
    print(f"[+] {ok}/{len(results)} PDFs downloaded successfully")
    print("\n[*] Per-tab results:")
    for r in results:
        status = "✅" if r["ok"] else "❌"
        print(f"    {status}  [{r['tab']:22}]  {r['document_id']:>6}  "
              f"{r.get('size_bytes', 0):>10,} bytes")

    # --- Save per-tab confirmation ---
    summary = {
        "total": len(results),
        "successful": ok,
        "tabs_tested": sorted(set(r["tab"] for r in results)),
        "results": results,
    }
    summary_path = OUTPUT_DIR / "_download_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n[+] Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()