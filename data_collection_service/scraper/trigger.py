"""Step Functions trigger for the PDF and JSON ingestion pipeline."""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from data_collection_service.config import (
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_PREFIX,
    SFN_STATE_MACHINE_ARN,
    SFN_TRIGGER_MAX_ATTEMPTS,
    SFN_TRIGGER_RETRY_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1


def build_run_id() -> str:
    """Generate an execution name without characters rejected by Step Functions."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _runs_prefix() -> str:
    base = (S3_PREFIX or "medicine-data-storage").strip("/")
    return f"{base}/processed_files/runs"


def manifest_s3_key(run_id: str) -> str:
    return f"{_runs_prefix()}/{run_id}/manifest.json"


def build_manifest(run_id: str, new_documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the immutable manifest consumed by the Step Functions pipeline."""
    pdf_docs = [document for document in new_documents if document.get("kind") == "pdf"]
    json_docs = [document for document in new_documents if document.get("kind") == "json"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "has_pdfs": bool(pdf_docs),
        "has_json": bool(json_docs),
        "documents": new_documents,
    }


def write_manifest(manifest: dict[str, Any]) -> str:
    """Upload the manifest to S3 and return its object key."""
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not configured; cannot write manifest")

    key = manifest_s3_key(manifest["run_id"])
    body = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    boto3.client("s3", region_name=AWS_REGION).put_object(
        Bucket=S3_BUCKET_NAME,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    return key


def _derive_execution_arn(run_id: str) -> str:
    """Derive the execution ARN returned for an already-started run."""
    parts = SFN_STATE_MACHINE_ARN.split(":")
    region = parts[3]
    account = parts[4]
    state_machine_name = SFN_STATE_MACHINE_ARN.split(":stateMachine:", 1)[1].split(":", 1)[0]
    return f"arn:aws:states:{region}:{account}:execution:{state_machine_name}:{run_id}"


def trigger_step_function(
    *, run_id: str, manifest_key: str, manifest: dict[str, Any]
) -> str:
    """Start a Step Functions execution, retrying transient AWS errors."""
    if not SFN_STATE_MACHINE_ARN:
        raise RuntimeError("SFN_STATE_MACHINE_ARN is not configured")

    output_base = f"{(S3_PREFIX or 'medicine-data-storage').strip('/')}/processed_files"
    execution_input = {
        "run_id": run_id,
        "bucket": S3_BUCKET_NAME,
        "region": AWS_REGION,
        "manifest_key": manifest_key,
        "output_base": output_base,
        "has_pdfs": manifest["has_pdfs"],
        "has_json": manifest["has_json"],
    }

    sfn = boto3.client("stepfunctions", region_name=AWS_REGION)
    last_error: Exception | None = None
    for attempt in range(1, SFN_TRIGGER_MAX_ATTEMPTS + 1):
        try:
            response = sfn.start_execution(
                stateMachineArn=SFN_STATE_MACHINE_ARN,
                name=run_id,
                input=json.dumps(execution_input),
            )
            return response["executionArn"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "ExecutionAlreadyExists":
                logger.warning("Step Functions execution already exists for run_id=%s", run_id)
                return _derive_execution_arn(run_id)
            last_error = exc
        except BotoCoreError as exc:
            last_error = exc

        if attempt < SFN_TRIGGER_MAX_ATTEMPTS:
            time.sleep(SFN_TRIGGER_RETRY_INTERVAL_SECONDS * attempt)

    raise RuntimeError(
        f"Step Functions trigger failed after {SFN_TRIGGER_MAX_ATTEMPTS} attempts: {last_error}"
    )


def trigger_ingestion_pipeline(new_documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a manifest and start Step Functions without raising to the scraper."""
    if not new_documents:
        logger.info("No new documents in this run; skipping pipeline trigger")
        return {"triggered": False, "reason": "no_new_documents"}

    run_id = build_run_id()
    result: dict[str, Any] = {"run_id": run_id, "triggered": False}
    try:
        manifest = build_manifest(run_id, new_documents)
        manifest_key = write_manifest(manifest)
        result["manifest_key"] = manifest_key
    except Exception as exc:
        logger.exception("Failed to write pipeline manifest: %s", exc)
        result["error"] = f"manifest_write_failed: {type(exc).__name__}"
        return result

    try:
        execution_arn = trigger_step_function(
            run_id=run_id, manifest_key=manifest_key, manifest=manifest
        )
        result["triggered"] = True
        result["execution_arn"] = execution_arn
        logger.info(
            "Pipeline triggered: run_id=%s pdfs=%d jsons=%d execution=%s",
            run_id,
            sum(1 for document in new_documents if document.get("kind") == "pdf"),
            sum(1 for document in new_documents if document.get("kind") == "json"),
            execution_arn,
        )
    except Exception as exc:
        logger.exception("Failed to trigger Step Functions: %s", exc)
        result["error"] = f"sfn_trigger_failed: {type(exc).__name__}"

    return result