"""Print schema of normalized document output CSVs from S3.

Usage:
    python data_processing_service/scripts/inspect_normalized.py \
      --bucket $Bucket \
      --prefix medicine-data-storage/processed_files/normalized \
      --samples 2
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path, PurePosixPath

import boto3


def _list_folders(client, bucket: str, prefix: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    folders: set[str] = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.strip("/")):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.endswith(".csv"):
                continue
            folder = str(PurePosixPath(key).parent)
            folders.add(folder)
    return sorted(folders)


def _list_csvs(client, bucket: str, folder: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=folder.strip("/") + "/"):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith(".csv"):
                keys.append(key)
    return sorted(keys)


def _read_csv(client, bucket: str, key: str, n: int = 2):
    response = client.get_object(Bucket=bucket, Key=key)
    text = response["Body"].read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1 : 1 + n]


def main() -> int:
    ap = argparse.ArgumentParser(description="Print schema for normalized staging CSVs.")
    ap.add_argument("--bucket", required=True, help="S3 bucket containing normalized output")
    ap.add_argument("--prefix", required=True, help="Normalized prefix to inspect")
    ap.add_argument("--region", default="ap-south-1", help="AWS region")
    ap.add_argument(
        "--samples",
        type=int,
        default=2,
        help="How many document folders to inspect",
    )
    args = ap.parse_args()

    client = boto3.client("s3", region_name=args.region)
    folders = _list_folders(client, args.bucket, args.prefix)
    print(f"Total document folders: {len(folders)}")

    if not folders:
        print("No folders found.")
        return 1

    for folder in folders[: args.samples]:
        print(f"\n{'=' * 80}")
        print(f"FOLDER: {folder}")
        print(f"{'=' * 80}")

        for csv_key in _list_csvs(client, args.bucket, folder):
            name = Path(csv_key).name
            try:
                headers, sample = _read_csv(client, args.bucket, csv_key)
            except Exception as exc:  # pragma: no cover - debugging helper
                print(f"  {name}: ERROR {exc}")
                continue

            print(f"\n  {name}:")
            print(f"    columns ({len(headers)}): {headers}")
            for i, row in enumerate(sample):
                truncated = [
                    (cell[:120] + "...") if len(cell) > 120 else cell
                    for cell in row
                ]
                print(f"    row[{i}]  : {truncated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
