"""Admin panel routes for dashboard, scraper, and system monitoring."""

from fastapi import APIRouter

from server.controllers import admin_controller

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard")
def dashboard():
    return admin_controller.get_dashboard_summary()


@router.get("/scraper/status")
def scraper_status():
    return admin_controller.get_scraper_status()


@router.get("/system")
def system_status():
    return admin_controller.get_system_status()
