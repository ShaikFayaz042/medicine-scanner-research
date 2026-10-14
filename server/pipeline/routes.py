from __future__ import annotations

import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from server.config import AWS_REGION, S3_BUCKET_NAME, S3_PREFIX
from server.database.database import SessionLocal, get_db
from server.database.models import PipelineEvent, RunApproval
from server.pipeline.approval_service import approve_run, reject_run
from server.pipeline.websocket_manager import manager

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _run_s3_prefix(run_id: str) -> str:
    """Build the S3 prefix shared by run-scoped pipeline artifacts."""
    return f"{(S3_PREFIX or '').strip('/')}/processed_files/runs/{run_id}"


@router.get("/runs/{run_id}/manifest")
def get_run_manifest(run_id: str):
    """Read a run manifest and return its source and document summary."""
    key = f"{_run_s3_prefix(run_id)}/manifest.json"
    try:
        response = boto3.client("s3", region_name=AWS_REGION).get_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
        )
        manifest = json.loads(response["Body"].read())
    except ClientError as exc:
        error = exc.response.get("Error", {})
        if error.get("Code") in {"NoSuchKey", "404"}:
            raise HTTPException(status_code=404, detail="manifest not found yet") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (BotoCoreError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    documents = manifest.get("documents", [])
    return {
        "run_id": run_id,
        "documents_count": len(documents),
        "sources": sorted({document["source"] for document in documents if document.get("source")}),
        "has_pdfs": bool(manifest.get("has_pdfs")),
        "has_json": bool(manifest.get("has_json")),
        "triggered_at": manifest.get("triggered_at"),
        "documents": documents,
    }


@router.get("/runs/{run_id}/artifacts/normalized")
def get_normalized_artifacts(run_id: str):
    """Count records in the current normalized JSON artifacts for a run."""
    prefix = f"{_run_s3_prefix(run_id)}/normalized_json/"
    files = []
    record_count = 0
    try:
        client = boto3.client("s3", region_name=AWS_REGION)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if not key.lower().endswith(".json"):
                    continue
                response = client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
                payload = json.loads(response["Body"].read())
                records = payload if isinstance(payload, list) else payload.get("records", [])
                count = len(records)
                record_count += count
                files.append({"key": key, "records": count})
    except (BotoCoreError, ClientError, ValueError, KeyError, AttributeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "run_id": run_id,
        "record_count": record_count,
        "file_count": len(files),
        "files": files,
    }


@router.get("/events")
def list_events(limit: int = 100, run_id: str | None = None, db: Session = Depends(get_db)):
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


@router.get("/runs")
def list_runs(limit: int = 50, db: Session = Depends(get_db)):
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
            recent = db.query(PipelineEvent).order_by(PipelineEvent.received_at.desc()).limit(20).all()
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
