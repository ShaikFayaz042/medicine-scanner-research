"""Backfill document provenance metadata into a new JSONL file.

The script only reads structured_raw, downloads, website scrape outputs, and
metadata files. It never modifies documents.jsonl in place.
It never modifies documents.jsonl in place.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "normalization" / "output" / "documents.jsonl"
DEFAULT_OUTPUT = ROOT / "normalization" / "output" / "documents_with_provenance.jsonl"
DEFAULT_DOWNLOADS = ROOT / "downloads"
DEFAULT_STRUCTURED_RAW = ROOT / "structured_raw"
DEFAULT_WEBSITES = ROOT / "websites"

URL_KEYS = ("source_url", "url", "download_url", "pdf_url")
FILENAME_KEYS = ("pdf_filename", "filename", "source_file", "local_path", "path")
DOCUMENT_ID_KEYS = ("document_id", "doc_id", "num_id")


def iter_json_records(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_records(child)


def filename_from_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = Path(value.replace("\\", "/")).name
    return name if name.lower().endswith(".pdf") else None


def build_pdf_index(downloads_dir: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in downloads_dir.rglob("*.pdf"):
        index.setdefault(path.name, []).append(path)
    return index


def build_metadata_index(*metadata_roots: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for metadata_root in metadata_roots:
        for metadata_path in metadata_root.rglob("*.json"):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for record in iter_json_records(payload):
                filename = next(
                    (filename_from_value(record.get(key)) for key in FILENAME_KEYS),
                    None,
                )
                source_url = next(
                    (record.get(key) for key in URL_KEYS if isinstance(record.get(key), str)),
                    None,
                )
                keys: list[str] = []
                if filename:
                    keys.append(f"filename:{filename}")
                document_id = next(
                    (str(record.get(key)) for key in DOCUMENT_ID_KEYS if record.get(key) is not None),
                    None,
                )
                if document_id:
                    keys.append(f"document_id:{document_id}")
                for key in keys:
                    if source_url or key not in index:
                        index[key] = {"source_url": source_url}
    return index


def sha256_file(path: Path, cache: dict[Path, str]) -> str:
    if path not in cache:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        cache[path] = digest.hexdigest()
    return cache[path]


def backfill(
    input_path: Path,
    output_path: Path,
    downloads_dir: Path,
    structured_raw_dir: Path,
    websites_dir: Path,
) -> tuple[int, int, int, int]:
    pdf_index = build_pdf_index(downloads_dir)
    metadata_index = build_metadata_index(downloads_dir, structured_raw_dir, websites_dir)
    hash_cache: dict[Path, str] = {}
    rows = matched_pdfs = hashes_added = urls_added = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as target:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            filename = filename_from_value(row.get("pdf_filename"))
            candidates = pdf_index.get(filename or "", [])
            pdf_path = candidates[0] if len(candidates) == 1 else None
            if pdf_path:
                matched_pdfs += 1
                if not row.get("file_hash"):
                    row["file_hash"] = sha256_file(pdf_path, hash_cache)
                    hashes_added += 1
            metadata = metadata_index.get(f"filename:{filename}")
            if not metadata and row.get("document_id") is not None:
                metadata = metadata_index.get(f"document_id:{row['document_id']}")
            if metadata and not row.get("source_url") and metadata.get("source_url"):
                row["source_url"] = metadata["source_url"]
                urls_added += 1
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows += 1

    return rows, matched_pdfs, hashes_added, urls_added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS)
    parser.add_argument("--structured-raw", type=Path, default=DEFAULT_STRUCTURED_RAW)
    parser.add_argument("--websites", type=Path, default=DEFAULT_WEBSITES)
    args = parser.parse_args()

    rows, matched, hashes_added, urls_added = backfill(
        args.input, args.output, args.downloads, args.structured_raw, args.websites
    )
    print(f"[ok] wrote {rows} rows -> {args.output}")
    print(f"[ok] uniquely matched PDFs: {matched}")
    print(f"[ok] file_hash values added: {hashes_added}")
    print(f"[ok] source_url values added: {urls_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
