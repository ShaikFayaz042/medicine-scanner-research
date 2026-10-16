"""Compatibility wrapper for the legacy admin controller import path."""

from server.services.admin_service import (
    get_dashboard_summary,
    get_scraper_status,
    get_system_status,
)

__all__ = [
    "get_dashboard_summary",
    "get_scraper_status",
    "get_system_status",
]
