"""Create and upgrade the SQLAlchemy tables used by the FastAPI server."""
from sqlalchemy import inspect, text

from server.database import models  # noqa: F401
from server.database.database import Base, engine


DOCUMENT_COLUMNS = {
    "source": "VARCHAR NOT NULL DEFAULT 'unknown'",
    "source_key": "VARCHAR",
    "document_type": "VARCHAR",
    "metadata": "JSONB",
    "profile_status": "VARCHAR",
    "processing_stage": "VARCHAR",
}


def ensure_document_columns() -> None:
    """Add source fields to an existing documents table without dropping data."""
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("documents")}
    with engine.begin() as connection:
        for name, definition in DOCUMENT_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE documents ADD COLUMN "{name}" {definition}'))


def _upgrade_sqlite_integer_primary_key(connection, table) -> None:
    """Rebuild a SQLite table whose BigInteger primary key cannot auto-increment."""
    table_name = table.name
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    if table_name not in table_names:
        return

    id_column = next(column for column in inspector.get_columns(table_name) if column["name"] == "id")
    if str(id_column["type"]).upper() == "INTEGER":
        return

    legacy_name = f"_{table_name}_legacy"
    if legacy_name in table_names:
        raise RuntimeError(f"Cannot migrate {table_name}: {legacy_name} already exists")

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    expected_columns = {column.name for column in table.columns}
    if existing_columns != expected_columns:
        raise RuntimeError(
            f"Cannot migrate {table_name}: existing columns do not match the expected schema"
        )

    preparer = connection.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    quoted_legacy = preparer.quote(legacy_name)
    for index in inspector.get_indexes(table_name):
        connection.execute(text(f"DROP INDEX {preparer.quote(index['name'])}"))

    connection.execute(text(f"ALTER TABLE {quoted_table} RENAME TO {quoted_legacy}"))
    table.create(connection)

    column_list = ", ".join(preparer.quote(column.name) for column in table.columns)
    connection.execute(
        text(
            f"INSERT INTO {quoted_table} ({column_list}) "
            f"SELECT {column_list} FROM {quoted_legacy}"
        )
    )
    connection.execute(text(f"DROP TABLE {quoted_legacy}"))


def ensure_pipeline_tables(bind=None) -> None:
    """Create pipeline tables and migrate SQLite autoincrement primary keys safely."""
    bind = bind or engine
    tables = [models.PipelineEvent.__table__, models.RunApproval.__table__]
    with bind.begin() as connection:
        Base.metadata.create_all(bind=connection, tables=tables)
        if bind.dialect.name == "sqlite":
            for table in tables:
                _upgrade_sqlite_integer_primary_key(connection, table)


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    ensure_document_columns()
    ensure_pipeline_tables()
    print("Database tables created or upgraded.")
