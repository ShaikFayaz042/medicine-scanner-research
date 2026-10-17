"""FastAPI application entry point for the server package."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from server import config as server_config
from server.auth.errors import register_auth_error_handlers
from server.database.init_db import ensure_pipeline_tables
from server.rate_limit import limiter
from server.routes.admin import router as admin_router
from server.routes.auth import router as auth_router
from server.routes.scans import router as scans_router
from server.routes.workflow import router as pipeline_router
from server.services.workflow_consumer import sqs_consumer_loop
from server.routes.cloud_scheduler import router as cloud_scheduler_router
from server.routes.documents import router as documents_router
from server.routes.medicines import router as medicines_router
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(server_config.CORS_ORIGINS),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)
app.state.limiter = limiter
register_auth_error_handlers(app)
app.include_router(documents_router)
app.include_router(medicines_router)
app.include_router(cloud_scheduler_router)
app.include_router(status_router)
app.include_router(auth_router)
app.include_router(scans_router)
app.include_router(admin_router)
app.include_router(pipeline_router)

CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"

if CLIENT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(CLIENT_DIST / "assets")), name="client_assets")


@app.get("/")
def ui():
    if CLIENT_DIST.exists() and (CLIENT_DIST / "index.html").exists():
        return FileResponse(CLIENT_DIST / "index.html")
    return {"service": "Medicine Scanner API", "status": "healthy", "docs": "/docs"}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi"):
        raise HTTPException(status_code=404, detail="Not found")
    if CLIENT_DIST.exists() and (CLIENT_DIST / "index.html").exists():
        return FileResponse(CLIENT_DIST / "index.html")
    return {"service": "Medicine Scanner API", "status": "healthy", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy"}
