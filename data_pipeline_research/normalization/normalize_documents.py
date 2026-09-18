"""Emit regulatory_documents rows from structured_raw/<folder>/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR,
    ROOT,
    STRUCTURED_RAW,
    load_all_configs,
    read_json,
    safe_str,
    sha256_file,
    utcnow_iso,
    write_jsonl,
    parse_date_with_precision,
)

SOURCE_ORG_BY_FOLDER = {
    "pvpi_safety": "PvPI",
}
SOURCE_CATEGORY_BY_FOLDER = {
    "nsq": "ALERTS",
    "spurious": "ALERTS",
    "drug_alert": "ALERTS",
    "fdc_prohibited": "FDC",
    "fdc_notification": "FDC",
    "gazette_legal": "GAZETTE",
    "pvpi_safety": "IPC_PVPI",
    "theft_recall": "ALERTS",
    "medical_device": "ALERTS",
    "ivd_alert": "ALERTS",
    "circular": "PUBLIC_NOTICES",
    "guideline": "PUBLIC_NOTICES",
    "other": "PUBLIC_NOTICES",
}


def load_classification_confidence() -> dict[tuple[str, str], float]:
    """Index classifier confidence by (folder, source filename)."""
    confidence: dict[tuple[str, str], float] = {}
    manifest_folder_aliases = {
        "nsq_alert": "nsq",
        "spurious_alert": "spurious",
    }
    classification_root = ROOT / "type_classification"
    for manifest in classification_root.glob("*/_manifest.json"):
        try:
            payload = read_json(manifest)
        except (OSError, json.JSONDecodeError):
            continue
        folder = manifest_folder_aliases.get(manifest.parent.name, manifest.parent.name)
        for item in payload.get("documents", []):
            filename = item.get("filename")
            value = item.get("classification_confidence")
            if filename and value is not None:
                confidence[(folder, filename)] = float(value)
    return confidence


def iter_document_files(folder_dir: Path) -> list[Path]:
    return [path for path in sorted(folder_dir.glob("*.json")) if not path.name.startswith("_")]


def find_pdf_hash(doc: dict, json_path: Path) -> str | None:
    for raw_path in doc.get("pdf_paths") or []:
        pdf_path = ROOT / Path(str(raw_path).replace("\\", "/"))
        digest = sha256_file(pdf_path)
        if digest:
            return digest
    return sha256_file(json_path)


def build_document_row(
    folder: str,
    file: Path,
    data: dict,
    document_type: str,
    contract: dict,
    confidence_by_file: dict[tuple[str, str], float],
) -> dict:
    if document_type not in contract["document_type_values"]:
        raise ValueError(f"Unsupported document_type {document_type!r}: {file}")

    document = data.get("document") or data
    extraction = data.get("extraction") or {}
    publication_raw = safe_str(
        document.get("publication_date")
        or document.get("date")
        or document.get("issue_date")
    )
    publication_date, precision = parse_date_with_precision(publication_raw)
    source_file = safe_str(document.get("source_file"))
    return {
        "source_org": SOURCE_ORG_BY_FOLDER.get(folder, "CDSCO"),
        "source_category": SOURCE_CATEGORY_BY_FOLDER.get(folder, "ALERTS"),
        "document_type": document_type,
        "title": safe_str(document.get("title") or document.get("subject") or file.stem),
        "publication_date": publication_date.isoformat() if publication_date else None,
        "publication_date_raw": publication_raw,
        "publication_date_precision": precision,
        "document_id": safe_str(document.get("document_id") or document.get("doc_id")),
        "source_url": safe_str(document.get("source_url") or document.get("url")),
        "pdf_filename": safe_str(document.get("source_file") or document.get("pdf_filename")),
        "file_hash": find_pdf_hash(document, file),
        "raw_text": None,
        "extraction_method": safe_str(extraction.get("extraction_method")),
        "extraction_status": safe_str(extraction.get("status")),
        "extraction_confidence": confidence_by_file.get((folder, source_file or "")),
        "_folder": folder,
        "_source_file": str(file.relative_to(STRUCTURED_RAW)).replace("\\", "/"),
        "_normalized_at": utcnow_iso(),
    }


def main() -> int:
    configs = load_all_configs()
    field_mapping = configs["field_mapping"]
    contract = configs["schema_contract"]
    rows: list[dict] = []
    confidence_by_file = load_classification_confidence()
    folders_seen = 0
    missing_folders = 0

    for folder, document_type in field_mapping["folder_name_aliases"].items():
        folder_dir = STRUCTURED_RAW / folder
        if not folder_dir.is_dir():
            missing_folders += 1
            print(f"[skip] folder missing: {folder_dir}")
            continue
        folders_seen += 1
        for file in iter_document_files(folder_dir):
            try:
                rows.append(build_document_row(
                    folder, file, read_json(file), document_type, contract, confidence_by_file,
                ))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"[error] {file}: {exc}")

    output = OUTPUT_DIR / "documents.jsonl"
    count = write_jsonl(rows, output)
    print(f"[ok] folders scanned: {folders_seen} (missing: {missing_folders})")
    print(f"[ok] wrote {count} documents -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
