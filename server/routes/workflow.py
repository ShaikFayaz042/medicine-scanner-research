from __future__ import annotations

import json

import boto3
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from server.config import AWS_REGION, S3_BUCKET_NAME, S3_PREFIX
from server.database.database import SessionLocal, get_db
from server.database.models import PipelineEvent, RunApproval
from server.repositories.workflow_repository import fetch_recent_events, list_events, list_runs
from server.services.workflow_approval_service import approve_run, reject_run
from server.services.workflow_websocket import manager
from server.services.workflow_service import get_run_manifest, list_normalized_artifacts

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _run_s3_prefix(run_id: str) -> str:
    """Build the S3 prefix shared by run-scoped pipeline artifacts."""
    return f"{(S3_PREFIX or '').strip('/')}/processed_files/runs/{run_id}"


@router.get("/runs/{run_id}/manifest")
def get_run_manifest_route(run_id: str):
    """Read a run manifest and return its source and document summary."""
    try:
        return get_run_manifest(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="manifest not found yet") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/runs/{run_id}/artifacts/normalized")
def get_normalized_artifacts_route(run_id: str):
    """Count records in the current normalized JSON artifacts for a run."""
    try:
        return list_normalized_artifacts(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/events")
def list_events_route(limit: int = 100, run_id: str | None = None, db: Session = Depends(get_db)):
    return list_events(db, limit=limit, run_id=run_id)


@router.get("/runs")
def list_runs_route(limit: int = 50, db: Session = Depends(get_db)):
    return list_runs(db, limit=limit)


@router.post("/runs/{run_id}/approve")
async def approve(run_id: str, payload: dict | None = None, db: Session = Depends(get_db)):
    body = payload or {}
    try:
        return await approve_run(run_id, decided_by=str(body.get("by") or "admin"), db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/reject")
def reject(run_id: str, payload: dict | None = None, db: Session = Depends(get_db)):
    body = payload or {}
    try:
        return reject_run(run_id, decided_by=str(body.get("by") or "admin"), notes=body.get("notes"), db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        db = SessionLocal()
        try:
            recent = fetch_recent_events(db, limit=20)
            for event in reversed(recent):
                await ws.send_json(
                    {
                        "kind": "history",
                        "id": event.id,
                        "event_type": event.event_type,
                        "run_id": event.run_id,
                        "received_at": event.received_at.isoformat() if event.received_at else None,
                        "payload": event.payload,
                    }
                )
        finally:
            db.close()

        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:
        await manager.disconnect(ws)
