"""APScheduler wrapper for the CDSCO monitor."""
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from automated_scraper_demo.database.database import SessionLocal
from automated_scraper_demo.database.models import SchedulerConfig
from automated_scraper_demo.scraper.jobs import run_scraper_job


def _ensure_scheduler_started():
    """Create a background scheduler if one was never initialized."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        print("[SCHEDULER] Started on demand")
    return _scheduler

JOB_ID = "cdsco_scraper"
_scheduler: BackgroundScheduler | None = None


def _job_wrapper():
    print(f"\n[SCHEDULER] Triggered at {datetime.now().isoformat()}")
    try:
        summary = run_scraper_job()
        print(f"[SCHEDULER] Completed — new={summary['new']}, downloaded={summary['downloaded']}, failed={summary['failed']}")
    except Exception as e:
        print(f"[SCHEDULER] FAILED: {e}")


def _load_config() -> SchedulerConfig:
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


def _apply_config(cfg: SchedulerConfig):
    scheduler = _ensure_scheduler_started()

    existing = scheduler.get_job(JOB_ID)
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
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    job = _scheduler.get_job(JOB_ID)
    next_run = job.next_run_time if job else None
    print(f"[SCHEDULER] Job scheduled for {cfg.hour:02d}:{cfg.minute:02d} daily (next run: {next_run})")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        print("[SCHEDULER] Already running")
        return

    _ensure_scheduler_started()
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
            "running": bool(_scheduler and _scheduler.running),
        }
    finally:
        db.close()
