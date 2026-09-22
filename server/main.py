"""FastAPI application entry point for the server package."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from server.routes.admin import router as admin_router
from server.routes.cloud_scheduler import router as cloud_scheduler_router
from server.routes.documents import router as documents_router
from server.routes.medicines import router as medicines_router
from server.routes.scraper import router as scraper_router
from server.routes.status import router as status_router


app = FastAPI(title="Medicine Scanner API", version="0.1.0")
app.include_router(documents_router)
app.include_router(medicines_router)
app.include_router(scraper_router)
app.include_router(cloud_scheduler_router)
app.include_router(status_router)
app.include_router(admin_router)

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
