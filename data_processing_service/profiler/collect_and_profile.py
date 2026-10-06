"""Inventory and structurally profile PDF and JSON objects from S3."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import boto3


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "data_processing_service" / "profiler" / "file_profiles.csv"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_processing_service.shared.config import (
    AWS_REGION,
    S3_INPUT_BUCKET,
    S3_INPUT_PREFIX,
)
from data_processing_service.shared.database import update_profiled_documents
from data_processing_service.profiler.pdf_profile import profile_pdf

DEFAULT_S3_INPUT_PREFIX = S3_INPUT_PREFIX
DEFAULT_S3_INPUT_BUCKET = S3_INPUT_BUCKET
DEFAULT_AWS_REGION = AWS_REGION


CSV_FIELDS = [
    "relative_path",
    "source_name",
    "file_name",
    "pdf_title",
    "file_type",
    "status",
    "structure_classification",
    "total_pages",
    "text_pages",
    "image_pages",
    "empty_pages",
    "table_pages",
    "has_tables",
    "entity_total",
    "json_root_type",
    "json_top_level_keys",
    "json_array_keys",
    "json_record_count",
    "json_item_type",
    "error",
]

RECORD_ARRAY_KEYS = {
    "records", "items", "results", "rows", "data", "nsq_records",
    "spurious_records", "prohibited_drugs", "adr_alerts", "fdc_list",
}


def _item_type(values: list[Any]) -> str:
    if not values:
        return "empty"
    kinds = {"object" if isinstance(value, dict) else "array" if isinstance(value, list) else "value"
             for value in values}
    if len(kinds) > 1:
        return "mixed"
    return kinds.pop()


def _profile_json(content: bytes) -> dict[str, Any]:
    data = json.loads(content.decode("utf-8-sig"))

    row: dict[str, Any] = {
        "status": "ok",
        "json_root_type": "null",
        "json_top_level_keys": "",
        "json_array_keys": "",
        "json_record_count": 0,
        "json_item_type": "",
    }

    if isinstance(data, list):
        row["json_root_type"] = "array"
        row["json_record_count"] = len(data)
        row["json_item_type"] = _item_type(data)
        row["structure_classification"] = (
            "record-array" if row["json_item_type"] == "object"
            else "empty-array" if not data
            else f"{row['json_item_type']}-array"
        )
        return row

    if not isinstance(data, dict):
        row["structure_classification"] = "json-scalar"
        return row

    row["json_root_type"] = "object"
    row["json_top_level_keys"] = "|".join(str(key) for key in data)
    arrays = {
        str(key): value for key, value in data.items()
        if isinstance(value, list)
        and (str(key).casefold() in RECORD_ARRAY_KEYS
             or any(isinstance(item, dict) for item in value))
    }
    row["json_array_keys"] = "|".join(arrays)

    if arrays:
        row["json_record_count"] = sum(len(value) for value in arrays.values())
        row["json_item_type"] = _item_type(
            [item for values in arrays.values() for item in values]
        )
        row["structure_classification"] = (
            "object-with-record-arrays"
            if row["json_item_type"] == "object"
            else "object-with-arrays"
        )
    else:
        row["structure_classification"] = "object-no-record-array"
    return row


def _base_row(key: str, prefix: str) -> dict[str, Any]:
    relative_key = key.removeprefix(f"{prefix.rstrip('/')}/") if prefix else key
    relative_path = PurePosixPath(relative_key)
    return {
        "relative_path": relative_path.as_posix(),
        "source_name": relative_path.parts[0] if len(relative_path.parts) > 1 else "",
        "file_name": relative_path.name,
        "pdf_title": "",
        "file_type": relative_path.suffix.lower().lstrip("."),
        "status": "ok",
        "structure_classification": "",
        "total_pages": "",
        "text_pages": "",
        "image_pages": "",
        "empty_pages": "",
        "table_pages": "",
        "has_tables": "",
        "entity_total": "",
        "json_root_type": "",
        "json_top_level_keys": "",
        "json_array_keys": "",
        "json_record_count": "",
        "json_item_type": "",
        "error": "",
    }


def profile_s3_object(s3_client: Any, bucket: str, key: str, prefix: str) -> dict[str, Any]:
    row = _base_row(key, prefix)
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        if row["file_type"] == "pdf":
            with tempfile.TemporaryDirectory() as temp_dir:
                pdf_path = Path(temp_dir) / row["file_name"]
                pdf_path.write_bytes(content)
                profile = profile_pdf(pdf_path, row["source_name"] or bucket)
            structure = profile["structure"]
            pages = profile["page_profile"]
            row.update({
                "structure_classification": structure["primary_type"],
                "total_pages": profile["total_pages"],
                "text_pages": structure["text_pages"],
                "image_pages": structure["image_pages"],
                "empty_pages": structure["empty_pages"],
                "table_pages": sum(1 for page in pages if page["has_table"]),
                "has_tables": structure["has_tables"],
                "entity_total": structure["entity_total"],
            })
        else:
            row.update(_profile_json(content))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        row["status"] = "error"
        row["structure_classification"] = "unreadable"
        row["error"] = str(exc).replace("\n", " ")[:300]
    except Exception as exc:
        row["status"] = "error"
        row["structure_classification"] = "processing-error"
        row["error"] = str(exc).replace("\n", " ")[:300]
    return row


def collect_s3_objects(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(
            item["Key"] for item in page.get("Contents", [])
            if PurePosixPath(item["Key"]).suffix.lower() in {".pdf", ".json"}
        )
    return sorted(keys, key=str.casefold)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect and profile PDF and JSON objects from an S3 bucket."
    )
    parser.add_argument("--bucket", default=DEFAULT_S3_INPUT_BUCKET,
                        help="S3 input bucket (defaults to AWS_S3_INPUT_BUCKET)")
    parser.add_argument("--prefix", default=DEFAULT_S3_INPUT_PREFIX,
                        help=f"S3 input key prefix (default: {DEFAULT_S3_INPUT_PREFIX})")
    parser.add_argument("--region", default=DEFAULT_AWS_REGION,
                        help=f"AWS region (default: {DEFAULT_AWS_REGION})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"CSV output path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--doc-id", help="Process only this exact S3 object key")
    parser.add_argument("--limit", type=int, default=0,
                        help="Optional file limit for a quick test; default processes all files")
    args = parser.parse_args(argv)

    if not args.bucket:
        parser.error("S3 bucket is required; set AWS_S3_BUCKET_NAME or pass --bucket")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    prefix = args.prefix.strip("/")
    if prefix:
        prefix += "/"
    s3_client = boto3.client("s3", region_name=args.region)
    files = collect_s3_objects(s3_client, args.bucket, prefix)
    if args.doc_id:
        files = [key for key in files if key == args.doc_id]
    if args.limit:
        files = files[:args.limit]
    if args.doc_id and not files:
        print(f"No matching S3 object: {args.doc_id}", file=sys.stderr)
        return 1

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile_results = []
    rows = []
    for index, key in enumerate(files, start=1):
        row = profile_s3_object(s3_client, args.bucket, key, prefix)
        rows.append(row)
        profile_results.append((key, row["status"]))
        if index % 100 == 0 or index == len(files):
            print(f"Profiled {index}/{len(files)} files")

    updated_count, unmatched_count, titles_by_key = update_profiled_documents(profile_results)
    for key, row in zip(files, rows):
        row["pdf_title"] = titles_by_key.get(key, "")

    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Found {len(files)} PDF/JSON objects in s3://{args.bucket}/{prefix}")
    print(f"Updated profile status for {updated_count} database rows; {unmatched_count} objects had no matching row")
    print(f"CSV written locally to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())