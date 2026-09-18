from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def _db_reachable() -> bool:
    try:
        from backend.database import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


DB_OK = _db_reachable()


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _require_db():
    if not DB_OK and os.getenv("SCANNER_ALLOW_NO_DB") != "1":
        pytest.skip("PostgreSQL not reachable; set SCANNER_ALLOW_NO_DB=1 to skip silently")