"""
Read-only database access for the Medicine Scanner search API.

- SELECT-only.
- Forces READ ONLY + correct search_path on every physical connection.
- Detects pg_trgm availability so matchers can fall back to ILIKE + difflib.
"""
from __future__ import annotations

import logging
import os
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


def _build_url() -> str:
    if url := os.getenv("DATABASE_URL"):
        return url
    user = os.getenv("DB_USER", "postgres")
    pwd = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "cdsco_monitor")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}"


DATABASE_URL = _build_url()
SCHEMA = os.getenv("DB_SCHEMA", "medicine_scanner")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _record):  # noqa: ANN001
    # Do NOT swallow errors here — if these fail, the connection is unusable.
    cur = dbapi_conn.cursor()
    try:
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.execute(f"SET search_path TO {SCHEMA}, public")
    finally:
        cur.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _detect_pg_trgm() -> bool:
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).first()
            return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("pg_trgm detection failed: %s", exc)
        return False


HAS_PG_TRGM: bool = _detect_pg_trgm()


def schema_diagnostics() -> dict:
    """Small diagnostic used by /api/diagnostics."""
    out: dict = {
        "schema": SCHEMA,
        "pg_trgm": HAS_PG_TRGM,
        "tables": [],
        "error": None,
    }
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s ORDER BY table_name"
                ),
                {"s": SCHEMA},
            ).all()
            out["tables"] = [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out