"""
CDSCO Homepage - Link Discovery for Banned Drugs
Purpose: Scrape the CDSCO homepage and extract all links containing
         'banned', 'prohibited', or 'consumer' to find the correct
         Banned Drugs page URL.
"""

import requests
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

URL = "https://cdsco.gov.in/opencms/opencms/en/"
BASE = "https://cdsco.gov.in"

OUTPUT_DIR = Path("websites/cdsco-banned-drugs/http-requests/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

print(f"[*] Fetching homepage: {URL}")
resp = requests.get(URL, headers=HEADERS, timeout=30)
print(f"[+] Status: {resp.status_code}, Size: {len(resp.content):,} bytes")

# Save raw HTML
(OUTPUT_DIR / "homepage.html").write_text(resp.text, encoding="utf-8")

soup = BeautifulSoup(resp.text, "html.parser")
all_links = soup.find_all("a", href=True)

print(f"\n[*] Total <a> tags: {len(all_links)}")

# Search for links matching our keywords
keywords = ["banned", "prohibited", "consumer", "banneddrugs"]
matches = []
for a in all_links:
    href = a["href"].strip()
    text = a.get_text(strip=True)
    haystack = (href + " " + text).lower()
    if any(kw in haystack for kw in keywords):
        matches.append({
            "text": text,
            "href": href,
            "absolute": urljoin(BASE, href),
        })

print(f"\n[*] Links matching {keywords}: {len(matches)}")
print("=" * 72)

for i, m in enumerate(matches, 1):
    print(f"\n[{i}] Text     : {m['text'][:80]}")
    print(f"    Href     : {m['href'][:120]}")
    print(f"    Absolute : {m['absolute'][:120]}")

# Save results
import json
(OUTPUT_DIR / "banned_links.json").write_text(
    json.dumps(matches, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(f"\n[+] Saved {len(matches)} matches to: {OUTPUT_DIR / 'banned_links.json'}")