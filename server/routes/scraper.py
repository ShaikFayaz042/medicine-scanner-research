"""Scraper-trigger routes.

Future ECS/Fargate trigger integration should live here instead of importing the
worker module directly.
"""
import json
import subprocess
import sys

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["scraper"])


def _run_scraper_via_cli(limit: int | None = None):
    """Invoke the standalone scraper CLI without importing cloud_worker.scraper.jobs."""
    cmd = [sys.executable, "-m", "cloud_worker.scraper.main"]
    if limit is not None:
        cmd.extend(["--limit", str(limit)])
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stdout = completed.stdout.strip()
    try:
        return json.loads(stdout) if stdout else {"returncode": completed.returncode}
    except json.JSONDecodeError:
        return {
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": completed.stderr.strip(),
            "trigger": "local_cli",
        }


@router.post("/scrape-now")
def scrape_now(limit: int | None = Query(None, ge=1, le=300)):
    return _run_scraper_via_cli(limit=limit)
