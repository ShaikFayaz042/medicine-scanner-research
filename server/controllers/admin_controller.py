"""Controller layer for admin dashboard and system monitoring."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from server.config import EVENTBRIDGE_SCHEDULE_NAME, S3_BUCKET_NAME
from server.database.database import SessionLocal
from server.database.models import Document
from server.status_store import get_worker_status


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _db_healthcheck() -> str:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "error"
    finally:
        db.close()


def get_dashboard_summary() -> dict[str, Any]:
    """Return aggregate stats for the admin dashboard."""
    db = SessionLocal()
    try:
        total_documents = db.query(Document).count()
        new_documents = db.query(Document).filter(Document.status == "discovered").count()
        downloaded = db.query(Document).filter(Document.status == "downloaded").count()
        failed = db.query(Document).filter(Document.status == "failed").count()

        last_record = db.query(Document).order_by(Document.updated_at.desc()).first()
        last_success = (
            db.query(Document)
            .filter(Document.status == "downloaded")
            .order_by(Document.updated_at.desc())
            .first()
        )
    finally:
        db.close()

    return {
        "total_documents": total_documents,
        "new_documents": new_documents,
        "downloaded": downloaded,
        "failed": failed,
        "last_scraper_run": _isoformat(last_record.updated_at) if last_record else None,
        "last_successful_run": _isoformat(last_success.updated_at) if last_success else None,
    }


def get_scraper_status() -> dict[str, Any]:
    """Return current scraper and latest summary information."""
    live_status = get_worker_status()
    db = SessionLocal()
    try:
        latest_document = db.query(Document).order_by(Document.updated_at.desc()).first()
        total_documents = db.query(Document).count()
        new_documents = db.query(Document).filter(Document.status == "discovered").count()
        downloaded = db.query(Document).filter(Document.status == "downloaded").count()
        failed = db.query(Document).filter(Document.status == "failed").count()
        skipped_existing = total_documents - (new_documents + downloaded + failed)
    finally:
        db.close()

    status_value = live_status.get("status", "idle")
    if status_value == "running":
        status_label = "running"
    elif status_value == "failed":
        status_label = "failed"
    else:
        status_label = "idle"

    return {
        "status": status_label,
        "last_run_time": live_status.get("last_started_at") or (_isoformat(latest_document.updated_at) if latest_document else None),
        "running": live_status.get("running", False),
        "source": live_status.get("source"),
        "triggered_by": live_status.get("triggered_by"),
        "last_finished_at": live_status.get("last_finished_at"),
        "last_error": live_status.get("last_error"),
        "latest_result": {
            "scraped": total_documents,
            "new": new_documents,
            "downloaded": downloaded,
            "failed": failed,
            "skipped_existing": max(skipped_existing, 0),
            "skipped_older": 0,
            "skipped_bad_date": 0,
        },
    }


def get_system_status() -> dict[str, Any]:
    """Return lightweight health info for system monitoring."""
    db_status = _db_healthcheck()

    return {
        "api_health": "healthy",
        "database": db_status,
        "s3": "connected" if S3_BUCKET_NAME else "not_configured",
        "scheduler": "enabled" if EVENTBRIDGE_SCHEDULE_NAME else "not_configured",
    }
