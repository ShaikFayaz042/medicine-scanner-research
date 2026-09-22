"""Cloud worker configuration for the standalone scraper task."""
import os
from pathlib import Path


def _load_env_file() -> None:
    """Load repository-local environment variables for the worker package."""
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [repo_root / ".env", repo_root / "server" / ".env"]

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

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME") or os.getenv("DB_DATABASE", "cdsco_monitor")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")

ssl_suffix = ""
if "supabase" in DB_HOST.lower() or "pooler" in DB_HOST.lower() or "aws-" in DB_HOST.lower():
    ssl_suffix = "?sslmode=require"

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}{ssl_suffix}"
)

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_PREFIX = os.getenv("S3_PREFIX", "medicine-data-storage")
S3_SOURCE_PREFIX = os.getenv("S3_SOURCE_PREFIX", "source_files")
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

CLOUD_ROOT = Path(__file__).resolve().parent
PDF_DIR = Path(os.getenv("SCRAPER_PDF_DIR", str(CLOUD_ROOT / "downloads")))
PDF_DIR.mkdir(parents=True, exist_ok=True)
