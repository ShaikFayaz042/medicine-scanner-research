from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ParsedEvent(BaseModel):
    event_id: str
    event_type: str
    source: str
    run_id: str | None = None
    event_time: datetime | None = None
    status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def _as_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _extract_run_id(detail: Mapping[str, Any], source: str) -> str | None:
    if source == "aws.states":
        raw_input = detail.get("input")
        if raw_input:
            try:
                parsed = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
                if isinstance(parsed, dict):
                    candidate = parsed.get("run_id")
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
            except (json.JSONDecodeError, TypeError):
                pass

        execution_arn = detail.get("executionArn") or detail.get("execution_arn")
        if isinstance(execution_arn, str) and execution_arn:
            return execution_arn.rsplit(":", 1)[-1] or None
        return None

    if source == "aws.ecs":
        containers = detail.get("containers") or []
        for container in containers:
            command = container.get("command") or []
            if isinstance(command, list):
                for index, part in enumerate(command[:-1]):
                    if part == "--run-id":
                        return str(command[index + 1])

        overrides = detail.get("overrides") or {}
        for container_override in overrides.get("containerOverrides", []):
            command = container_override.get("command") or []
            if isinstance(command, list):
                for index, part in enumerate(command[:-1]):
                    if part == "--run-id":
                        return str(command[index + 1])

    return None


def parse_pipeline_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    if not isinstance(body, dict):
        raise ValueError("Event payload must be a mapping")

    source = str(body.get("source") or "unknown")
    detail = body.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    if source == "aws.states":
        event_type = "sfn.state_change"
    elif source == "aws.ecs":
        event_type = "ecs.task_state_change"
    elif source == "aws.cloudwatch":
        event_type = "alarm.state_change"
    else:
        event_type = "unknown"

    status = detail.get("status") or body.get("status")
    run_id = _extract_run_id(detail, source) or body.get("run_id")
    event_time_raw = body.get("time") or detail.get("timestamp") or detail.get("eventTime")
    event_time = _as_datetime(event_time_raw)
    if event_time_raw is not None:
        logger.debug("Parsed event_time=%r -> %r for source=%s", event_time_raw, event_time, source)
    event_id = str(body.get("MessageId") or body.get("event_id") or body.get("id") or "unknown")

    event = ParsedEvent(
        event_id=event_id,
        event_type=event_type,
        source=source,
        run_id=str(run_id) if run_id else None,
        event_time=event_time,
        status=str(status) if status is not None else None,
        payload=dict(body),
    )
    try:
        return event.model_dump(mode="json")
    except Exception:
        logger.exception("Failed to JSON-serialize ParsedEvent for source=%s event_id=%s payload=%r", source, event_id, body)
        return event.model_dump()


def _coerce_sqs_body(raw_body: Any) -> dict[str, Any]:
    if isinstance(raw_body, dict):
        return raw_body
    if isinstance(raw_body, (bytes, bytearray)):
        raw_body = raw_body.decode("utf-8")
    if not isinstance(raw_body, str):
        raise ValueError("SQS message body must be a JSON string or dict")

    text = raw_body.strip()
    if not text:
        raise ValueError("SQS message body is empty")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    repaired = _repair_missing_quotes(text)
    if repaired is not None:
        try:
            body = json.loads(repaired)
            if isinstance(body, dict):
                return body
        except json.JSONDecodeError:
            pass

    try:
        body = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        try:
            body = ast.literal_eval(repaired) if repaired is not None else None
        except (ValueError, SyntaxError):
            body = None

    if not isinstance(body, dict):
        raise ValueError("SQS message body is not valid JSON or Python dict syntax")
    return body

    if not isinstance(body, dict):
        raise ValueError("SQS message body must decode to a dictionary")
    return body


def _repair_missing_quotes(text: str) -> str | None:
    if not text.startswith("{") or not text.endswith("}"):
        return None

    inner = text[1:-1].strip()
    if not inner:
        return "{}"

    def find_closing_brace(source: str, start: int) -> int:
        depth = 0
        for idx in range(start, len(source)):
            if source[idx] == "{":
                depth += 1
            elif source[idx] == "}":
                depth -= 1
                if depth == 0:
                    return idx
        raise ValueError("Unbalanced braces in malformed SQS payload")

    def parse_value(source: str, start: int) -> tuple[str, int]:
        idx = start
        while idx < len(source) and source[idx].isspace():
            idx += 1
        if idx >= len(source):
            return '""', idx
        if source[idx] == "{":
            end = find_closing_brace(source, idx)
            repaired = _repair_missing_quotes(source[idx : end + 1])
            return (repaired if repaired is not None else source[idx : end + 1]), end + 1
        value_start = idx
        while idx < len(source) and source[idx] not in {",", "}"}:
            if source[idx] == "{":
                raise ValueError("Nested object should have been caught earlier")
            idx += 1
        value = source[value_start:idx].strip()
        if not value:
            return '""', idx
        if value.lower() in {"true", "false", "null"}:
            return value, idx
        if value.startswith(('"', "'")) and value.endswith(('"', "'")):
            return value, idx
        if value.replace(".", "", 1).lstrip("-").isdigit():
            return value, idx
        return json.dumps(value), idx

    parts: list[str] = []
    i = 0
    while i < len(inner):
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i >= len(inner):
            break
        key_start = i
        while i < len(inner) and inner[i] not in {":", ","}:
            i += 1
        key = inner[key_start:i].strip()
        if not key:
            raise ValueError("Malformed SQS payload: missing dict key")
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i >= len(inner) or inner[i] != ":":
            raise ValueError("Malformed SQS payload: expected ':' after key")
        i += 1
        while i < len(inner) and inner[i].isspace():
            i += 1
        value, i = parse_value(inner, i)
        parts.append(f'"{key}":{value}')
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i < len(inner) and inner[i] == ",":
            i += 1

    repaired = "{" + ",".join(parts) + "}"
    return repaired if repaired != text else None


def parse_event(sqs_message: Mapping[str, Any]) -> dict[str, Any]:
    raw_body = sqs_message.get("Body")
    try:
        body = _coerce_sqs_body(raw_body)
        body["MessageId"] = sqs_message.get("MessageId") or body.get("MessageId") or body.get("event_id")
        return parse_pipeline_event(body)
    except Exception:
        preview = raw_body if isinstance(raw_body, str) else repr(raw_body)
        logger.exception("Parse failed for body=%r", preview[:500])
        raise
