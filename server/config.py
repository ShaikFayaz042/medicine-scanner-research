"""Server-specific configuration for the Render/FastAPI app."""
import os
from pathlib import Path


def _load_env_file() -> None:
    """Load environment variables from project-local .env files if present."""
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

MEDICINE_DB_HOST = os.getenv("MEDICINE_DB_HOST", "localhost")
MEDICINE_DB_PORT = os.getenv("MEDICINE_DB_PORT", "5432")
MEDICINE_DB_NAME = os.getenv("MEDICINE_DB_NAME", "medicine_regulatory_db")
MEDICINE_DB_USER = os.getenv("MEDICINE_DB_USER", "postgres")
MEDICINE_DB_PASSWORD = os.getenv("MEDICINE_DB_PASSWORD")
MEDICINE_DB_URI = os.getenv("MEDICINE_DB_URI")
MEDICINE_DB_SCHEMA = os.getenv("MEDICINE_DB_SCHEMA", "public")

medicine_ssl_suffix = ""
if "supabase" in MEDICINE_DB_HOST.lower() or "pooler" in MEDICINE_DB_HOST.lower() or "aws-" in MEDICINE_DB_HOST.lower():
    medicine_ssl_suffix = "?sslmode=require"

MEDICINE_DATABASE_URL = MEDICINE_DB_URI or (
    f"postgresql+psycopg2://{MEDICINE_DB_USER}:{MEDICINE_DB_PASSWORD}"
    f"@{MEDICINE_DB_HOST}:{MEDICINE_DB_PORT}/{MEDICINE_DB_NAME}{medicine_ssl_suffix}"
)

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_PREFIX = os.getenv("S3_PREFIX", "medicine-data-storage")

# AWS ECS / EventBridge Scheduler configuration for the FastAPI controller.
ECS_CLUSTER_NAME = os.getenv("ECS_CLUSTER_NAME") or os.getenv("ECS_CLUSTER")
ECS_CLUSTER_ARN = os.getenv("ECS_CLUSTER_ARN")
ECS_TASK_DEFINITION = os.getenv("ECS_TASK_DEFINITION")
ECS_TASK_DEFINITION_ARN = os.getenv("ECS_TASK_DEFINITION_ARN")
ECS_SUBNETS = os.getenv("ECS_SUBNETS", "")
ECS_SECURITY_GROUPS = os.getenv("ECS_SECURITY_GROUPS", "")
ECS_CONTAINER_NAME = os.getenv("ECS_CONTAINER_NAME")
EVENTBRIDGE_SCHEDULE_NAME = os.getenv("EVENTBRIDGE_SCHEDULE_NAME", "cdsco-scraper-daily")
EVENTBRIDGE_SCHEDULER_ROLE_ARN = os.getenv("EVENTBRIDGE_SCHEDULER_ROLE_ARN") or os.getenv("AWS_SCHEDULER_ROLE_ARN")
AWS_ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID")

CDSCO_ALERTS_URL = "https://cdsco.gov.in/opencms/opencms/en/Alerts/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

APP_DIR = Path(__file__).resolve().parent
PDF_DIR = APP_DIR / "downloads"
PDF_DIR.mkdir(parents=True, exist_ok=True)
