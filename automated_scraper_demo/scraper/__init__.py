"""Scraper layer for CDSCO alert monitoring."""

__all__ = ["scrape_alerts", "run_scraper_job"]


def __getattr__(name):
    if name == "scrape_alerts":
        from .scraper import scrape_alerts

        return scrape_alerts
    if name == "run_scraper_job":
        from .jobs import run_scraper_job

        return run_scraper_job
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
