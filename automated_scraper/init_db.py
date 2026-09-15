"""Run once to create tables in PostgreSQL."""
from automated_scraper.database import engine, Base
from automated_scraper import models  # noqa: F401  (import needed to register models)

print("[*] Creating tables...")
Base.metadata.create_all(bind=engine)
print("[+] Done. Tables created (or already existed).")