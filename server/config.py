"""Server-specific configuration for the Render/FastAPI app."""
from pathlib import Path

from sqlalchemy.engine import URL, make_url


def _load_env_file() -> dict[str, str]:
    """Read repository- and server-scoped env variables without using process env."""
    env_files = [
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parent / ".env",
    ]

    values: dict[str, str] = {}
    for env_file in env_files:
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_ENV = _load_env_file()


def _env(name: str, default: str | None = None) -> str | None:
    return _ENV.get(name, default)


def _is_remote_supabase_pooler(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower()
    return any(marker in host for marker in ("supabase", "pooler", "aws-"))


def _should_use_sqlite_fallback(host: str | None, uri: str | None, app_env: str | None = None) -> bool:
    if (app_env or _env("APP_ENV") or "").lower() == "production":
        return False

    if uri:
        try:
            parsed_uri = make_url(uri)
        except Exception:
            return True
        if parsed_uri.host:
            return _is_remote_supabase_pooler(parsed_uri.host)

    return _is_remote_supabase_pooler(host)


def _local_sqlite_url(database_name: str = "medicine_scanner.sqlite3") -> str:
    database_path = (Path(__file__).resolve().parents[1] / "server" / database_name).resolve()
    return f"sqlite:///{database_path.as_posix()}"


APP_ENV = _env("APP_ENV", "development")
SCRAPER_DB_HOST = _env("SCRAPER_DB_HOST", "localhost")
SCRAPER_DB_PORT = _env("SCRAPER_DB_PORT", "5432")
SCRAPER_DB_NAME = _env("SCRAPER_DB_NAME", "cdsco_monitor")
SCRAPER_DB_USER = _env("SCRAPER_DB_USER", "postgres")
SCRAPER_DB_PASSWORD = _env("SCRAPER_DB_PASSWORD")
SCRAPER_DB_URI = _env("SCRAPER_DB_URI")

if _should_use_sqlite_fallback(SCRAPER_DB_HOST, SCRAPER_DB_URI, APP_ENV):
    DATABASE_URL = _local_sqlite_url("scraper_local.sqlite3")
else:
    requires_ssl = _is_remote_supabase_pooler(SCRAPER_DB_HOST)
    if SCRAPER_DB_URI:
        scraper_url = make_url(SCRAPER_DB_URI)
        if requires_ssl or "supabase" in (scraper_url.host or "").lower() or "pooler" in (scraper_url.host or "").lower():
            query = dict(scraper_url.query)
            query.setdefault("sslmode", "require")
            scraper_url = scraper_url.set(query=query)
        DATABASE_URL = scraper_url.render_as_string(hide_password=False)
    else:
        DATABASE_URL = URL.create(
            "postgresql+psycopg2",
            username=SCRAPER_DB_USER,
            password=SCRAPER_DB_PASSWORD,
            host=SCRAPER_DB_HOST,
            port=int(SCRAPER_DB_PORT),
            database=SCRAPER_DB_NAME,
            query={"sslmode": "require"} if requires_ssl else {},
        ).render_as_string(hide_password=False)

MEDICINE_DB_HOST = _env("MEDICINE_DB_HOST", "localhost")
MEDICINE_DB_PORT = _env("MEDICINE_DB_PORT", "5432")
MEDICINE_DB_NAME = _env("MEDICINE_DB_NAME", "medicine_regulatory_db")
MEDICINE_DB_USER = _env("MEDICINE_DB_USER", "postgres")
MEDICINE_DB_PASSWORD = _env("MEDICINE_DB_PASSWORD")
MEDICINE_DB_URI = _env("MEDICINE_DB_URI")
MEDICINE_DB_SCHEMA = _env("MEDICINE_DB_SCHEMA", "medicine_scanner")

if _should_use_sqlite_fallback(MEDICINE_DB_HOST, MEDICINE_DB_URI, APP_ENV):
    MEDICINE_DATABASE_URL = _local_sqlite_url("medicine_local.sqlite3")
else:
    medicine_ssl_suffix = ""
    if "supabase" in MEDICINE_DB_HOST.lower() or "pooler" in MEDICINE_DB_HOST.lower() or "aws-" in MEDICINE_DB_HOST.lower():
        medicine_ssl_suffix = "?sslmode=require"

    MEDICINE_DATABASE_URL = MEDICINE_DB_URI or (
        f"postgresql+psycopg2://{MEDICINE_DB_USER}:{MEDICINE_DB_PASSWORD}"
        f"@{MEDICINE_DB_HOST}:{MEDICINE_DB_PORT}/{MEDICINE_DB_NAME}{medicine_ssl_suffix}"
    )

AWS_REGION = _env("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME = _env("AWS_S3_BUCKET_NAME", "medicine-data-storage-449902674528-ap-south-1-an")
S3_PREFIX = _env("AWS_S3_PREFIX", "medicine-data-storage")

SQS_QUEUE_URL = _env("SQS_QUEUE_URL", "https://sqs.ap-south-1.amazonaws.com/449902674528/pipeline-events")
SQS_DLQ_URL = _env("SQS_DLQ_URL", "https://sqs.ap-south-1.amazonaws.com/449902674528/pipeline-events-dlq")
SQS_MAX_MESSAGES = int(_env("SQS_MAX_MESSAGES", "10"))
SQS_WAIT_SECONDS = int(_env("SQS_WAIT_SECONDS", "20"))
SQS_VISIBILITY_TIMEOUT = int(_env("SQS_VISIBILITY_TIMEOUT", "60"))
SQS_MAX_RECEIVE_COUNT = int(_env("SQS_MAX_RECEIVE_COUNT", "3"))

# SQS / pipeline event config
SQS_QUEUE_URL = _env("SQS_QUEUE_URL", "https://sqs.ap-south-1.amazonaws.com/449902674528/pipeline-events")
SQS_MAX_MESSAGES = int(_env("SQS_MAX_MESSAGES", "10"))
SQS_WAIT_SECONDS = int(_env("SQS_WAIT_SECONDS", "20"))
SQS_VISIBILITY_TIMEOUT = int(_env("SQS_VISIBILITY_TIMEOUT", "60"))

# Pipeline orchestration config
SFN_STATE_MACHINE_ARN = _env("SFN_STATE_MACHINE_ARN", "arn:aws:states:ap-south-1:449902674528:stateMachine:pdf-ingestion-pipeline")
INGESTER_TASK_DEFINITION = _env("INGESTER_TASK_DEFINITION", "data-ingester-task")
ECS_CLUSTER = _env("ECS_CLUSTER", "medicine-scanner-cluster")
ECS_SUBNET = _env("ECS_SUBNET", "subnet-0a54f8319db88cd67")
ECS_SECURITY_GROUP = _env("ECS_SECURITY_GROUP", "sg-059755d9860be0cc7")

# AWS ECS / EventBridge Scheduler configuration for the FastAPI controller.
ECS_CLUSTER_NAME = _env("ECS_CLUSTER_NAME") or _env("ECS_CLUSTER")
ECS_CLUSTER_ARN = _env("ECS_CLUSTER_ARN")
ECS_TASK_DEFINITION = _env("ECS_TASK_DEFINITION")
ECS_TASK_DEFINITION_ARN = _env("ECS_TASK_DEFINITION_ARN")
ECS_SUBNETS = _env("ECS_SUBNETS", "")
ECS_SECURITY_GROUPS = _env("ECS_SECURITY_GROUPS", "")
ECS_CONTAINER_NAME = _env("ECS_CONTAINER_NAME")
EVENTBRIDGE_SCHEDULE_NAME = _env("EVENTBRIDGE_SCHEDULE_NAME", "cdsco-scraper-daily")
EVENTBRIDGE_SCHEDULER_ROLE_ARN = _env("EVENTBRIDGE_SCHEDULER_ROLE_ARN") or _env("AWS_SCHEDULER_ROLE_ARN")
AWS_ACCOUNT_ID = _env("AWS_ACCOUNT_ID")
