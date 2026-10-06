"""Normalize parsed regulatory JSON with the validated ingestion implementation."""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path, PurePosixPath

import boto3

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_processing_service.normalizer.pipeline import run_pipeline  # noqa: E402
from data_processing_service.shared.config import AWS_REGION, S3_INPUT_BUCKET, S3_INPUT_PREFIX  # noqa: E402
from data_processing_service.shared.scraper_status import set_scraper_document_status  # noqa: E402


DEFAULT_INPUT_PREFIX = "medicine-data-storage/processed_files/parsed_json"
DEFAULT_PROFILER_PREFIX = "medicine-data-storage/processed_files/profiler_output"
DEFAULT_NSQ_PREFIX = f"{S3_INPUT_PREFIX.rstrip('/')}/nsq"
DEFAULT_OUTPUT_PREFIX = "medicine-data-storage/processed_files/normalized"
PROFILER_JSON_FOLDERS = {"nsq_json", "spurious_json"}
STAGING_FILES = (
    "regulatory_documents.csv",
    "raw_source_records.csv",
    "organizations.csv",
    "ingredients.csv",
    "products.csv",
    "product_ingredients.csv",
    "product_organizations.csv",
    "batches.csv",
    "regulatory_events.csv",
    "normalization_manifest.csv",
)


