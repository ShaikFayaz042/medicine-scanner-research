from __future__ import annotations

import threading
from datetime import datetime

_lock = threading.Lock()
_worker_status = {
    "status": "idle",
    "source": None,
    "triggered_by": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}


def get_worker_status() -> dict:
    with _lock:
        status = dict(_worker_status)
        if status["last_started_at"] and status["status"] == "running":
            status["running"] = True
        else:
            status["running"] = False
        return status


def set_worker_status(status: str, **kwargs) -> dict:
    global _worker_status
    with _lock:
        now = datetime.utcnow().isoformat()
        _worker_status["status"] = status
        _worker_status["source"] = kwargs.get("source") or _worker_status["source"]
        _worker_status["triggered_by"] = kwargs.get("triggered_by") or _worker_status["triggered_by"]

        if status == "running":
            _worker_status["last_started_at"] = kwargs.get("started_at") or now
            _worker_status["last_finished_at"] = None
        elif status in {"finished", "failed", "idle"}:
            _worker_status["last_finished_at"] = kwargs.get("finished_at") or now
            if kwargs.get("error") is not None:
                _worker_status["last_error"] = kwargs.get("error")
            if status == "finished":
                _worker_status["last_error"] = None
        if kwargs.get("error") is not None:
            _worker_status["last_error"] = kwargs.get("error")
        if kwargs.get("source") is not None:
            _worker_status["source"] = kwargs["source"]
        if kwargs.get("triggered_by") is not None:
            _worker_status["triggered_by"] = kwargs["triggered_by"]
        return dict(_worker_status)
