"""Admin panel routes for dashboard, scraper, and system monitoring."""

from fastapi import APIRouter

from server.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard")
def dashboard():
    return admin_service.get_dashboard_summary()


@router.get("/scraper/status")
def scraper_status():
    return admin_service.get_scraper_status()


@router.get("/system")
def system_status():
    return admin_service.get_system_status()
