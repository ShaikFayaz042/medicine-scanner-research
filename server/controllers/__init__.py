"""Compatibility exports for the server controller layer."""

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
