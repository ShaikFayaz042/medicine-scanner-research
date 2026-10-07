"""Configuration for the standalone data collection service."""
import os
from pathlib import Path


def _load_env_file() -> None:
    """Load service-local or repository-local environment variables."""
    service_root = Path(__file__).resolve().parent
    repo_root = service_root.parent
    candidates = [service_root / ".env", repo_root / ".env", repo_root / "server" / ".env"]

    for env_file in candidates:
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

SCRAPER_DB_HOST = os.getenv("SCRAPER_DB_HOST", "localhost")
SCRAPER_DB_PORT = os.getenv("SCRAPER_DB_PORT", "5432")
SCRAPER_DB_NAME = os.getenv("SCRAPER_DB_NAME", "cdsco_monitor")
SCRAPER_DB_USER = os.getenv("SCRAPER_DB_USER", "postgres")
SCRAPER_DB_PASSWORD = os.getenv("SCRAPER_DB_PASSWORD")

ssl_suffix = ""
if "supabase" in SCRAPER_DB_HOST.lower() or "pooler" in SCRAPER_DB_HOST.lower() or "aws-" in SCRAPER_DB_HOST.lower():
    ssl_suffix = "?sslmode=require"

DATABASE_URL = (
    f"postgresql+psycopg2://{SCRAPER_DB_USER}:{SCRAPER_DB_PASSWORD}"
    f"@{SCRAPER_DB_HOST}:{SCRAPER_DB_PORT}/{SCRAPER_DB_NAME}{ssl_suffix}"
)

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
S3_PREFIX = os.getenv("AWS_S3_PREFIX", "medicine-data-storage")
S3_SOURCE_PREFIX = os.getenv("AWS_S3_SOURCE_PREFIX", "source_files")
S3_SOURCE_FOLDERS = {
    "cdsco_alerts": "alerts",
    "alerts": "alerts",
    "cdsco_fdc": "fdc",
    "fdc": "fdc",
    "cdsco_nsq": "nsq",
    "nsq": "nsq",
    "ipc_pvpi": "ipc",
    "pvpi": "ipc",
    "cdsco_banned_drugs": "banned",
    "banned": "banned",
}

CDSCO_ALERTS_URL = "https://cdsco.gov.in/opencms/opencms/en/Alerts/"
CDSCO_FDC_URL = "https://cdsco.gov.in/opencms/opencms/en/Drugs/FDC/"
CDSCO_BANNED_DRUGS_URL = "https://cdsco.gov.in/opencms/opencms/en/BannedDrugs"
CDSCO_ONLINE_BASE_URL = "https://cdscoonline.gov.in"
IPC_PVPI_URL = "https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

SERVICE_ROOT = Path(__file__).resolve().parent
PDF_DIR = Path(os.getenv("SCRAPER_PDF_DIR", str(SERVICE_ROOT / "downloads")))
PDF_DIR.mkdir(parents=True, exist_ok=True)

# --- Pipeline trigger config ---
SFN_STATE_MACHINE_ARN = os.getenv(
    "SFN_STATE_MACHINE_ARN",
    "arn:aws:states:ap-south-1:449902674528:stateMachine:pdf-ingestion-pipeline",
)
SFN_TRIGGER_MAX_ATTEMPTS = int(os.getenv("SFN_TRIGGER_MAX_ATTEMPTS", "3"))
SFN_TRIGGER_RETRY_INTERVAL_SECONDS = int(
    os.getenv("SFN_TRIGGER_RETRY_INTERVAL_SECONDS", "5")
)
