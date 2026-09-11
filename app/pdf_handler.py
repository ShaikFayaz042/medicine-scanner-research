"""PDF download handler — resolves the iframe wrapper and downloads the real PDF."""
import hashlib
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import PDF_DIR, USER_AGENT


def _fetch_pdf_bytes(url: str, referer: str | None = None) -> bytes:
    """Follow wrapper -> iframe -> real PDF. Returns PDF bytes."""
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer

    resp = requests.get(url, headers=headers, timeout=60)
    ctype = resp.headers.get("Content-Type", "").lower()

    # Case 1: direct PDF
    if "application/pdf" in ctype or resp.content.startswith(b"%PDF-"):
        return resp.content

    # Case 2: HTML wrapper with iframe
    if "text/html" in ctype:
        soup = BeautifulSoup(resp.text, "html.parser")
        iframe = soup.find("iframe")
        if iframe and iframe.get("src"):
            inner = iframe["src"].strip()
            inner_url = urljoin(url, inner)

            # If iframe points to a PDF.js viewer, unwrap the file= param
            if "file=" in inner_url:
                file_part = inner_url.split("file=", 1)[1].split("&")[0]
                inner_url = urljoin(url, file_part)

            return _fetch_pdf_bytes(inner_url, referer=url)

    raise RuntimeError(
        f"Could not resolve PDF from {url}. "
        f"Content-Type={ctype}, first bytes={resp.content[:80]!r}"
    )


def download_pdf(document_id: int, pdf_url: str) -> dict:
    """
    Download the PDF for a document.
    Returns: local_file_path, file_size_bytes, content_hash (sha256).
    """
    pdf_bytes = _fetch_pdf_bytes(pdf_url)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError(f"Downloaded content is not a PDF (document_id={document_id})")

    out_path = PDF_DIR / f"{document_id}.pdf"
    out_path.write_bytes(pdf_bytes)

    return {
        "local_file_path": str(out_path),
        "file_size_bytes": len(pdf_bytes),
        "content_hash": hashlib.sha256(pdf_bytes).hexdigest(),
    }
