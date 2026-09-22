"""PDF download handler — resolves the iframe wrapper and downloads the real PDF."""
import hashlib
from pathlib import PurePosixPath
from urllib.parse import urljoin

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError
from bs4 import BeautifulSoup

from cloud_worker.config import (
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_PREFIX,
    S3_SOURCE_FOLDERS,
    S3_SOURCE_PREFIX,
    USER_AGENT,
)


def _fetch_pdf_bytes(url: str, referer: str | None = None) -> bytes:
    """Follow wrapper -> iframe -> real PDF. Returns PDF bytes."""
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "").lower()

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

            return _fetch_pdf_bytes(inner_url, referer=url)

    raise RuntimeError(
        f"Could not resolve PDF from {url}. "
        f"Content-Type={ctype}, first bytes={resp.content[:80]!r}"
    )


def download_pdf(
    document_id: int,
    pdf_url: str,
    source_name: str = "cdsco_alerts",
    filename: str | None = None,
) -> dict:
    """Download the PDF for a document and return metadata."""
    pdf_bytes = _fetch_pdf_bytes(pdf_url)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError(f"Downloaded content is not a PDF (document_id={document_id})")

    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not configured.")

    bucket_prefix = (S3_PREFIX or "").strip("/")
    source_prefix = (S3_SOURCE_PREFIX or "").strip("/")
    folder = S3_SOURCE_FOLDERS.get(source_name, source_name)
    parts = [part for part in (bucket_prefix, source_prefix, folder) if part]
    object_name = PurePosixPath(filename).name if filename else f"{document_id}.pdf"
    object_key = "/".join(parts) + f"/{object_name}"

    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=object_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 upload failed for document_id={document_id}: {exc}") from exc

    file_size_bytes = len(pdf_bytes)
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    return {
        "s3_object_key": object_key,
        "file_size_bytes": file_size_bytes,
        "content_hash": content_hash,
    }
