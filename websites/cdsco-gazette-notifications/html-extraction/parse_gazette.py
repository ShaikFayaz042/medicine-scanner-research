"""
CDSCO Gazette Notifications - HTML Extraction with keyword filter.

Gazette is ~80% administrative notifications (amendments, appointments,
fee revisions, port designations). Only a small fraction is truly
relevant to a medicine scanner:
  - Prohibitions / bans of drugs or FDCs
  - Restrictions on specific FDCs
  - Schedule H1 inclusions
  - Debarments of applicants
  - Antimicrobial prohibition for animal use

Filter aggressively. Keep signal, drop noise.

Fixes applied (v3):
  1. Normalize text before word matching.
     v2 used r"\bkeyword\b" which failed on "_Draft" because
     underscore is a word character in Python regex — no boundary
     between "_" and "d". Now we replace all non-alphanumeric chars
     with spaces, so "_Draft_" -> " draft " (matches), while
     "import" stays one token (does NOT match " port ").
  2. Post-processing dedup by notification number.
     CDSCO sometimes re-uploads the same notification with a new
     document_id (e.g. "Prohibition of 16 FDCs" appeared twice with
     different num_id values). Dedup on extracted notification
     number (e.g. "s.o. 3068(e) to s.o. 3083(e)").
  3. Added "exemption" to SKIP — exemptions are the opposite of
     prohibitions and are not useful for a medicine scanner.
  4. Tightened notification-number regex to reliably capture
     patterns like "GSR 219(E)", "S.O. 2607", "S.O. 3068(E) to S.O. 3083(E)".
"""

import base64
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

INPUT_HTML = Path("websites/cdsco-gazette-notifications/http-requests/output/gazette_page.html")
OUTPUT_DIR = Path("websites/cdsco-gazette-notifications/html-extraction/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://cdsco.gov.in"

# --- Full extraction. No relevance filtering applied. ---

# --- Dedup helper ---

NOTIF_RE = re.compile(
    r"(?:G\.S\.R\.?|S\.O\.?)\s*\d+(?:\s*\(E\))?"
    r"(?:\s*to\s*(?:G\.S\.R\.?|S\.O\.?)\s*\d+(?:\s*\(E\))?)?",
    re.IGNORECASE,
)


def notification_number(title: str) -> str:
    """Extract a canonical notification number from the title.

    Examples:
      "2026.06.11 S.O. 3068(E) to S.O. 3083(E)_ Prohibition of 16 FDCs"
        -> "s.o. 3068(e) to s.o. 3083(e)"
      "2024.08.12__DR_S.O. 3285(E) to 3440(E)_ Prohibition of 156 FDCs"
        -> "s.o. 3285(e) to 3440(e)"
      "GSR 219(E) Dt. 26.03.2020_Sale of Hydroxychloroquine..."
        -> "gsr 219(e)"
    """
    m = NOTIF_RE.search(title)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(0).strip().lower())


# --- Main ---

def main():
    if not INPUT_HTML.exists():
        raise SystemExit(f"[!] {INPUT_HTML} not found. Run gazette_test.py first.")

    html = INPUT_HTML.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="example")
    if table is None:
        tables = soup.find_all("table")
        if not tables:
            raise SystemExit("[!] No tables found in HTML.")
        table = max(tables, key=lambda t: len(t.find_all("tr")))

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")

    all_records = []
    kept_records = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # Gazette table: S.no | Title | Release Date | Download Pdf | Pdf Size
        anchor = cells[3].find("a")
        if not (anchor and anchor.get("href")):
            continue

        raw_href = anchor["href"].strip()
        pdf_url = urljoin(BASE_URL, raw_href)

        num_id_b64 = ""
        document_id = None
        if "num_id=" in raw_href:
            num_id_b64 = raw_href.split("num_id=")[1].split("&")[0]
            try:
                document_id = int(base64.b64decode(num_id_b64).decode("utf-8"))
            except Exception:
                pass

        title = cells[1].get_text(strip=True)

        record = {
            "sno":               cells[0].get_text(strip=True),
            "title":             title,
            "release_date":      cells[2].get_text(strip=True),
            "pdf_url":           pdf_url,
            "num_id_b64":        num_id_b64,
            "document_id":       document_id,
            "pdf_size_declared": cells[4].get_text(strip=True),
            "notif_number":      notification_number(title),
        }
        all_records.append(record)

    # Save full dataset only; no filtering.
    (OUTPUT_DIR / "gazette_all.json").write_text(
        json.dumps(all_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[*] Total rows parsed : {len(all_records)}")
    print(f"[+] All saved to : {OUTPUT_DIR / 'gazette_all.json'}")
    print("\n[*] First few records:")
    for r in all_records[:10]:
        nnum = f"  [{r['notif_number']}]" if r["notif_number"] else ""
        print(f"    {r['release_date']}  {r['title'][:80]}{nnum}")


if __name__ == "__main__":
    main()