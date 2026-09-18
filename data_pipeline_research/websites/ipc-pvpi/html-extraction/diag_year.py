"""
Diagnostic: dump every <a> on a problem year page whose visible
text mentions a month name or a 4-digit year. Also dump every
string in the HTML that ends in .pdf.

Usage:
    python diag_year.py 2023
    python diag_year.py 2019
    python diag_year.py 2017
    python diag_year.py 2016
"""
import html as html_lib
import re
import sys
from urllib.parse import urljoin

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

YEAR_URLS = {
    "2023": "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/1089-drug-alerts-2023.html",
    "2022": "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/931-drug-alerts-2022.html",
    "2019": "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/602-drug-alerts-2019.html",
    "2017": "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/418-drug-alerts-2017.html",
    "2016": "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/417-drug-alerts-2016.html",
}

MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)

anchor_re = re.compile(
    r'<a\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)
text_re = re.compile(rf"{MONTH}|\b(?:19|20)\d{{2}}\b", re.I)
pdf_str_re = re.compile(r'[^"\'\s<>()]*\.pdf', re.I)


def main(year: str) -> None:
    url = YEAR_URLS.get(year)
    if not url:
        print(f"[!] No URL configured for year {year}")
        print(f"    Add it to YEAR_URLS or pass one of: {sorted(YEAR_URLS)}")
        sys.exit(1)

    print(f"[*] Fetching {year}: {url}")
    r = requests.get(url, headers=HEADERS, timeout=20)
    print(f"[+] HTTP {r.status_code}, {len(r.text):,} bytes\n")

    print(f"=== Anchors whose text mentions a month or a year ({year}) ===")
    shown = 0
    for m in anchor_re.finditer(r.text):
        href_raw = m.group(1)
        inner = m.group(2)

        # Strip inner HTML tags, collapse whitespace
        text = re.sub(r"<[^>]+>", " ", inner)
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text_re.search(text):
            continue

        href = html_lib.unescape(href_raw.strip())
        abs_url = urljoin(url, href)
        print(f"  text: {text!r}")
        print(f"    href: {href!r}")
        print(f"    abs : {abs_url}")
        shown += 1
    print(f"[*] {shown} anchor(s) matched\n")

    print(f"=== Every '.pdf' string appearing anywhere in HTML ({year}) ===")
    seen = set()
    for m in pdf_str_re.finditer(r.text):
        s = m.group(0)
        if s in seen:
            continue
        seen.add(s)
        print(f"  {s}")
    print(f"[*] {len(seen)} unique .pdf strings\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python diag_year.py <YEAR>")
        print(f"Configured years: {sorted(YEAR_URLS)}")
        sys.exit(1)
    main(sys.argv[1])