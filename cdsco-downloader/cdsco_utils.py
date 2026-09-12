"""
Shared utilities for CDSCO / IPC downloaders.
Handles the two‑layer PDF wrapper (download_file_division.jsp → iframe → real PDF),
retries, polite delays, filename sanitisation, and metadata logging.
"""

import base64
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Resolve downloads root relative to the repo, not the CWD.
# cdsco_utils.py lives in cdsco-downloader/, so parent.parent == repo root.
DOWNLOADS_ROOT = Path(__file__).resolve().parent.parent / "downloads"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CDSCO_BASE = "https://cdsco.gov.in"
WRAPPER_PATH = (
    "/opencms/opencms/system/modules/CDSCO.WEB/elements/"
    "download_file_division.jsp"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# Polite delay between downloads (seconds)
DELAY = 0.5

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = DOWNLOADS_ROOT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_download_root() -> Path:
    """Return the single shared downloads directory at repo root."""
    return ensure_dir(DOWNLOAD_ROOT)


def get_download_dir(category: str) -> Path:
    """Return a category-specific directory under the shared root."""
    return ensure_dir(get_download_root() / category)


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Turn a title into a safe filename fragment."""
    name = re.sub(r"[^\w\s\-.]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:max_len] or "document"


def base64_decode_num_id(num_id_b64: str) -> int | None:
    """Decode num_id (base64) → integer document_id."""
    try:
        return int(base64.b64decode(num_id_b64).decode("utf-8"))
    except Exception:
        return None


def extract_num_id_from_href(href: str) -> str | None:
    """Return the base64 num_id from a CDSCO download link."""
    if "num_id=" not in href:
        return None
    return href.split("num_id=")[1].split("&")[0]


# ---------------------------------------------------------------------------
# Core: resolve a CDSCO wrapped PDF
# ---------------------------------------------------------------------------
def resolve_cdsco_pdf(
    num_id_b64: str,
    referer: str | None = None,
    max_retries: int = 3,
) -> bytes | None:
    """
    Given a base64 num_id, fetch the wrapper, follow the iframe,
    and return the raw PDF bytes.

    Returns None on failure.
    """
    wrapper_url = (
        f"{CDSCO_BASE}{WRAPPER_PATH}?num_id={num_id_b64}"
    )
    headers = {"Referer": referer} if referer else {}

    for attempt in range(1, max_retries + 1):
        try:
            resp = SESSION.get(
                wrapper_url, headers=headers, timeout=30
            )
            resp.raise_for_status()

            # Direct PDF (rare)
            if resp.content.startswith(b"%PDF-"):
                return resp.content

            # Wrapper HTML → find iframe
            soup = BeautifulSoup(resp.text, "html.parser")
            iframe = soup.find("iframe")
            if not iframe or not iframe.get("src"):
                log.warning("No iframe found for num_id=%s", num_id_b64)
                return None

            inner_url = urljoin(wrapper_url, iframe["src"].strip())

            # Fetch real PDF
            pdf_resp = SESSION.get(
                inner_url,
                headers={**HEADERS, **({"Referer": wrapper_url} if referer else {})},
                timeout=60,
            )
            pdf_resp.raise_for_status()

            if not pdf_resp.content.startswith(b"%PDF-"):
                log.warning(
                    "Inner response is not a PDF for num_id=%s: %s",
                    num_id_b64,
                    inner_url,
                )
                return None

            return pdf_resp.content

        except requests.RequestException as exc:
            log.warning(
                "Attempt %d/%d failed for num_id=%s: %s",
                attempt,
                max_retries,
                num_id_b64,
                exc,
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

    return None


def download_pdf(
    url: str,
    dest_path: Path,
    referer: str | None = None,
    max_retries: int = 3,
) -> bool:
    """Download a direct PDF URL to dest_path. Returns True on success."""
    headers = {"Referer": referer} if referer else {}
    for attempt in range(1, max_retries + 1):
        try:
            resp = SESSION.get(url, headers=headers, timeout=60, stream=True)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            return True
        except requests.RequestException as exc:
            log.warning(
                "Attempt %d/%d failed for %s: %s", attempt, max_retries, url, exc
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    return False


# ---------------------------------------------------------------------------
# Metadata helper
# ---------------------------------------------------------------------------
def save_metadata(records: list[dict], path: Path) -> None:
    path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Saved %d metadata records to %s", len(records), path)