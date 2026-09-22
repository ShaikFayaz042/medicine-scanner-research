"""Seed initial scheduler configuration and trigger a scrape pass."""
from automated_scraper_demo.database.database import SessionLocal
from automated_scraper_demo.database.models import SchedulerConfig
from automated_scraper_demo.scraper.jobs import run_scraper_job


def seed_demo_data():
    db = SessionLocal()
    try:
        cfg = db.query(SchedulerConfig).first()
        if cfg is None:
            db.add(SchedulerConfig(hour=2, minute=0, enabled=True))
            db.commit()
    finally:
        db.close()

    summary = run_scraper_job(fetch_limit=20)
    print(summary)


if __name__ == "__main__":
    seed_demo_data()
