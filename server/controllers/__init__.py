"""Controller layer for the server application."""

from server.controllers.admin_controller import (
    get_dashboard_summary,
    get_scraper_status,
    get_system_status,
)

__all__ = [
    "get_dashboard_summary",
    "get_scraper_status",
    "get_system_status",
]