def _iter_json_keys(
    s3_client,
    bucket: str,
    prefix: str,
    allowed_folders: set[str] | None = None,
) -> list[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if PurePosixPath(key).suffix.lower() != ".json":
                continue
            if allowed_folders is not None:
                relative = key[len(prefix.strip("/")):].lstrip("/")
                folder, separator, _ = relative.partition("/")
                if not separator or folder not in allowed_folders:
                    continue
            keys.append(key)
    return sorted(keys, key=str.casefold)


def _output_key(output_prefix: str, input_prefix: str, input_key: str, filename: str) -> str:
    prefix = input_prefix.strip("/")
    relative = input_key[len(prefix):].lstrip("/") if prefix else input_key
    relative_path = PurePosixPath(relative)
    document_path = relative_path.parent / relative_path.stem / filename
    return str(PurePosixPath(output_prefix.strip("/")) / document_path)


def normalize_local_file(input_path: Path, output_dir: Path) -> int:
    """Run normalization and validation for one local parsed JSON file."""
    return run_pipeline(str(input_path), str(output_dir), load_db_flag=False)


def _normalize_s3_file(
    s3_client,
    input_bucket: str,
    input_prefix: str,
    input_key: str,
    output_bucket: str,
    output_prefix: str,
) -> int:
    response = s3_client.get_object(Bucket=input_bucket, Key=input_key)
    parsed_json = response["Body"].read()

    with tempfile.TemporaryDirectory(prefix="medicine-normalize-") as temp_dir:
        temp_root = Path(temp_dir)
        input_path = temp_root / PurePosixPath(input_key).name
        staging_dir = temp_root / "staging"
        input_path.write_bytes(parsed_json)

        result = run_pipeline(str(input_path), str(staging_dir), load_db_flag=False)
        if result != 0:
            return result

        document_csv = staging_dir / "regulatory_documents.csv"
        with document_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            document_headers = reader.fieldnames or []
            document_rows = list(reader)
        if not document_rows:
            raise RuntimeError("Normalized output has no regulatory document row")
        document_row = document_rows[0]
        source_url = document_row.get("source_url") or ""
        if source_url.startswith(str(temp_root)):
            source_url = input_key
            document_row["source_url"] = source_url
            with document_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=document_headers)
                writer.writeheader()
                writer.writerow(document_row)

        for filename in STAGING_FILES:
            staging_file = staging_dir / filename
            if not staging_file.is_file():
                raise RuntimeError(f"Validated staging output is missing: {filename}")
            output_key = _output_key(output_prefix, input_prefix, input_key, filename)
            s3_client.upload_file(str(staging_file), output_bucket, output_key)
            print(f"Uploaded s3://{output_bucket}/{output_key}")

        status_result = set_scraper_document_status(
            status="normalized",
            source_document_id=document_row.get("source_document_id"),
            source_url=source_url,
            source_s3_key=input_key,
        )
        if not status_result.get("updated"):
            raise RuntimeError(f"Scraper status was not updated: {status_result.get('reason', status_result.get('error'))}")
        print(f"Scraper document status updated: normalized ({status_result.get('matched_by')})")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize parsed JSON into validated per-document staging CSVs."
    )
    parser.add_argument("--input", type=Path, help="One local parsed JSON file instead of scanning S3")
    parser.add_argument(
        "--out",
        type=Path,
        help="Local staging output directory (defaults to data_processing_service/normalizer/local_output/<file>)",
    )
    parser.add_argument("--bucket", default=S3_INPUT_BUCKET, help="S3 bucket containing parsed JSON files")
    parser.add_argument("--prefix", default=DEFAULT_INPUT_PREFIX, help="S3 prefix to scan for parsed JSON files")
    parser.add_argument(
        "--profiler-prefix",
        default=DEFAULT_PROFILER_PREFIX,
        help="Legacy S3 prefix; only nsq_json/ and spurious_json/ folders are normalized",
    )
    parser.add_argument(
        "--nsq-prefix",
        default=DEFAULT_NSQ_PREFIX,
        help="S3 prefix containing scraper NSQ and spurious JSON files",
    )
    parser.add_argument("--region", default=AWS_REGION, help="AWS region")
    parser.add_argument("--s3-output-bucket", default=None, help="Bucket for validated staging CSVs")
    parser.add_argument("--s3-output-prefix", default=DEFAULT_OUTPUT_PREFIX, help="Base prefix for staging CSVs")
    parser.add_argument("--doc-id", help="Normalize only this exact input S3 JSON key")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of S3 documents to process")
    args = parser.parse_args(argv)

    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    if args.input:
        if not args.input.is_file():
            parser.error(f"--input must point to an existing JSON file: {args.input}")
        output_dir = args.out or (
            REPO_ROOT / "data_processing_service" / "normalizer" / "local_output" / args.input.stem
        )
        return normalize_local_file(args.input, output_dir)

    if not args.bucket:
        parser.error("--bucket is required when --input is not supplied")
    if not args.s3_output_bucket:
        args.s3_output_bucket = args.bucket

    s3_client = boto3.client("s3", region_name=args.region)
    sources = [
        (key, args.prefix)
        for key in _iter_json_keys(s3_client, args.bucket, args.prefix)
    ]
    sources.extend(
        (key, args.profiler_prefix)
        for key in _iter_json_keys(
            s3_client,
            args.bucket,
            args.profiler_prefix,
            allowed_folders=PROFILER_JSON_FOLDERS,
        )
    )
    nsq_output_prefix = args.nsq_prefix.strip("/").rsplit("/", 1)[0]
    sources.extend(
        (key, nsq_output_prefix)
        for key in _iter_json_keys(s3_client, args.bucket, args.nsq_prefix)
    )
    sources = sorted(dict(sources).items(), key=lambda item: item[0].casefold())
    if args.doc_id:
        sources = [source for source in sources if source[0] == args.doc_id]
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        print(
            "No JSON files found under parsed_json, source_files/nsq, "
            "or legacy profiler nsq_json/spurious_json prefixes.",
            file=sys.stderr,
        )
        return 1

    failed = 0
    for index, (key, source_prefix) in enumerate(sources, start=1):
        try:
            result = _normalize_s3_file(
                s3_client,
                args.bucket,
                source_prefix,
                key,
                args.s3_output_bucket,
                args.s3_output_prefix,
            )
            if result:
                failed += 1
                print(f"FAILED {index}/{len(sources)}: {key}", file=sys.stderr)
            else:
                print(f"Normalized {index}/{len(sources)}: {key}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {index}/{len(sources)} {key}: {exc}", file=sys.stderr)

    print(f"Normalization complete: {len(sources) - failed}/{len(sources)} documents passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())