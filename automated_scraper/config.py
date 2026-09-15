"""Application configuration."""
import os

# --- Database ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "cdsco_monitor")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "fayaz")  # <-- put your real password

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# --- Storage ---
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent
STORAGE_DIR = APP_DIR / "storage"
PDF_DIR = STORAGE_DIR / "pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

# --- Scraper ---
CDSCO_ALERTS_URL = "https://cdsco.gov.in/opencms/opencms/en/Alerts/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)