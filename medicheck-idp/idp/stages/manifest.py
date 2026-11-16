"""Stage 0: create an idempotent manifest for the source PDF."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from idp.schemas.manifest import DocumentManifest
from idp.storage import artifacts

_ARTIFACT = "00_manifest/document_manifest"


def _file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def run(pdf_path: str | Path) -> DocumentManifest:
    """Write `document_manifest.json`, preserving the first upload time on retries."""
    path = Path(pdf_path)
    sha256, size_bytes = _file_identity(path)
    cached = artifacts.load(_ARTIFACT, sha256, DocumentManifest)
    if cached is not None and cached.sha256 == sha256 and cached.size_bytes == size_bytes:
        return cached

    manifest = DocumentManifest(
        doc_id=sha256,
        file_name=path.name,
        size_bytes=size_bytes,
        sha256=sha256,
        upload_time=datetime.now(timezone.utc),
    )
    artifacts.save(_ARTIFACT, sha256, manifest)
    return manifest
