"""
APScheduler wrapper.

- Runs as a background scheduler inside the FastAPI process.
- Reads the (single-row) scheduler_config table on startup.
- Fires run_scraper_job() at the configured local time.
"""
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.jobs import run_scraper_job
from app.models import SchedulerConfig

JOB_ID = "cdsco_scraper"

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# The function APScheduler calls when the time arrives
# ---------------------------------------------------------------------------

def _job_wrapper():
    print(f"\n[SCHEDULER] Triggered at {datetime.now().isoformat()}")
    try:
        summary = run_scraper_job()
        print(f"[SCHEDULER] Completed — new={summary['new']}, "
              f"downloaded={summary['downloaded']}, failed={summary['failed']}")
    except Exception as e:
        print(f"[SCHEDULER] FAILED: {e}")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_config() -> SchedulerConfig:
    """Get the single config row, creating a default if none exists."""
    db = SessionLocal()
    try:
        cfg = db.query(SchedulerConfig).first()
        if cfg is None:
            cfg = SchedulerConfig(hour=2, minute=0, enabled=True)
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return cfg
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def _apply_config(cfg: SchedulerConfig):
    """(Re)schedule the job based on the given config."""
    global _scheduler
    assert _scheduler is not None

    # Remove existing job if present
    existing = _scheduler.get_job(JOB_ID)
    if existing:
        existing.remove()

    if not cfg.enabled:
        print("[SCHEDULER] Job disabled — not scheduled")
        return

    trigger = CronTrigger(hour=cfg.hour, minute=cfg.minute)
    _scheduler.add_job(
        _job_wrapper,
        trigger=trigger,
        id=JOB_ID,
        name="CDSCO scraper",
        replace_existing=True,
        coalesce=True,            # if multiple fires missed, run once
        max_instances=1,          # never overlap
        misfire_grace_time=3600,  # tolerate 1h if the process was paused
    )
    job = _scheduler.get_job(JOB_ID)
    next_run = job.next_run_time if job else None
    print(f"[SCHEDULER] Job scheduled for {cfg.hour:02d}:{cfg.minute:02d} daily "
          f"(next run: {next_run})")


# ---------------------------------------------------------------------------
# Public API — called from FastAPI
# ---------------------------------------------------------------------------

def start_scheduler():
    """Start the scheduler and load config. Called from FastAPI lifespan."""
    global _scheduler
    if _scheduler is not None:
        print("[SCHEDULER] Already running")
        return

    _scheduler = BackgroundScheduler()
    _scheduler.start()
    print("[SCHEDULER] Started")

    cfg = _load_config()
    _apply_config(cfg)


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("[SCHEDULER] Stopped")


def update_schedule(hour: int, minute: int, enabled: bool) -> dict:
    """Update DB config and reschedule immediately."""
    db = SessionLocal()
    try:
        cfg = db.query(SchedulerConfig).first()
        if cfg is None:
            cfg = SchedulerConfig()
            db.add(cfg)
        cfg.hour = hour
        cfg.minute = minute
        cfg.enabled = enabled
        db.commit()
        db.refresh(cfg)
        _apply_config(cfg)
    finally:
        db.close()
    return get_scheduler_state()


def get_scheduler_state() -> dict:
    """Return current config + next run info."""
    db = SessionLocal()
    try:
        cfg = db.query(SchedulerConfig).first()
        if cfg is None:
            return {"configured": False}
        job = _scheduler.get_job(JOB_ID) if _scheduler else None
        next_run = job.next_run_time if job else None
        return {
            "configured": True,
            "hour": cfg.hour,
            "minute": cfg.minute,
            "enabled": cfg.enabled,
            "time_str": f"{cfg.hour:02d}:{cfg.minute:02d}",
            "next_run": next_run.isoformat() if next_run else None,
            "running": _scheduler.running if _scheduler else False,
        }
    finally:
        db.close()