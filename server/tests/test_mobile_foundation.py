from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import UUID

from server import config as server_config
from server.database.mobile_models import Scan, User
from server.main import app


def test_mobile_database_url_reuses_medicine_database_uri():
    assert server_config.MOBILE_DATABASE_URL.startswith("postgresql")
    assert server_config.MOBILE_DATABASE_URL == server_config.MEDICINE_DATABASE_URL
    assert server_config.MOBILE_DB_SCHEMA == "mobile_app_schema"


def test_expo_web_origin_can_preflight_auth_registration():
    client = TestClient(app)
    response = client.options(
        "/auth/register",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"


def test_process_environment_overrides_env_files(monkeypatch):
    monkeypatch.setitem(server_config._ENV, "RATE_LIMIT_AUTH", "file-value")
    monkeypatch.setenv("RATE_LIMIT_AUTH", "process-value")

    assert server_config._env("RATE_LIMIT_AUTH") == "process-value"


def test_mobile_database_url_requires_supabase_and_ssl(monkeypatch):
    monkeypatch.setenv(
        "MEDICINE_DB_URI",
        "postgresql+psycopg2://user:password@db.project.supabase.co:5432/postgres?sslmode=disable",
    )
    url = server_config._medicine_database_url()
    assert "db.project.supabase.co" in url
    assert "sslmode=require" in url

    monkeypatch.setenv(
        "MEDICINE_DB_URI",
        "postgresql+psycopg2://user:password@localhost:5432/postgres",
    )
    with pytest.raises(ValueError, match="Supabase"):
        server_config._medicine_database_url()


def test_scraper_and_medicine_fallback_decisions_remain_compatible():
    assert server_config._should_use_sqlite_fallback("pooler.supabase.com", None, "development")
    assert server_config._should_use_sqlite_fallback("localhost", None, "development") is False
    assert server_config._should_use_sqlite_fallback("pooler.supabase.com", None, "production") is False


def test_mobile_models_are_schema_scoped_and_uuid_backed():
    assert User.__table__.schema == "mobile_app_schema"
    assert Scan.__table__.schema == "mobile_app_schema"
    assert isinstance(User.__table__.c.id.type, UUID)
    assert isinstance(Scan.__table__.c.id.type, UUID)
    assert User.__table__.c.email.unique is True

    fk_targets = {str(foreign_key.target_fullname) for foreign_key in Scan.__table__.c.user_id.foreign_keys}
    assert "mobile_app_schema.users.id" in fk_targets

    composite_index = next(index for index in Scan.__table__.indexes if set(index.columns.keys()) == {"user_id", "created_at"})
    assert composite_index is not None


def test_manual_mobile_migration_is_scoped_to_mobile_schema_only():
    migration_path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "mobile_app_001_init.sql"
    assert migration_path.exists()

    migration_sql = migration_path.read_text(encoding="utf-8").lower()
    assert "create schema if not exists mobile_app_schema" in migration_sql
    assert "create table if not exists mobile_app_schema.users" in migration_sql
    assert "create table if not exists mobile_app_schema.scans" in migration_sql
    assert "foreign key (user_id) references mobile_app_schema.users (id)" in migration_sql

    forbidden_objects = [
        "documents",
        "pipeline_events",
        "run_approvals",
        "scheduler_config",
        "products",
        "batches",
    ]
    for forbidden in forbidden_objects:
        assert forbidden not in migration_sql
