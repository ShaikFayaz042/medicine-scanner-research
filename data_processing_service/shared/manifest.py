"""Read immutable input manifests and write isolated per-stage results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

BASE_PREFIX = "medicine-data-storage/processed_files"
RESULT_FILENAMES = {
    "extractor": "extracted",
    "classifier": "classified",
    "parser": "parsed",
    "normalizer": "normalized",
    "ingester": "ingested",
    "processor": "processor",
    "profiler": "profiled",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def manifest_key(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"{BASE_PREFIX}/runs/{run_id}/manifest.json"


def _validate_run_id(run_id: str) -> None:
    if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a non-empty path segment")


def result_key(run_id: str, stage: str) -> str:
    _validate_run_id(run_id)
    if stage not in RESULT_FILENAMES:
        raise ValueError(f"Unsupported result stage: {stage}")
    return f"{BASE_PREFIX}/runs/{run_id}/results/{RESULT_FILENAMES[stage]}.json"


def read_manifest(client: Any, bucket: str, key: str) -> dict[str, Any]:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    payload = json.loads(body.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Run manifest must be a JSON object")
    return payload


def write_result(
    client: Any,
    bucket: str,
    run_id: str,
    stage: str,
    result: dict[str, Any],
) -> str:
    key = result_key(run_id, stage)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return key
