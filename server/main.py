"""FastAPI application entry point for the server package."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from server.database.init_db import ensure_pipeline_tables
from server.pipeline.consumer import sqs_consumer_loop
from server.pipeline.routes import router as pipeline_router
from server.routes.admin import router as admin_router
from server.routes.cloud_scheduler import router as cloud_scheduler_router
from server.routes.documents import router as documents_router
from server.routes.medicines import router as medicines_router
from server.routes.scraper import router as scraper_router
from server.routes.status import router as status_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_pipeline_tables()
    consumer_task = asyncio.create_task(sqs_consumer_loop())
    try:
        yield
    finally:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Medicine Scanner API", version="0.1.0", lifespan=lifespan)
app.include_router(documents_router)
app.include_router(medicines_router)
app.include_router(scraper_router)
app.include_router(cloud_scheduler_router)
app.include_router(status_router)
app.include_router(admin_router)
app.include_router(pipeline_router)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"

if CLIENT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(CLIENT_DIST / "assets")), name="client_assets")


@app.get("/", response_class=HTMLResponse)
def ui(request: Request):
    if CLIENT_DIST.exists() and (CLIENT_DIST / "index.html").exists():
        return FileResponse(CLIENT_DIST / "index.html")
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
def health():
    return {"status": "healthy"}
