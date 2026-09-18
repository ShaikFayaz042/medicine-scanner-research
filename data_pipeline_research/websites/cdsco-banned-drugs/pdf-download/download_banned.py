"""
CDSCO Banned Drugs - PDF Download & Discovery
Purpose:
  1. Download banneddrugs_1.pdf (from the iframe src)
  2. Check if banneddrugs_2.pdf, banneddrugs_3.pdf etc. exist
  3. Check for a no-suffix variant
  4. Inspect the PDF structure (text-based vs scanned)
"""

import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Input HTML (saved by banned_test.py) ---
INPUT_HTML = Path("websites/cdsco-banned-drugs/http-requests/output/banned_page.html")
OUTPUT_DIR = Path("websites/cdsco-banned-drugs/pdf-download/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://cdsco.gov.in"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# --- Step 1: Extract the iframe src from the saved HTML ---
if not INPUT_HTML.exists():
    raise SystemExit(f"[!] {INPUT_HTML} not found. Run banned_test.py first.")

html = INPUT_HTML.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
iframe = soup.find("iframe")

if not iframe or not iframe.get("src"):
    raise SystemExit("[!] No iframe src found in the page HTML.")

iframe_src = iframe["src"].strip()
primary_url = urljoin(BASE_URL, iframe_src)

print(f"[*] Extracted iframe src: {iframe_src}")
print(f"[*] Primary PDF URL    : {primary_url}\n")


def try_download(url: str, label: str) -> dict:
    """Attempt to download a URL as a PDF."""
    print("=" * 72)
    print(f"[*] {label}")
    print(f"[*] {url[:110]}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"[-] Request failed: {e}")
        return {"url": url, "ok": False, "reason": str(e)}

    ctype = resp.headers.get("Content-Type", "N/A")
    print(f"[+] Status      : {resp.status_code}")
    print(f"[+] Content-Type: {ctype}")
    print(f"[+] Size        : {len(resp.content):,} bytes")

    is_pdf = resp.content.startswith(b"%PDF-")
    print(f"[+] Magic bytes : {resp.content[:8]!r}")
    print(f"[+] Valid PDF?  : {'YES' if is_pdf else 'NO'}")

    if not is_pdf:
        print(f"[!] Not a PDF. First 300 bytes:")
        print(f"    {resp.content[:300]!r}")
        return {"url": url, "ok": False, "reason": "not a PDF"}

    fname = url.rsplit("/", 1)[-1] or "banned.pdf"
    out_path = OUTPUT_DIR / fname
    out_path.write_bytes(resp.content)
    sha256 = hashlib.sha256(resp.content).hexdigest()

    print(f"[+] Saved       : {out_path}")
    print(f"[+] SHA-256     : {sha256}")

    return {
        "url": url,
        "ok": True,
        "size_bytes": len(resp.content),
        "sha256": sha256,
        "path": str(out_path),
    }


def main():
    print("[*] Banned Drugs PDF Download & Discovery\n")

    results = []

    # --- Test 1: Primary PDF ---
    results.append(try_download(primary_url, "PRIMARY PDF (from iframe)"))

    # --- Test 2: Check for sibling files ---
    base_dir = primary_url.rsplit("/", 1)[0]
    for suffix in ["banneddrugs_2.pdf", "banneddrugs_3.pdf", "banneddrugs_4.pdf"]:
        candidate = f"{base_dir}/{suffix}"
        results.append(try_download(candidate, f"SIBLING: {suffix}"))

    # --- Test 3: No-suffix variant ---
    no_suffix = f"{base_dir}/banneddrugs.pdf"
    results.append(try_download(no_suffix, "ALTERNATE: banneddrugs.pdf"))

    # --- Summary ---
    print("\n" + "=" * 72)
    print("[*] SUMMARY")
    for r in results:
        status = "✅" if r["ok"] else "❌"
        fname = r["url"].rsplit("/", 1)[-1]
        if r["ok"]:
            print(f"    {status} {fname:30} {r['size_bytes']:>10,} bytes  "
                  f"sha256={r['sha256'][:16]}...")
        else:
            print(f"    {status} {fname:30} {r.get('reason', 'unknown')}")

    # Save summary
    summary_path = OUTPUT_DIR / "_download_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[+] Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()