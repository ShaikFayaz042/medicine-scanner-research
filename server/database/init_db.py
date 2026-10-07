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


def ensure_pipeline_tables() -> None:
    """Create the pipeline event and run approval tables if they do not exist."""
    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.PipelineEvent.__table__,
            models.RunApproval.__table__,
        ],
    )


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    ensure_document_columns()
    ensure_pipeline_tables()
    print("Database tables created or upgraded.")
