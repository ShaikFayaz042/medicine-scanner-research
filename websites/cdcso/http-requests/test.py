"""
CDSCO HTTP Request Experiment
Target: https://cdsco.gov.in/opencms/opencms/en/Alerts/
Purpose: Determine if the Alerts page is accessible via direct HTTP request
         and whether PDF links are present in the initial HTML response.
"""

import requests
from pathlib import Path
from datetime import datetime

# Target URL
URL = "https://cdsco.gov.in/opencms/opencms/en/Alerts/"

# Output directory for storing raw HTML and response metadata
OUTPUT_DIR = Path("websites/cdcso/http-requests/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Use a realistic browser User-Agent to avoid being blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

print(f"[*] Sending GET request to: {URL}")
print(f"[*] Timeout: 30 seconds")

try:
    response = requests.get(URL, headers=HEADERS, timeout=30)

    # --- Response Metadata ---
    print(f"\n[+] HTTP Status Code: {response.status_code}")
    print(f"[+] Response Size: {len(response.content)} bytes ({len(response.content) / 1024:.2f} KB)")
    print(f"[+] Content-Type: {response.headers.get('Content-Type', 'N/A')}")
    print(f"[+] Server: {response.headers.get('Server', 'N/A')}")

    # --- Save raw HTML to file ---
    html_file = OUTPUT_DIR / "alerts_page.html"
    html_file.write_text(response.text, encoding="utf-8")
    print(f"\n[+] Raw HTML saved to: {html_file}")

    # --- Quick check: Does the HTML contain PDF links? ---
    html_lower = response.text.lower()
    pdf_count = html_lower.count(".pdf")
    print(f"[+] Occurrences of '.pdf' in HTML: {pdf_count}")

    if pdf_count > 0:
        print("[+] PDF links appear to be present in the initial HTML response.")
    else:
        print("[-] No '.pdf' found in HTML. Links may be loaded dynamically.")

    # --- Check for common alert-related keywords ---
    keywords = ["nsq", "spurious", "drug alert", "batch", "not of standard quality"]
    print("\n[*] Keyword presence in HTML:")
    for kw in keywords:
        found = kw.lower() in html_lower
        print(f"    - '{kw}': {'FOUND' if found else 'not found'}")

    # --- Save response metadata ---
    meta_file = OUTPUT_DIR / "response_metadata.txt"
    meta_file.write_text(
        f"URL: {URL}\n"
        f"Status: {response.status_code}\n"
        f"Size: {len(response.content)} bytes\n"
        f"Content-Type: {response.headers.get('Content-Type')}\n"
        f"Server: {response.headers.get('Server')}\n"
        f"Timestamp: {datetime.now().isoformat()}\n"
        f"PDF occurrences: {pdf_count}\n",
        encoding="utf-8",
    )
    print(f"[+] Metadata saved to: {meta_file}")

except requests.exceptions.Timeout:
    print("[-] Request timed out after 30 seconds.")
except requests.exceptions.ConnectionError as e:
    print(f"[-] Connection error: {e}")
except requests.exceptions.RequestException as e:
    print(f"[-] Request failed: {e}")