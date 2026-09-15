"""
Read-only Medicine Scanner API entrypoint.

Run:
    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import schema_diagnostics
from backend.scanner_api.router import router as scanner_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Medicine Scanner - Regulatory Search API",
    version="0.1.0",
    description=(
        "Read-only search API for CDSCO/IPC-PvPI regulatory information. "
        "Never medical advice. Never a safety certification."
    ),
)

app.include_router(scanner_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/diagnostics")
def diagnostics() -> dict:
    """Quick DB/schema reachability check."""
    return schema_diagnostics()


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))