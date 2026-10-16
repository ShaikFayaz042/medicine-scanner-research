from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from server.config import AWS_REGION, S3_BUCKET_NAME, S3_PREFIX


def build_run_s3_prefix(run_id: str) -> str:
    """Build the S3 prefix shared by run-scoped pipeline artifacts."""
    return f"{(S3_PREFIX or '').strip('/')}/processed_files/runs/{run_id}"


def resolve_manifest_key(run_id: str | None, payload: dict[str, Any]) -> str | None:
    """Resolve the manifest key for a run from the event payload or its derived path."""
    if not run_id:
        return None

    detail = payload.get("detail") or {}
    manifest_key = None
    if isinstance(detail.get("output"), str):
        try:
            output = json.loads(detail["output"])
            manifest_key = output.get("manifest_key") or output.get("manifestS3Key")
        except json.JSONDecodeError:
            manifest_key = None
    elif isinstance(detail.get("output"), dict):
        manifest_key = detail["output"].get("manifest_key") or detail["output"].get("manifestS3Key")

    if manifest_key:
        return str(manifest_key)

    candidate = f"{S3_PREFIX}/processed_files/runs/{run_id}/manifest.json"
    if not S3_BUCKET_NAME:
        return candidate

    try:
        boto3.client("s3", region_name=AWS_REGION).head_object(Bucket=S3_BUCKET_NAME, Key=candidate)
        return candidate
    except ClientError:
        return candidate
    except Exception:
        return candidate


def get_run_manifest(run_id: str) -> dict[str, Any]:
    """Read a run manifest and return its source and document summary."""
    key = f"{build_run_s3_prefix(run_id)}/manifest.json"
    try:
        response = boto3.client("s3", region_name=AWS_REGION).get_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
        )
        manifest = json.loads(response["Body"].read())
    except ClientError as exc:
        error = exc.response.get("Error", {})
        if error.get("Code") in {"NoSuchKey", "404"}:
            raise FileNotFoundError("manifest not found yet") from exc
        raise RuntimeError(str(exc)) from exc
    except (BotoCoreError, ValueError, KeyError) as exc:
        raise RuntimeError(str(exc)) from exc

    documents = manifest.get("documents", [])
    return {
        "run_id": run_id,
        "documents_count": len(documents),
        "sources": sorted({document["source"] for document in documents if document.get("source")}),
        "has_pdfs": bool(manifest.get("has_pdfs")),
        "has_json": bool(manifest.get("has_json")),
        "triggered_at": manifest.get("triggered_at"),
        "documents": documents,
    }


def list_normalized_artifacts(run_id: str) -> dict[str, Any]:
    """Count records in the current normalized JSON artifacts for a run."""
    prefix = f"{build_run_s3_prefix(run_id)}/normalized_json/"
    files = []
    record_count = 0
    try:
        client = boto3.client("s3", region_name=AWS_REGION)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if not key.lower().endswith(".json"):
                    continue
                response = client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
                payload = json.loads(response["Body"].read())
                records = payload if isinstance(payload, list) else payload.get("records", [])
                count = len(records)
                record_count += count
                files.append({"key": key, "records": count})
    except (BotoCoreError, ClientError, ValueError, KeyError, AttributeError) as exc:
        raise RuntimeError(str(exc)) from exc

    return {
        "run_id": run_id,
        "record_count": record_count,
        "file_count": len(files),
        "files": files,
    }
