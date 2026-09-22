"""One-shot scraper worker entry point for ECS/Fargate-style execution.

This module is designed to run as a temporary task: start, perform the
scrape workflow once, then exit without starting a long-lived web service.
"""
import argparse
import json
import os
from urllib import error, request

from cloud_worker.scraper.jobs import run_scraper_job


def _notify_backend(event: str, payload: dict | None = None) -> None:
    base_url = os.getenv("APP_BASE_URL") or os.getenv("SERVER_BASE_URL") or os.getenv("BACKEND_URL")
    if not base_url:
        return
    data = payload or {}
    data.setdefault("source", "aws-ecs")
    data.setdefault("triggered_by", os.getenv("SCRAPER_TRIGGER", "scheduler"))
    try:
        req = request.Request(
            f"{base_url.rstrip('/')}/api/scheduler/worker/{event}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5):
            pass
    except (error.URLError, TimeoutError, OSError):
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CDSCO scraper once.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of records to scrape in one run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the run plan without executing the scraper.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("Dry run requested: scraper execution skipped.")
        return 0

    _notify_backend("start")
    try:
        summary = run_scraper_job(fetch_limit=args.limit)
    except Exception as exc:
        _notify_backend("error", {"error": str(exc)})
        raise
    _notify_backend("finish", {"status": "finished", "summary": summary})
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
