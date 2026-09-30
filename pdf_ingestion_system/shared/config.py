"""Configuration local to the PDF ingestion tools."""

import os
from pathlib import Path

from sqlalchemy.engine import URL, make_url


REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_INGESTION_ROOT = Path(__file__).resolve().parents[1]
_PDF_SCRAPER_DB_SETTINGS: dict[str, str] = {}


def _load_env_files() -> None:
    env_files = (REPO_ROOT / ".env", REPO_ROOT / "server" / ".env", PDF_INGESTION_ROOT / ".env")
    for env_file in reversed(env_files):
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if env_file == PDF_INGESTION_ROOT / ".env" and key.startswith("SCRAPER_DB_"):
                _PDF_SCRAPER_DB_SETTINGS[key] = value
                continue
            os.environ.setdefault(key, value)


_load_env_files()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_INPUT_BUCKET = os.getenv("AWS_S3_INPUT_BUCKET") or os.getenv("AWS_S3_BUCKET_NAME")
S3_INPUT_PREFIX = os.getenv("AWS_S3_INPUT_PREFIX") or "/".join(
    part.strip("/")
    for part in (os.getenv("AWS_S3_PREFIX", "medicine-data-storage"), os.getenv("AWS_S3_SOURCE_PREFIX", "source_files"))
    if part.strip("/")
)
S3_OUTPUT_BUCKET = os.getenv("AWS_S3_OUTPUT_BUCKET") or S3_INPUT_BUCKET
S3_OUTPUT_PREFIX = os.getenv(
    "AWS_S3_OUTPUT_PREFIX",
    "medicine-data-storage/processed_files/profiler_output",
)

SCRAPER_DB_HOST = _PDF_SCRAPER_DB_SETTINGS.get("SCRAPER_DB_HOST", os.getenv("SCRAPER_DB_HOST", "localhost"))
SCRAPER_DB_PORT = _PDF_SCRAPER_DB_SETTINGS.get("SCRAPER_DB_PORT", os.getenv("SCRAPER_DB_PORT", "5432"))
SCRAPER_DB_NAME = _PDF_SCRAPER_DB_SETTINGS.get("SCRAPER_DB_NAME", os.getenv("SCRAPER_DB_NAME", "cdsco_monitor"))
SCRAPER_DB_USER = _PDF_SCRAPER_DB_SETTINGS.get("SCRAPER_DB_USER", os.getenv("SCRAPER_DB_USER", "postgres"))
SCRAPER_DB_PASSWORD = _PDF_SCRAPER_DB_SETTINGS.get("SCRAPER_DB_PASSWORD", os.getenv("SCRAPER_DB_PASSWORD"))
SCRAPER_DB_URI = _PDF_SCRAPER_DB_SETTINGS.get("SCRAPER_DB_URI", os.getenv("SCRAPER_DB_URI"))

_ssl_suffix = ""
if "supabase" in SCRAPER_DB_HOST.lower() or "pooler" in SCRAPER_DB_HOST.lower() or "aws-" in SCRAPER_DB_HOST.lower():
    _ssl_suffix = "?sslmode=require"

if SCRAPER_DB_URI:
    scraper_url = make_url(SCRAPER_DB_URI)
    if "supabase" in (scraper_url.host or "").lower() or "pooler" in (scraper_url.host or "").lower():
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
        query={"sslmode": "require"} if _ssl_suffix else {},
    ).render_as_string(hide_password=False)

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

if "pooler.supabase.com" in MEDICINE_DB_HOST.lower() and MEDICINE_DB_USER and MEDICINE_DB_PASSWORD:
    MEDICINE_DATABASE_URL = URL.create(
        "postgresql+psycopg2",
        username=MEDICINE_DB_USER,
        password=MEDICINE_DB_PASSWORD,
        host=MEDICINE_DB_HOST,
        port=int(MEDICINE_DB_PORT),
        database=MEDICINE_DB_NAME,
        query={"sslmode": "require"},
    ).render_as_string(hide_password=False)
elif MEDICINE_DB_URI:
    medicine_url = make_url(MEDICINE_DB_URI)
    if "supabase" in (medicine_url.host or "").lower() or "pooler" in (medicine_url.host or "").lower():
        query = dict(medicine_url.query)
        query.setdefault("sslmode", "require")
        medicine_url = medicine_url.set(query=query)
    MEDICINE_DATABASE_URL = medicine_url.render_as_string(hide_password=False)
else:
    MEDICINE_DATABASE_URL = (
        f"postgresql+psycopg2://{MEDICINE_DB_USER}:{MEDICINE_DB_PASSWORD}"
        f"@{MEDICINE_DB_HOST}:{MEDICINE_DB_PORT}/{MEDICINE_DB_NAME}{medicine_ssl_suffix}"
    )
