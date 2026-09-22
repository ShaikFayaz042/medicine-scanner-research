from fastapi import APIRouter
from pydantic import BaseModel

from server.status_store import get_worker_status, set_worker_status

router = APIRouter(prefix="/api", tags=["status"])


class WorkerEventPayload(BaseModel):
    source: str | None = None
    triggered_by: str | None = None
    error: str | None = None


@router.get("/scheduler/worker-status")
def scheduler_worker_status():
    return get_worker_status()


@router.post("/scheduler/worker/start")
def scheduler_worker_start(payload: WorkerEventPayload | None = None):
    data = payload.model_dump() if payload else {}
    return set_worker_status("running", **data)


@router.post("/scheduler/worker/finish")
def scheduler_worker_finish(payload: WorkerEventPayload | None = None):
    data = payload.model_dump() if payload else {}
    return set_worker_status("finished", **data)


@router.post("/scheduler/worker/error")
def scheduler_worker_error(payload: WorkerEventPayload | None = None):
    data = payload.model_dump() if payload else {}
    return set_worker_status("failed", **data)
