"""Create database tables for the monitor application."""
from automated_scraper_demo.database.database import Base, engine
from automated_scraper_demo.database import models  # noqa: F401  (register model metadata)


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")
