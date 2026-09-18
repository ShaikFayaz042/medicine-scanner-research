"""
IPC PvPI Drug Safety Alerts — Extraction (v8)

Fixes over v7:

  1) MAJOR: The `seen` set was populated BEFORE the anchor-text
     filter ran. When a PDF appeared in a split anchor with an
     <img> (visible text = ""), we would mark it as seen, then
     reject it for lacking "alert" — and the *real* anchor later
     on the same page (with proper "Drug Safety Alert (Month
     YYYY)" text) got skipped as a duplicate. This silently ate:
        2017: File674/File683/...  -> from 12 down to 2
        2016: File517 (Mar), File606 (Aug) -> from 8 down to 6
        2024: Drug_Safety_AlertsMay_2024.pdf
        2022: Drug_Safety_Alert_December_2022.pdf
        2023: Drug_Safety_Alert_March_2023.pdf
     Fix: only add to `seen` after ALL filters pass.

  2) month_from_filename() now understands dsaMMYY (dsa1017 ->
     October, dsa1117 -> November). Previously the per-year
     summary showed "2017: 2 (no month name in filename)".

  3) Per-year summary prints the "(no month name in filename)"
     note once next to the year header, not as its own line that
     silently swallowed the count.

Expected output:

    2026   5   Feb, Mar, May, Jun, Jul
    2025   5   Mar, May, Jun, Aug, Sep
    2024   8   Mar, May, Jun, Jul, Aug, Sep, Nov, Dec
    2023  11   Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov
    2022  12   Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
    2021  10   Jan, Feb, Mar, Apr, Jun, Jul, Aug, Sep, Nov, Dec
    2020  10   Jan, Feb, Mar, Jun, Jul, Aug, Sep, Oct, Nov, Dec
    2019  11   Jan, Feb, Mar, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
    2018   6   Jan, Feb, Mar, Apr, Sep, Dec
    2017  12   Jan..Dec
    2016   8   Mar, Apr, May, Jun, Jul, Aug, Nov, Dec
    Total: 98 unique Drug Safety Alert PDFs.
"""

import html as html_lib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests

# --- Config ---

