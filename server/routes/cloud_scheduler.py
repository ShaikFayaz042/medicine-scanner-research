"""AWS EventBridge/ECS scheduler controller for the scraper worker.

This file replaces the obsolete local APScheduler implementation and delegates
schedule state to AWS EventBridge Scheduler while triggering the ECS/Fargate
worker via the supported AWS task runner.
"""
import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.config import (
    AWS_ACCOUNT_ID,
    AWS_REGION,
    ECS_CLUSTER_ARN,
    ECS_CLUSTER_NAME,
    ECS_CONTAINER_NAME,
    ECS_SECURITY_GROUPS,
    ECS_SUBNETS,
    ECS_TASK_DEFINITION,
    ECS_TASK_DEFINITION_ARN,
    EVENTBRIDGE_SCHEDULE_NAME,
    EVENTBRIDGE_SCHEDULER_ROLE_ARN,
)
from server.status_store import get_worker_status, set_worker_status

router = APIRouter(prefix="/api", tags=["scheduler"])

ECS_SUBNETS = [item.strip() for item in (ECS_SUBNETS or "").split(",") if item.strip()]
ECS_SECURITY_GROUPS = [
    item.strip() for item in (ECS_SECURITY_GROUPS or "").split(",") if item.strip()
]
EVENTBRIDGE_ROLE_ARN = EVENTBRIDGE_SCHEDULER_ROLE_ARN


class ScheduleUpdate(BaseModel):
    hour: str | None = None
    minute: str | None = None
    times: list[dict[str, int]] | None = None
    enabled: bool = True
    day_of_month: str | None = None
    month: str | None = None
    day_of_week: str | None = None
    year: str | None = None


def _scheduler_client():
    return boto3.client("scheduler", region_name=AWS_REGION)


def _ecs_client():
    return boto3.client("ecs", region_name=AWS_REGION)


def _validate_aws_config() -> None:
    if not ECS_CLUSTER_ARN or not ECS_TASK_DEFINITION_ARN:
        raise HTTPException(
            status_code=503,
            detail="AWS ECS scheduler config is incomplete. Set ECS_CLUSTER_ARN and ECS_TASK_DEFINITION_ARN (or ECS_CLUSTER_NAME + ECS_TASK_DEFINITION + AWS_ACCOUNT_ID).",
        )
    if not ECS_CONTAINER_NAME:
        raise HTTPException(
            status_code=503,
            detail="ECS_CONTAINER_NAME must match the ECS task definition container name exactly.",
        )
    if not ECS_SUBNETS:
        raise HTTPException(
            status_code=503,
            detail="ECS_SUBNETS is required for Fargate task execution.",
        )


def _build_network_configuration() -> dict[str, Any] | None:
    if not ECS_SUBNETS:
        return None
    return {
        "awsvpcConfiguration": {
            "subnets": ECS_SUBNETS,
            "securityGroups": ECS_SECURITY_GROUPS,
            "assignPublicIp": "ENABLED",
        }
    }


def _build_schedule_target() -> dict[str, Any]:
    if not EVENTBRIDGE_ROLE_ARN:
        raise HTTPException(
            status_code=503,
            detail="EVENTBRIDGE_SCHEDULER_ROLE_ARN is required for EventBridge Scheduler targets.",
        )
    if not ECS_SUBNETS:
        raise HTTPException(
            status_code=503,
            detail="ECS_SUBNETS is required for EventBridge Scheduler Fargate targets.",
        )

    target: dict[str, Any] = {
        "Arn": ECS_CLUSTER_ARN,
        "RoleArn": EVENTBRIDGE_ROLE_ARN,
        "EcsParameters": {
            "TaskDefinitionArn": ECS_TASK_DEFINITION_ARN,
            "LaunchType": "FARGATE",
            "NetworkConfiguration": {
                "AwsVpcConfiguration": {
                    "Subnets": ECS_SUBNETS,
                    "SecurityGroups": ECS_SECURITY_GROUPS,
                    "AssignPublicIp": "ENABLED",
                }
            },
            "PlatformVersion": "LATEST",
            "PropagateTags": "TASK",
        },
        "Input": json.dumps({
            "containerOverrides": [
                {
                    "name": ECS_CONTAINER_NAME,
                    "command": ["python", "-m", "cloud_worker.scraper.main", "--limit", "1"],
                }
            ]
        }),
    }
    return target


