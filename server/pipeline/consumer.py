"""Compatibility wrapper for the workflow consumer module."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from server.config import AWS_REGION, S3_BUCKET_NAME, S3_PREFIX, SQS_MAX_RECEIVE_COUNT, SQS_QUEUE_URL
from server.database.database import SessionLocal
from server.database.models import PipelineEvent, RunApproval
from server.services.workflow_consumer import _handle_failed_message, _message_body_preview, _message_receive_count, sqs_consumer_loop
from server.services.workflow_events import parse_event
from server.services.workflow_websocket import broadcast

logger = logging.getLogger(__name__)

_S3_CLIENT: Any | None = None


def _get_s3_client() -> Any:
    global _S3_CLIENT
    if _S3_CLIENT is None:
        _S3_CLIENT = boto3.client("s3", region_name=AWS_REGION)
    return _S3_CLIENT


def _resolve_manifest_key(run_id: str | None, payload: dict[str, Any]) -> str | None:
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
        logger.warning("S3 bucket is not configured for run %s; using derived manifest_key=%s", run_id, candidate)
        return candidate

    try:
        _get_s3_client().head_object(Bucket=S3_BUCKET_NAME, Key=candidate)
        return candidate
    except ClientError as exc:
        logger.warning(
            "Manifest %s was not found in bucket %s for run %s; using derived manifest_key anyway. Reason=%s",
            candidate,
            S3_BUCKET_NAME,
            run_id,
            exc,
        )
        return candidate
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning(
            "Unable to verify manifest %s in bucket %s for run %s; using derived manifest_key anyway. Reason=%s",
            candidate,
            S3_BUCKET_NAME,
            run_id,
            exc,
        )
        return candidate


def _ensure_pending_approval(run_id: str | None, payload: dict[str, Any]) -> None:
    if not run_id:
        return

    db = SessionLocal()
    try:
        existing = db.query(RunApproval).filter(RunApproval.run_id == run_id).first()
        manifest_key = _resolve_manifest_key(run_id, payload)

        if existing is not None:
            if existing.status == "pending" and existing.manifest_key == manifest_key:
                return
            if existing.status in {"approved", "rejected", "ingested"}:
                return

            existing.manifest_key = manifest_key
            existing.status = "pending"
            db.commit()
            return

        db.add(
            RunApproval(
                run_id=run_id,
                status="pending",
                manifest_key=manifest_key,
            )
        )
        db.commit()
    finally:
        db.close()


def _persist_event(event: dict[str, Any]) -> bool:
    db = SessionLocal()
    try:
        existing = db.query(PipelineEvent).filter(PipelineEvent.event_id == event["event_id"]).first()
        if existing is not None:
            return False

        event_time = event.get("event_time")
        if isinstance(event_time, str):
            event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        if event_time is not None and getattr(event_time, "tzinfo", None) is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        record = PipelineEvent(
            event_id=event["event_id"],
            event_type=event["event_type"],
            source=event["source"],
            run_id=event.get("run_id"),
            event_time=event_time,
            payload=event.get("payload", {}),
        )
        db.add(record)
        db.commit()

        if event.get("event_type") == "sfn.state_change" and event.get("status") == "SUCCEEDED":
            _ensure_pending_approval(event.get("run_id"), event.get("payload", {}))
        return True
    finally:
        db.close()


__all__ = [
    "_handle_failed_message",
    "_message_receive_count",
    "_message_body_preview",
    "_persist_event",
    "_resolve_manifest_key",
    "_ensure_pending_approval",
    "sqs_consumer_loop",
    "parse_event",
    "broadcast",
    "SessionLocal",
    "S3_BUCKET_NAME",
    "S3_PREFIX",
    "SQS_QUEUE_URL",
    "SQS_MAX_RECEIVE_COUNT",
    "AWS_REGION",
]

resolve_manifest_key = _resolve_manifest_key
