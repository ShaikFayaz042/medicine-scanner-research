from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from server.config import (
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_PREFIX,
    SQS_DLQ_URL,
    SQS_MAX_MESSAGES,
    SQS_MAX_RECEIVE_COUNT,
    SQS_QUEUE_URL,
    SQS_VISIBILITY_TIMEOUT,
    SQS_WAIT_SECONDS,
)
from server.database.database import SessionLocal
from server.database.models import PipelineEvent, RunApproval
from server.pipeline.events import parse_event
from server.pipeline.websocket_manager import broadcast

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


def _message_receive_count(message: dict[str, Any]) -> int:
    attributes = message.get("Attributes") or {}
    value = attributes.get("ApproximateReceiveCount")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _message_body_preview(message: dict[str, Any]) -> str:
    body = message.get("Body") or ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    return str(body)[:200]


def _handle_failed_message(sqs_client: Any, message: dict[str, Any], exc: Exception) -> None:
    receive_count = _message_receive_count(message)
    raw_body = message.get("Body") or ""
    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8", errors="replace")
    body_preview = str(raw_body)[:200]

    if receive_count >= SQS_MAX_RECEIVE_COUNT:
        logger.error(
            "Parse failed (attempt %d): %s | body=%r",
            receive_count,
            exc,
            body_preview,
        )
        try:
            if message.get("ReceiptHandle"):
                sqs_client.delete_message(
                    QueueUrl=SQS_QUEUE_URL,
                    ReceiptHandle=message["ReceiptHandle"],
                )
            logger.warning("Dropped poison SQS message %s after %d attempts", message.get("MessageId"), receive_count)
        except Exception:
            logger.exception("Failed to delete poison message %s after %d attempts", message.get("MessageId"), receive_count)
        return

    logger.warning(
        "Parse failed (attempt %d): %s | body=%r",
        receive_count,
        exc,
        body_preview,
    )


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
    db: Session = SessionLocal()
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


async def sqs_consumer_loop() -> None:
    """Long-poll the SQS queue, persist valid events, and broadcast them to WebSocket clients."""
    sqs = boto3.client("sqs", region_name=AWS_REGION)

    while True:
        try:
            response = await asyncio.to_thread(
                sqs.receive_message,
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=SQS_MAX_MESSAGES,
                WaitTimeSeconds=SQS_WAIT_SECONDS,
                VisibilityTimeout=SQS_VISIBILITY_TIMEOUT,
                AttributeNames=["ApproximateReceiveCount"],
                MessageAttributeNames=["All"],
            )
        except ClientError as exc:
            logger.exception("SQS receive failed: %s", exc)
            await asyncio.sleep(5)
            continue

        messages = response.get("Messages", [])
        for message in messages:
            try:
                event = parse_event(message)
                persisted = await asyncio.to_thread(_persist_event, event)
                if persisted:
                    await broadcast(event)
                    await asyncio.to_thread(
                        sqs.delete_message,
                        QueueUrl=SQS_QUEUE_URL,
                        ReceiptHandle=message["ReceiptHandle"],
                    )
            except Exception as exc:
                _handle_failed_message(sqs, message, exc)
                continue

        await asyncio.sleep(0.1)
