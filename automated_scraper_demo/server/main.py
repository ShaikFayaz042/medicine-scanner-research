"""CDSCO Monitor — FastAPI application entry point."""
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from automated_scraper_demo.config import PDF_DIR
from automated_scraper_demo.database.database import SessionLocal
from automated_scraper_demo.database.models import Document
from automated_scraper_demo.scraper.jobs import _parse_cdsco_date, run_scraper_job
from automated_scraper_demo.scheduler import scheduler as sched_mod


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched_mod.start_scheduler()
    yield
    sched_mod.shutdown_scheduler()


app = FastAPI(title="CDSCO Monitor", version="0.1.0", lifespan=lifespan)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "client"))


@app.get("/", response_class=HTMLResponse)
def ui(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/scrape-now")
def scrape_now(limit: int | None = Query(None, ge=1, le=300)):
    return run_scraper_job(fetch_limit=limit)


def _date_sort_key(d: Document) -> datetime:
    """Parse CDSCO's 'YYYY-Mon-DD' string into a real datetime."""
    try:
        return _parse_cdsco_date(d.release_date)
    except (ValueError, TypeError):
        return datetime.min


@app.get("/api/documents")
def list_documents():
    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        docs.sort(key=lambda d: d.document_id)
        docs.sort(key=_date_sort_key, reverse=True)

        return {
            "count": len(docs),
            "documents": [
                {
                    "id": d.id,
                    "document_id": d.document_id,
                    "title": d.title,
                    "release_date": d.release_date,
                    "status": d.status,
                    "file_size_bytes": d.file_size_bytes,
                    "pdf_url": d.pdf_url,
                    "local_file_path": d.local_file_path,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in docs
            ],
        }
    finally:
        db.close()


@app.get("/api/documents/{document_id}")
def get_document(document_id: int):
    db = SessionLocal()
    try:
        d = db.query(Document).filter(Document.document_id == document_id).first()
        if not d:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "document_id": d.document_id,
            "title": d.title,
            "release_date": d.release_date,
            "status": d.status,
            "pdf_url": d.pdf_url,
            "local_file_path": d.local_file_path,
            "file_size_bytes": d.file_size_bytes,
            "content_hash": d.content_hash,
        }
    finally:
        db.close()


@app.get("/static-pdf/{document_id}.pdf")
def serve_pdf(document_id: int):
    path = PDF_DIR / f"{document_id}.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(path), media_type="application/pdf")


class ScheduleUpdate(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(..., ge=0, le=59)
    enabled: bool = True


@app.get("/api/scheduler")
def get_scheduler():
    return sched_mod.get_scheduler_state()


@app.put("/api/scheduler")
def set_scheduler(payload: ScheduleUpdate):
    return sched_mod.update_schedule(
        hour=payload.hour, minute=payload.minute, enabled=payload.enabled,
    )