def run_scraper_now(limit: int | None = None) -> dict:
    """Trigger an ECS task to run the scraper worker immediately."""
    set_worker_status("running", source="aws-ecs", triggered_by="manual")
    _validate_aws_config()
    client = _ecs_client()
    network = _build_network_configuration()
    payload = {
        "cluster": ECS_CLUSTER_NAME or ECS_CLUSTER_ARN,
        "taskDefinition": ECS_TASK_DEFINITION_ARN or ECS_TASK_DEFINITION,
        "launchType": "FARGATE",
        "count": 1,
        "overrides": {
            "containerOverrides": [
                {
                    "name": ECS_CONTAINER_NAME,
                    "command": [
                        "python",
                        "-m",
                        "cloud_worker.scraper.main",
                        *(["--limit", str(limit)] if limit is not None else []),
                    ],
                }
            ]
        },
    }
    if network is not None:
        payload["networkConfiguration"] = network

    try:
        response = client.run_task(**payload)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=500, detail=f"ECS run_task failed: {exc}") from exc

    return {
        "status": "started",
        "source": "aws-ecs",
        "cluster": ECS_CLUSTER_NAME or ECS_CLUSTER_ARN,
        "task_definition": ECS_TASK_DEFINITION_ARN or ECS_TASK_DEFINITION,
        "tasks": response.get("tasks", []),
    }


def get_scheduler_state() -> dict:
    """Read schedule state from AWS EventBridge Scheduler."""
    if not EVENTBRIDGE_SCHEDULE_NAME:
        return {
            "configured": False,
            "source": "aws-eventbridge",
            "message": "Schedule name is not configured.",
            "hour": 0,
            "minute": 0,
            "enabled": False,
        }

    client = _scheduler_client()
    schedules = []
    try:
        schedule = client.get_schedule(Name=EVENTBRIDGE_SCHEDULE_NAME)
        schedules.append(schedule)
    except client.exceptions.ResourceNotFoundException:
        return {
            "configured": False,
            "source": "aws-eventbridge",
            "schedule_name": EVENTBRIDGE_SCHEDULE_NAME,
            "state": "not_created",
            "hour": 0,
            "minute": 0,
            "enabled": False,
        }
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read AWS schedule: {exc}") from exc

    suffix = 2
    while True:
        try:
            schedules.append(client.get_schedule(Name=f"{EVENTBRIDGE_SCHEDULE_NAME}-{suffix}"))
            suffix += 1
        except client.exceptions.ResourceNotFoundException:
            break
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read AWS schedule: {exc}") from exc

    schedule = schedules[0]
    state = schedule.get("State", "UNKNOWN")
    times = []
    for item in schedules:
        minute, hour = _cron_time_from_expression(item.get("ScheduleExpression"))
        times.append({"hour": hour, "minute": minute})
    minute, hour = times[0]["minute"], times[0]["hour"]
    cron_fields = _cron_fields_from_expression(schedule.get("ScheduleExpression", "cron(0 0 * * ? *)"))
    return {
        "configured": True,
        "source": "aws-eventbridge",
        "schedule_name": EVENTBRIDGE_SCHEDULE_NAME,
        "state": state,
        "schedule_expression": schedule.get("ScheduleExpression"),
        "enabled": state == "ENABLED",
        "times": times,
        "hour": hour,
        "minute": minute,
        "day_of_month": cron_fields.get("day_of_month"),
        "month": cron_fields.get("month"),
        "day_of_week": cron_fields.get("day_of_week"),
        "year": cron_fields.get("year"),
        "worker_status": get_worker_status(),
    }


def _cron_expression_from_fields(
    hour: str | int,
    minute: str | int,
    day_of_month: str | int | None = None,
    month: str | int | None = None,
    day_of_week: str | int | None = None,
    year: str | int | None = None,
) -> str:
    """Build an AWS EventBridge cron expression while preserving the current hour/minute behavior."""
    if day_of_month not in (None, "*") and day_of_week not in (None, "*", "?"):
        raise HTTPException(
            status_code=400,
            detail="Provide either day_of_month or day_of_week, not both.",
        )

    dom = "*" if day_of_month in (None, "?") else str(day_of_month)
    month_field = "*" if month is None else str(month)
    dow = "*" if day_of_week in (None, "*") else str(day_of_week)
    if day_of_month not in (None, "*", "?"):
        dow = "?"
    elif day_of_week == "?":
        dom = "*"
    elif day_of_week not in (None, "*"):
        dom = "?"
    elif day_of_month in (None, "*", "?"):
        dow = "?"
    year_field = "*" if year is None else str(year)

    return f"cron({minute} {hour} {dom} {month_field} {dow} {year_field})"


