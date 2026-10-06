"""Small S3 object helpers shared by ingestion stages."""

from __future__ import annotations

import json
from typing import Any


def read_s3_bytes(client: Any, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def read_s3_json(client: Any, bucket: str, key: str) -> Any:
    return json.loads(read_s3_bytes(client, bucket, key).decode("utf-8-sig"))


def write_s3_bytes(
    client: Any,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def write_s3_json(client: Any, bucket: str, key: str, value: Any) -> None:
    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
    write_s3_bytes(client, bucket, key, body, "application/json; charset=utf-8")
