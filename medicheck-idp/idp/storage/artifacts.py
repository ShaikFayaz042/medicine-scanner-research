"""Read and write pipeline JSON artifacts on the local disk or S3 (`s3://bucket/key`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Tuple


def is_s3(uri: str) -> bool:
    return uri.startswith("s3://")


def _split(uri: str) -> Tuple[str, str]:
    bucket, _, key = uri[len("s3://"):].partition("/")
    return bucket, key


def _s3():
    import boto3

    return boto3.client("s3")


def join(base: str, name: str) -> str:
    return f"{base.rstrip('/')}/{name}" if is_s3(base) else str(Path(base) / name)


def read_json(uri: str) -> Any:
    if is_s3(uri):
        bucket, key = _split(uri)
        body = _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body.decode("utf-8-sig"))
    return json.loads(Path(uri).read_text(encoding="utf-8-sig"))


def write_json(uri: str, value: Any) -> None:
    body = json.dumps(value, ensure_ascii=False, indent=2)
    if is_s3(uri):
        bucket, key = _split(uri)
        _s3().put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/json; charset=utf-8")
        return
    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def list_json(uri: str) -> List[str]:
    """JSON files under a local directory or S3 prefix; a single file is returned as itself."""
    if is_s3(uri):
        bucket, prefix = _split(uri)
        if prefix.endswith(".json"):
            return [uri]
        keys: List[str] = []
        for page in _s3().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            keys += [f"s3://{bucket}/{item['Key']}" for item in page.get("Contents", []) if item["Key"].endswith(".json")]
        return sorted(keys)
    path = Path(uri)
    if path.is_file():
        return [str(path)]
    return sorted(str(p) for p in path.rglob("*.json"))
