"""Application configuration."""
import os
from pathlib import Path


def _load_env_file() -> None:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# --- Database ---
LOCAL_DB_HOST = os.getenv("LOCAL_DB_HOST", "localhost")
LOCAL_DB_PORT = os.getenv("LOCAL_DB_PORT", "5432")
LOCAL_DB_NAME = os.getenv("LOCAL_DB_NAME", "cdsco_monitor")
LOCAL_DB_USER = os.getenv("LOCAL_DB_USER", "postgres")
LOCAL_DB_PASSWORD = os.getenv("LOCAL_DB_PASSWORD", "")

DATABASE_URL = (
    f"postgresql+psycopg2://{LOCAL_DB_USER}:{LOCAL_DB_PASSWORD}"
    f"@{LOCAL_DB_HOST}:{LOCAL_DB_PORT}/{LOCAL_DB_NAME}"
)

# --- Storage ---
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent
STORAGE_DIR = APP_DIR / "storage"
PDF_DIR = STORAGE_DIR
PDF_DIR.mkdir(parents=True, exist_ok=True)

# --- Scraper ---
CDSCO_ALERTS_URL = "https://cdsco.gov.in/opencms/opencms/en/Alerts/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)