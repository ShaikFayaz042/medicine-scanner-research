"""JSON artifact upload handling for structured scraper sources."""
import hashlib
import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud_worker.config import (
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_PREFIX,
    S3_SOURCE_FOLDERS,
    S3_SOURCE_PREFIX,
)


def upload_json_artifact(source_name: str, filename: str, payload: Any) -> dict[str, Any]:
    """Serialize a JSON payload and upload it to the configured S3 bucket."""
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not configured.")

    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    bucket_prefix = (S3_PREFIX or "").strip("/")
    source_prefix = (S3_SOURCE_PREFIX or "").strip("/")
    folder = S3_SOURCE_FOLDERS.get(source_name, source_name)
    parts = [part for part in (bucket_prefix, source_prefix, folder) if part]
    object_key = "/".join(parts) + f"/{filename}.json"

    try:
        boto3.client("s3", region_name=AWS_REGION).put_object(
            Bucket=S3_BUCKET_NAME,
            Key=object_key,
            Body=body,
            ContentType="application/json",
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 JSON upload failed for {source_name}/{filename}: {exc}") from exc

    return {
        "s3_object_key": object_key,
        "file_size_bytes": len(body),
        "content_hash": hashlib.sha256(body).hexdigest(),
    }