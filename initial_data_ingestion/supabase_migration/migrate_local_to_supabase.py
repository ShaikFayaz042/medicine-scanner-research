"""Replace Supabase ingestion tables with validated local staging data.

This script is intentionally destructive only when --yes is supplied. The delete
and reload run in one PostgreSQL transaction, so a load failure rolls back the
replacement.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "initial_data_ingestion"))

from shared.load_db import load_staging_to_db
from shared.validate import validate_staging_dir


DEFAULT_STAGING = ROOT / "initial_data_ingestion" / "09_normalization" / "01_staging" / "corrected_aggregate"
TABLES_DELETE_ORDER = (
    "regulatory_events",
    "raw_source_records",
    "product_ingredients",
    "product_organizations",
    "batches",
    "products",
    "ingredients",
    "organizations",
    "regulatory_documents",
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def supabase_connection_kwargs() -> dict[str, object]:
    """Read Supabase settings without putting credentials in source control."""
    load_env_file(ROOT / ".env")
    load_env_file(ROOT / "initial_data_ingestion" / ".env")

    host = os.getenv("SUPABASE_HOST") or os.getenv("DB_HOST")
    port = os.getenv("SUPABASE_PORT") or os.getenv("DB_PORT", "5432")
    database = os.getenv("SUPABASE_DATABASE") or os.getenv("DB_NAME") or os.getenv("DB_DATABASE", "postgres")
    user = os.getenv("SUPABASE_USER") or os.getenv("DB_USER")
    password = os.getenv("SUPABASE_PASSWORD") or os.getenv("DB_PASSWORD")

    missing = [name for name, value in {
        "SUPABASE_HOST/DB_HOST": host,
        "SUPABASE_USER/DB_USER": user,
        "SUPABASE_PASSWORD/DB_PASSWORD": password,
    }.items() if not value]
    if missing:
        raise RuntimeError("Missing Supabase settings: " + ", ".join(missing))

    return {
        "host": host,
        "port": int(port),
        "dbname": database,
        "user": user,
        "password": unquote(password),
        "sslmode": "require",
    }


def count_rows(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        result = {}
        for table in reversed(TABLES_DELETE_ORDER):
            cur.execute(f"SELECT count(*) FROM {table}")
            result[table] = cur.fetchone()[0]
        return result


def replace_supabase_data(staging_dir: Path, confirm: bool, dry_run: bool) -> None:
    valid, errors = validate_staging_dir(str(staging_dir))
    if not valid:
        raise RuntimeError("Staging validation failed:\n" + "\n".join(errors[:50]))

    kwargs = supabase_connection_kwargs()
    conn = psycopg2.connect(**kwargs)
    try:
        before = count_rows(conn)
        print("Connected to Supabase:", kwargs["host"], "database=", kwargs["dbname"])
        print("Existing rows:", before)

        if dry_run:
            print("Dry run: validation and connection check passed; no data changed.")
            return
        if not confirm:
            raise RuntimeError("Refusing to delete Supabase data. Re-run with --yes.")

        with conn.cursor() as cur:
            for table in TABLES_DELETE_ORDER:
                cur.execute(f"DELETE FROM {table}")

        counts = load_staging_to_db(str(staging_dir), db_connection=conn)
        conn.commit()
        print("Supabase replacement committed.")
        print("Loaded rows:", counts)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace Supabase ingestion data from corrected local staging")
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--yes", action="store_true", help="Confirm destructive delete and reload")
    parser.add_argument("--dry-run", action="store_true", help="Validate staging and connect without changing data")
    args = parser.parse_args()
    replace_supabase_data(args.staging, confirm=args.yes, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
