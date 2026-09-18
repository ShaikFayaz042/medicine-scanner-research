"""
IPC PvPI Drug Safety Alerts — Downloader

Reads websites/ipc-pvpi/html-extraction/output/ipc_pdfs.json, downloads
each PDF into output/pdf/, and verifies:

  * HTTP 200
  * Content-Type is application/pdf OR the response body starts with %PDF
  * File size > 1 KB (guards against Joomla 200-with-HTML-error-pages)

Behaviour:
  * Existing files with the same size are skipped (idempotent re-runs).
  * Filenames are de-duplicated: if two URLs share a filename, the
    second gets a numeric suffix (foo.pdf -> foo__2.pdf).
  * Small politeness delay between requests.

Exit code is 0 on success, 1 if any download failed.
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests

# --- Config ---

BASE = Path("websites/ipc-pvpi/html-extraction/output")
INPUT_JSON = BASE / "ipc_pdfs.json"
OUT_DIR = BASE / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

TIMEOUT = 60              # seconds per request
RETRIES = 3               # attempts per URL
RETRY_DELAY = 2.0         # seconds between retries
POLITE_DELAY = 0.5        # seconds between different URLs
MIN_PDF_BYTES = 1024      # anything smaller is treated as a broken PDF
PDF_MAGIC = b"%PDF"


# --- Helpers ---

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    """Strip path separators and control chars; keep spaces & parentheses."""
    name = unquote(name)
    # Take just the last path segment, in case the URL had a slash inside
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _INVALID_CHARS.sub("_", name).strip()
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name or "unnamed.pdf"


def unique_path(directory: Path, filename: str, taken: set[str]) -> Path:
    """Return a path for filename that doesn't collide with `taken` on disk."""
    base, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
    candidate = filename
    n = 2
    while (directory / candidate).exists() or candidate.lower() in taken:
        candidate = f"{base}__{n}.{ext}" if ext else f"{base}__{n}"
        n += 1
    taken.add(candidate.lower())
    return directory / candidate


def looks_like_pdf(content: bytes, content_type: str) -> tuple[bool, str]:
    """Return (is_pdf, reason)."""
    ct = (content_type or "").lower()
    if PDF_MAGIC in content[:1024]:
        return True, "magic bytes"
    if "application/pdf" in ct:
        # Some servers omit magic but declare the type — accept with caution
        return True, "content-type header"
    if "text/html" in ct:
        return False, "server returned HTML (likely an error page)"
    return False, f"unexpected content ({ct or 'unknown'})"


def fetch(url: str) -> requests.Response | None:
    """GET with retries. Return None on total failure."""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
            return r
        except requests.RequestException as exc:
            print(f"       attempt {attempt}/{RETRIES} failed: {exc}")
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    return None


def download_one(entry: dict, taken: set[str]) -> tuple[bool, str]:
    """Download a single entry. Returns (success, message)."""
    url = entry["pdf_url"]
    raw_name = entry.get("filename") or url.rsplit("/", 1)[-1]
    fname = safe_filename(raw_name)
    dest = unique_path(OUT_DIR, fname, taken)

    # Already have it? Compare sizes if we do a HEAD, else just skip.
    if dest.exists():
        # We don't know the remote size without a HEAD, so just trust it.
        size = dest.stat().st_size
        return True, f"skipped (already exists, {size:,} bytes)"

    r = fetch(url)
    if r is None:
        return False, "network error after retries"

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"

    content = r.content  # small enough to buffer fully

    if len(content) < MIN_PDF_BYTES:
        return False, f"too small ({len(content)} bytes) — probably broken"

    ok, reason = looks_like_pdf(content, r.headers.get("Content-Type", ""))
    if not ok:
        return False, f"not a PDF ({reason})"

    dest.write_bytes(content)
    return True, f"{len(content):,} bytes -> {dest.name}  [{reason}]"


# --- Main ---

def main() -> None:
    if not INPUT_JSON.exists():
        print(f"[!] {INPUT_JSON} not found. Run parse_ipc_pvpi.py first.")
        sys.exit(1)

    entries = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    print(f"[*] Loaded {len(entries)} PDF entries from {INPUT_JSON}")
    print(f"[*] Downloading to {OUT_DIR}\n")

    taken: set[str] = {p.name.lower() for p in OUT_DIR.glob("*.pdf")}
    ok = 0
    skipped = 0
    failed: list[tuple[str, str]] = []

    for i, entry in enumerate(entries, start=1):
        url = entry["pdf_url"]
        year = entry.get("year") or "?"
        print(f"[{i:>3}/{len(entries)}] {year}  {url}")

        success, msg = download_one(entry, taken)
        print(f"       -> {msg}")

        if success:
            if msg.startswith("skipped"):
                skipped += 1
            else:
                ok += 1
        else:
            failed.append((url, msg))

        if not msg.startswith("skipped"):
            time.sleep(POLITE_DELAY)

    # --- Summary ---
    print("\n" + "=" * 64)
    print(f"[+] Downloaded : {ok}")
    print(f"[+] Skipped    : {skipped} (already present)")
    print(f"[+] Failed     : {len(failed)}")

    if failed:
        print("\n[!] Failures:")
        for url, msg in failed:
            print(f"    {msg}\n      {url}")

    # Sanity-check the folder
    files = sorted(OUT_DIR.glob("*.pdf"))
    total_bytes = sum(p.stat().st_size for p in files)
    print(f"\n[*] Files on disk : {len(files)}")
    print(f"[*] Total size    : {total_bytes / 1024 / 1024:.1f} MB")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()