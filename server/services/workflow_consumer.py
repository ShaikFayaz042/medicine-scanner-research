from __future__ import annotations

import asyncio
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from server.config import (
    AWS_REGION,
    S3_PREFIX,
    SQS_DLQ_URL,
    SQS_MAX_MESSAGES,
    SQS_MAX_RECEIVE_COUNT,
    SQS_QUEUE_URL,
    SQS_VISIBILITY_TIMEOUT,
    SQS_WAIT_SECONDS,
)
from server.database.database import SessionLocal
from server.repositories.workflow_repository import ensure_pending_approval, persist_event
from server.services.workflow_events import parse_event
from server.services.workflow_websocket import broadcast
from server.services.workflow_service import resolve_manifest_key

logger = logging.getLogger(__name__)


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


def _persist_event(event: dict[str, Any]) -> bool:
    db = SessionLocal()
    try:
        persisted = persist_event(db, event)
        if persisted and event.get("event_type") == "sfn.state_change" and event.get("status") == "SUCCEEDED":
            ensure_pending_approval(
                db,
                event.get("run_id"),
                event.get("payload", {}),
                resolve_manifest_key(event.get("run_id"), event.get("payload", {})),
            )
        return persisted
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