def _cron_fields_from_expression(schedule_expression: str) -> dict[str, Any]:
    """Parse the minute/hour/day/month/day-of-week fields from an AWS cron string."""
    try:
        if not schedule_expression.startswith("cron(") or not schedule_expression.endswith(")"):
            return {"minute": 0, "hour": 0, "day_of_month": None, "month": None, "day_of_week": None}
        cron_fields = schedule_expression[5:-1].split()
        if len(cron_fields) < 5:
            return {"minute": 0, "hour": 0, "day_of_month": None, "month": None, "day_of_week": None, "year": "*"}
        minute, hour, day_of_month, month, day_of_week = cron_fields[:5]
        year = cron_fields[5] if len(cron_fields) > 5 else "*"

        def parse_field(value: str):
            try:
                return int(value)
            except ValueError:
                return value

        return {
            "minute": parse_field(minute),
            "hour": parse_field(hour),
            "day_of_month": day_of_month,
            "month": month,
            "day_of_week": day_of_week,
            "year": year,
        }
    except (TypeError, ValueError):
        return {"minute": 0, "hour": 0, "day_of_month": "*", "month": "*", "day_of_week": "?", "year": "*"}


def _build_update_payload_from_existing(
    existing_schedule: dict[str, Any],
    hour: int,
    minute: int,
    enabled: bool,
    day_of_month: int | None = None,
    month: int | None = None,
    day_of_week: str | int | None = None,
    year: str | int | None = None,
    cron_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve the live AWS schedule target and metadata while updating the requested schedule."""
    payload: dict[str, Any] = {
        "Name": existing_schedule.get("Name", EVENTBRIDGE_SCHEDULE_NAME),
        "ScheduleExpression": _cron_expression_from_fields(
            (cron_fields or {}).get("hour", hour),
            (cron_fields or {}).get("minute", minute),
            (cron_fields or {}).get("day_of_month", day_of_month),
            (cron_fields or {}).get("month", month),
            (cron_fields or {}).get("day_of_week", day_of_week),
            (cron_fields or {}).get("year", year),
        ),
        "State": "ENABLED" if enabled else "DISABLED",
        "FlexibleTimeWindow": existing_schedule.get("FlexibleTimeWindow", {"Mode": "OFF"}),
        "Target": existing_schedule.get("Target"),
    }

    if "ScheduleExpressionTimezone" in existing_schedule:
        payload["ScheduleExpressionTimezone"] = existing_schedule["ScheduleExpressionTimezone"]
    for field in ("GroupName", "Description", "StartDate", "EndDate", "ActionAfterCompletion", "KmsKeyArn"):
        if existing_schedule.get(field) is not None:
            payload[field] = existing_schedule[field]

    return payload


def _cron_time_from_expression(schedule_expression: str) -> tuple[int, int]:
    """Parse a cron string into minute/hour integers while keeping other cron fields available."""
    parsed = _cron_fields_from_expression(schedule_expression)
    return parsed["minute"], parsed["hour"]


def update_schedule(
    hour: str | int | None,
    minute: str | int | None,
    enabled: bool,
    day_of_month: str | int | None = None,
    month: str | int | None = None,
    day_of_week: str | int | None = None,
    times: list[dict[str, int]] | None = None,
    year: str | int | None = None,
    cron_fields: dict[str, Any] | None = None,
) -> dict:
    """Create or update the AWS EventBridge schedule while preserving the current hour/minute behavior."""
    client = _scheduler_client()
    use_cron_fields = cron_fields is not None
    if use_cron_fields:
        times = [{"hour": 0, "minute": 0}]
    elif times is None:
        if hour is None or minute is None:
            raise HTTPException(status_code=422, detail="Provide times or both hour and minute.")
        times = [{"hour": hour, "minute": minute}]
    if not times:
        raise HTTPException(status_code=422, detail="Provide at least one schedule time.")

    for time in times:
        if use_cron_fields:
            continue
        if not 0 <= time.get("hour", -1) <= 23 or not 0 <= time.get("minute", -1) <= 59:
            raise HTTPException(status_code=422, detail="Schedule times must contain valid hour and minute values.")

    def schedule_name(index: int) -> str:
        return EVENTBRIDGE_SCHEDULE_NAME if index == 0 else f"{EVENTBRIDGE_SCHEDULE_NAME}-{index + 1}"

    for index, time in enumerate(times):
        current_name = schedule_name(index)
        try:
            existing_schedule = client.get_schedule(Name=current_name)
        except client.exceptions.ResourceNotFoundException:
            existing_schedule = None
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read existing AWS schedule: {exc}") from exc

        if existing_schedule is not None:
            payload = _build_update_payload_from_existing(
                existing_schedule,
                time["hour"],
                time["minute"],
                enabled,
                day_of_month=day_of_month,
                month=month,
                day_of_week=day_of_week,
                year=year,
                cron_fields=cron_fields,
            )
            try:
                client.update_schedule(**payload)
            except (BotoCoreError, ClientError) as exc:
                raise HTTPException(status_code=500, detail=f"Failed to update AWS schedule: {exc}") from exc
            continue

        _validate_aws_config()
        if not EVENTBRIDGE_ROLE_ARN:
            raise HTTPException(
                status_code=503,
                detail="EVENTBRIDGE_SCHEDULER_ROLE_ARN is required to update the EventBridge schedule.",
            )

        cron_expression = _cron_expression_from_fields(
            (cron_fields or {}).get("hour", time["hour"]),
            (cron_fields or {}).get("minute", time["minute"]),
            (cron_fields or {}).get("day_of_month", day_of_month),
            (cron_fields or {}).get("month", month),
            (cron_fields or {}).get("day_of_week", day_of_week),
            (cron_fields or {}).get("year", year),
        )
        payload = {
            "Name": current_name,
            "ScheduleExpression": cron_expression,
            "State": "ENABLED" if enabled else "DISABLED",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": _build_schedule_target(),
        }

        try:
            client.create_schedule(**payload)
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to create AWS schedule: {exc}") from exc

    if not use_cron_fields:
        stale_index = len(times) + 1
        while True:
            stale_name = f"{EVENTBRIDGE_SCHEDULE_NAME}-{stale_index}"
            try:
                client.delete_schedule(Name=stale_name)
                stale_index += 1
            except client.exceptions.ResourceNotFoundException:
                break
            except (BotoCoreError, ClientError) as exc:
                raise HTTPException(status_code=500, detail=f"Failed to remove stale AWS schedule: {exc}") from exc

    return get_scheduler_state()


def _schedule_exists(name: str) -> bool:
    client = _scheduler_client()
    try:
        client.get_schedule(Name=name)
        return True
    except client.exceptions.ResourceNotFoundException:
        return False


@router.get("/scheduler")
def get_scheduler_route():
    return get_scheduler_state()


@router.put("/scheduler")
def set_scheduler_route(payload: ScheduleUpdate):
    return update_schedule(
        payload.hour,
        payload.minute,
        payload.enabled,
        day_of_month=payload.day_of_month,
        month=payload.month,
        day_of_week=payload.day_of_week,
        times=payload.times,
        year=payload.year,
        cron_fields={
            "minute": payload.minute,
            "hour": payload.hour,
            "day_of_month": payload.day_of_month,
            "month": payload.month,
            "day_of_week": payload.day_of_week,
            "year": payload.year,
        } if payload.times is None and payload.minute is not None and payload.hour is not None else None,
    )


@router.post("/scheduler/run-now")
def trigger_run_now():
    return run_scraper_now()


@router.get("/scheduler/status")
def get_scheduler_status():
    return get_scheduler_state()


@router.post("/scheduler/pause")
def pause_scheduler():
    client = _scheduler_client()
    try:
        existing_schedule = client.get_schedule(Name=EVENTBRIDGE_SCHEDULE_NAME)
    except client.exceptions.ResourceNotFoundException:
        raise HTTPException(
            status_code=404,
            detail=f"EventBridge schedule '{EVENTBRIDGE_SCHEDULE_NAME}' does not exist.",
        ) from None
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read AWS schedule: {exc}") from exc

    cron_fields = _cron_fields_from_expression(existing_schedule.get("ScheduleExpression", "cron(0 0 * * ? *)"))
    minute = cron_fields["minute"]
    hour = cron_fields["hour"]
    payload = _build_update_payload_from_existing(
        existing_schedule,
        hour=hour,
        minute=minute,
        enabled=False,
        day_of_month=cron_fields.get("day_of_month"),
        month=cron_fields.get("month"),
        day_of_week=cron_fields.get("day_of_week"),
    )
    payload["State"] = "DISABLED"

    try:
        client.update_schedule(**payload)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to pause AWS schedule: {exc}") from exc
    return get_scheduler_state()


@router.post("/scheduler/resume")
def resume_scheduler():
    client = _scheduler_client()
    try:
        existing_schedule = client.get_schedule(Name=EVENTBRIDGE_SCHEDULE_NAME)
    except client.exceptions.ResourceNotFoundException:
        raise HTTPException(
            status_code=404,
            detail=f"EventBridge schedule '{EVENTBRIDGE_SCHEDULE_NAME}' does not exist.",
        ) from None
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read AWS schedule: {exc}") from exc

    cron_fields = _cron_fields_from_expression(existing_schedule.get("ScheduleExpression", "cron(0 0 * * ? *)"))
    minute = cron_fields["minute"]
    hour = cron_fields["hour"]
    payload = _build_update_payload_from_existing(
        existing_schedule,
        hour=hour,
        minute=minute,
        enabled=True,
        day_of_month=cron_fields.get("day_of_month"),
        month=cron_fields.get("month"),
        day_of_week=cron_fields.get("day_of_week"),
    )
    payload["State"] = "ENABLED"

    try:
        client.update_schedule(**payload)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resume AWS schedule: {exc}") from exc
    return get_scheduler_state()
