from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from server.database.models import PipelineEvent, RunApproval


def list_events(db: Session, limit: int = 100, run_id: str | None = None):
    query = db.query(PipelineEvent).order_by(PipelineEvent.received_at.desc())
    if run_id:
        query = query.filter(PipelineEvent.run_id == run_id)
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "run_id": event.run_id,
            "received_at": event.received_at.isoformat() if event.received_at else None,
            "event_time": event.event_time.isoformat() if event.event_time else None,
            "source": event.source,
            "payload": event.payload,
        }
        for event in query.limit(limit).all()
    ]


def list_runs(db: Session, limit: int = 50):
    runs = db.query(RunApproval).order_by(RunApproval.requested_at.desc()).limit(limit).all()
    return [
        {
            "run_id": run.run_id,
            "status": run.status,
            "manifest_key": run.manifest_key,
            "requested_at": run.requested_at.isoformat() if run.requested_at else None,
            "decided_at": run.decided_at.isoformat() if run.decided_at else None,
            "decided_by": run.decided_by,
            "ingester_task_arn": run.ingester_task_arn,
            "notes": run.notes,
        }
        for run in runs
    ]


def fetch_recent_events(db: Session, limit: int = 20):
    return db.query(PipelineEvent).order_by(PipelineEvent.received_at.desc()).limit(limit).all()


def ensure_pending_approval(db: Session, run_id: str | None, payload: dict[str, Any], manifest_key: str | None) -> None:
    if not run_id:
        return

    existing = db.query(RunApproval).filter(RunApproval.run_id == run_id).first()
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


def persist_event(db: Session, event: dict[str, Any]) -> bool:
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
        from server.services.workflow_service import resolve_manifest_key

        ensure_pending_approval(db, event.get("run_id"), event.get("payload", {}), resolve_manifest_key(event.get("run_id"), event.get("payload", {})))
    return True