INPUT_HTML = Path("websites/ipc-pvpi/http-requests/output/ipc_page.html")
OUTPUT_DIR = Path("websites/ipc-pvpi/html-extraction/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
YEAR_HTML_DIR = OUTPUT_DIR / "year_pages"
YEAR_HTML_DIR.mkdir(parents=True, exist_ok=True)

PAGE_URL = (
    "https://www.ipc.gov.in/"
    "mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# --- Master index (always dropped) ---

ALWAYS_DROP_HINTS = [
    "list-of-drugs-safety-alert",
    "list_of_drugs_safety_alert",
]


def is_master_index(url: str) -> bool:
    u = url.lower()
    return any(h in u for h in ALWAYS_DROP_HINTS)


# --- Main-page sidebar filter ---

KEEP_URL_HINTS = [
    "/pvpi/",
    "/pvpi/das/",
    "drug_safety_alert",
    "drug-safety-alert",
    "drugs_safety_alert",
    "drugs-safety-alert",
    "drug_alert",
    "drug-alert",
    "drugs_alert",
    "drugs-alert",
    "dsa",
    "monthly_drug_safety_alert",
]

DROP_URL_HINTS = [
    "ip-reference-substances",
    "imp-rs",
    "reference-substances",
    "phytopharmaceutical",
    "supply-order",
    "prednisone",
    "impurity",
]


def is_drug_alert_main_page(url: str) -> bool:
    if is_master_index(url):
        return False
    u = url.lower()
    fname = u.rsplit("/", 1)[-1]
    for drop in DROP_URL_HINTS:
        if drop in u:
            return False
    if "/pvpi/das/" in u or "/pvpi/" in u:
        return True
    for keep in KEEP_URL_HINTS:
        if keep == "dsa":
            if fname.startswith("dsa"):
                return True
            continue
        if keep in u:
            return True
    return False


# --- Year / month from filename ---

# Note: no \b — underscores are word characters and break boundaries.
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
DSA_SHORT_RE = re.compile(r"\bdsa(\d{2})(\d{2})\b", re.I)


def year_from_filename(fname: str) -> str | None:
    m = DSA_SHORT_RE.search(fname)
    if m:
        yy = m.group(2)
        if 16 <= int(yy) <= 26:
            return "20" + yy
    matches = YEAR_RE.findall(fname)
    return matches[-1] if matches else None


def month_from_filename(fname: str) -> str | None:
    """Extract month from filename.

    Handles:
      * dsaMMYY       -> MM is 2-digit month (10 -> October)
      * Month-Name    -> January..December, or 3-letter abbr
    """
    # dsaMMYY first (dsa1017 -> October, dsa1117 -> November)
    m = DSA_SHORT_RE.search(fname)
    if m:
        mm = int(m.group(1))
        if 1 <= mm <= 12:
            return MONTHS[mm - 1]

    f = fname.lower()
    for name in MONTHS:
        if name.lower() in f:
            return name
    abbrs = ["jan", "feb", "mar", "apr", "may", "jun",
             "jul", "aug", "sep", "oct", "nov", "dec"]
    for i, ab in enumerate(abbrs):
        if ab in f:
            return MONTHS[i]
    return None


# --- Extraction ---

PDF_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref=["\']([^"\']*\.pdf(?:\?[^"\']*)?)["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
ALERT_WORD_RE = re.compile(r"\balert", re.I)


def _visible_text(inner_html: str) -> str:
    """Strip tags + entities + whitespace from anchor inner HTML."""
    text = TAG_STRIP_RE.sub(" ", inner_html)
    text = html_lib.unescape(text)
    return WS_RE.sub(" ", text).strip()


def extract_pdfs(
    html: str,
    page_url: str,
    filt,
    require_alert_text: bool = False,
) -> list[dict]:
    """Extract .pdf hrefs from <a href="...pdf">...pdf...</a>.

    Only adds a URL to `seen` AFTER it passes every filter. This is
    critical: Joomla emits split anchors (<a><img></a> <a>text</a>)
    where the icon-only anchor has no visible text. If we marked the
    URL as seen at that point, the real anchor later in the page
    would be skipped as a duplicate.
    """
    found: list[dict] = []
    seen: set[str] = set()

    for m in PDF_ANCHOR_RE.finditer(html):
        raw = html_lib.unescape(m.group(1).strip())
        url = urljoin(page_url, raw)

        # De-dup only AFTER a URL has been accepted. Do not pre-add.
        if url in seen:
            continue

        if not filt(url):
            continue

        if require_alert_text:
            text = _visible_text(m.group(2))
            if not ALERT_WORD_RE.search(text):
                continue

        # Accepted — mark and record.
        seen.add(url)
        fname = unquote(url.split("/")[-1].split("?")[0])
        found.append({"pdf_url": url, "filename": fname})

    return found


def extract_year_links(html: str, page_url: str) -> list[dict]:
    found = []
    seen = set()
    anchor_re = re.compile(
        r'<a\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.I | re.S,
    )
    year_re = re.compile(r'Drug\s+Alerts?\s+(\d{4})', re.I)
    for m in anchor_re.finditer(html):
        ym = year_re.search(m.group(2))
        if not ym:
            continue
        year = ym.group(1)
        href = html_lib.unescape(m.group(1).strip())
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        found.append({"year": year, "url": url})
    found.sort(key=lambda d: d["year"], reverse=True)
    return found


# --- Fetch ---

def fetch(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=20)


def fetch_year_page(start_url: str, out_file: Path) -> str | None:
    try:
        r = fetch(start_url)
    except Exception as exc:
        print(f"       -> error: {exc}")
        return None
    if r.status_code != 200:
        print(f"       -> HTTP {r.status_code}")
        return None
    out_file.write_text(r.text, encoding="utf-8")
    return r.text


# --- Main ---

def main() -> None:
    if not INPUT_HTML.exists():
        raise SystemExit(f"[!] {INPUT_HTML} not found. Run ipc_test.py first.")

    html = INPUT_HTML.read_text(encoding="utf-8", errors="ignore")

    print("[*] Extracting from saved HTML...")

    main_pdfs = extract_pdfs(
        html, PAGE_URL, is_drug_alert_main_page, require_alert_text=False
    )
    year_links = extract_year_links(html, PAGE_URL)

    print(f"[*] Per-alert PDFs on main page : {len(main_pdfs)}")
    print(f"[*] Year links on main page     : {len(year_links)}")

    all_pdfs: dict[str, dict] = {}

    for p in main_pdfs:
        p["source"] = "main_page"
        p["year"] = year_from_filename(p["filename"]) or ""
        all_pdfs[p["pdf_url"]] = p

    if year_links:
        print(f"\n[*] Following {len(year_links)} year link(s)...")
        for yl in year_links:
            page_year = yl["year"]
            print(f"    {page_year}: {yl['url']}")
            out_file = YEAR_HTML_DIR / f"{page_year}.html"
            text = fetch_year_page(yl["url"], out_file)
            if not text:
                continue

            y_pdfs = extract_pdfs(
                text,
                yl["url"],
                filt=lambda u: not is_master_index(u),
                require_alert_text=True,
            )

            added = 0
            for p in y_pdfs:
                if p["pdf_url"] in all_pdfs:
                    continue
                fn_year = year_from_filename(p["filename"])
                p["year"] = fn_year or page_year
                p["source"] = "year_page"
                all_pdfs[p["pdf_url"]] = p
                added += 1
            print(f"       -> {added} new PDF(s) (page had {len(y_pdfs)} DSA link(s))")

    all_pdfs_list = sorted(
        all_pdfs.values(),
        key=lambda p: (p.get("year") or "0", p["filename"]),
        reverse=True,
    )

    # --- Save ---
    out_json = OUTPUT_DIR / "ipc_pdfs.json"
    out_json.write_text(
        json.dumps(all_pdfs_list, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # --- Diagnostics ---
    by_year: dict[str, list[dict]] = {}
    for p in all_pdfs_list:
        by_year.setdefault(p.get("year") or "?", []).append(p)

    print("\n[*] Per-year summary:")
    print(f"    {'Year':6} {'Count':>5}   Months present")
    for y in sorted(by_year.keys(), reverse=True):
        entries = by_year[y]
        months_present: set[str] = set()
        undated = 0
        for e in entries:
            mn = month_from_filename(e["filename"])
            if mn:
                months_present.add(mn)
            else:
                undated += 1

        header = f"    {y:6} {len(entries):>5}"
        if months_present:
            present_str = ", ".join(m[:3] for m in MONTHS if m in months_present)
            note = f"  (+{undated} undated)" if undated else ""
            print(f"{header}   present: {present_str}{note}")
            absent = [m for m in MONTHS if m not in months_present]
            if absent:
                absent_str = ", ".join(m[:3] for m in absent)
                print(f"    {'':6} {'':>5}   MISSING: {absent_str}")
        else:
            print(f"{header}   (no month name in any filename)")

    print(f"\n[*] Total unique Drug Safety Alert PDFs: {len(all_pdfs_list)}")
    print(f"[+] Saved JSON to    : {out_json}")
    print(f"[+] Saved year HTMLs : {YEAR_HTML_DIR}")


if __name__ == "__main__":
    main()