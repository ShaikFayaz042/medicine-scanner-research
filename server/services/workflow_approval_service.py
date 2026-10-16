from __future__ import annotations

from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from server.config import AWS_REGION, ECS_CLUSTER, ECS_SECURITY_GROUP, ECS_SUBNET, S3_BUCKET_NAME
from server.database.models import RunApproval


async def approve_run(run_id: str, decided_by: str, db: Session) -> dict:
    approval = db.query(RunApproval).filter(RunApproval.run_id == run_id).first()
    if approval is None:
        raise ValueError(f"Run {run_id} not found")
    if approval.status not in ("pending", "rejected"):
        raise ValueError(f"Run {run_id} is already {approval.status}")

    if not approval.manifest_key:
        raise ValueError(f"Run {run_id} is missing a manifest_key")

    if approval.status == "rejected":
        approval.notes = None

    ecs = boto3.client("ecs", region_name=AWS_REGION)
    try:
        response = ecs.run_task(
            cluster=ECS_CLUSTER,
            taskDefinition="data-ingester-task",
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": [ECS_SUBNET],
                    "securityGroups": [ECS_SECURITY_GROUP],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "data-ingester",
                        "command": [
                            "--bucket",
                            S3_BUCKET_NAME,
                            "--region",
                            AWS_REGION,
                            "--manifest-s3-key",
                            approval.manifest_key,
                            "--run-id",
                            run_id,
                            "--commit",
                        ],
                    }
                ]
            },
        )
        task_arn = response["tasks"][0]["taskArn"]
    except ClientError as exc:
        raise ValueError(f"Failed to launch ingester: {exc}") from exc

    approval.status = "approved"
    approval.decided_at = datetime.now(timezone.utc)
    approval.decided_by = decided_by
    approval.ingester_task_arn = task_arn
    db.commit()

    return {
        "run_id": run_id,
        "status": "approved",
        "ingester_task_arn": task_arn,
    }


def reject_run(run_id: str, decided_by: str, notes: str | None, db: Session) -> dict:
    approval = db.query(RunApproval).filter(RunApproval.run_id == run_id).first()
    if approval is None:
        raise ValueError(f"Run {run_id} not found")
    if approval.status not in ("pending", "approved"):
        raise ValueError(f"Run {run_id} is already {approval.status}")

    approval.status = "rejected"
    approval.decided_at = datetime.now(timezone.utc)
    approval.decided_by = decided_by
    approval.notes = notes
    db.commit()
    return {"run_id": run_id, "status": "rejected"}
