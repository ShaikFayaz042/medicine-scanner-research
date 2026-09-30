"""Synchronize normalized/ingested lifecycle states to scraper documents."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from pdf_ingestion_system.shared.config import DATABASE_URL


_STATUS_ENGINE = None


def set_scraper_document_status(
    *,
    status: str,
    source_document_id: str | None = None,
    source_url: str | None = None,
    source_s3_key: str | None = None,
    engine=None,
) -> dict[str, object]:
    """Update one scraper document row, refusing ambiguous identity matches."""
    global _STATUS_ENGINE
    owns_engine = engine is None
    if owns_engine:
        if _STATUS_ENGINE is None:
            _STATUS_ENGINE = create_engine(DATABASE_URL, future=True)
        engine = _STATUS_ENGINE

    try:
        inspector = inspect(engine)
        if not inspector.has_table("documents"):
            return {"updated": False, "reason": "documents table not found"}
        columns = {column["name"] for column in inspector.get_columns("documents")}
        update_columns = [column for column in ("status", "processing_stage") if column in columns]
        if not update_columns:
            return {"updated": False, "reason": "no supported status columns"}

        candidates = []
        for column, value in (
            ("s3_object_key", source_url),
            ("s3_object_key", source_s3_key),
            ("pdf_url", source_url),
            ("source_key", source_document_id),
            ("source_key", source_url),
            ("document_id", source_document_id),
        ):
            if column in columns and value:
                candidate = (column, value)
                if candidate not in candidates:
                    candidates.append(candidate)

        if not candidates:
            return {"updated": False, "reason": "no usable document identity"}

        values = {column: status for column in update_columns}
        if "updated_at" in columns:
            values["updated_at"] = text("CURRENT_TIMESTAMP")
        assignments = ", ".join(f"{column} = :{column}" for column in update_columns)
        if "updated_at" in values:
            assignments += ", updated_at = CURRENT_TIMESTAMP"
            values.pop("updated_at")

        with engine.begin() as connection:
            for column, identity in candidates:
                if column == "document_id":
                    where = "CAST(document_id AS TEXT) = :identity"
                else:
                    where = f"{column} = :identity"
                matches = connection.execute(
                    text(f"SELECT count(1) FROM documents WHERE {where}"),
                    {"identity": identity},
                ).scalar_one()
                if matches == 0:
                    continue
                if matches != 1:
                    return {"updated": False, "reason": "ambiguous document identity", "matched_by": column}
                result = connection.execute(
                    text(f"UPDATE documents SET {assignments} WHERE {where}"),
                    {**values, "identity": identity},
                )
                return {
                    "updated": result.rowcount == 1,
                    "matched_by": column,
                    "updated_columns": update_columns,
                    "rows": result.rowcount,
                }

        return {"updated": False, "reason": "scraper document row not found"}
    except Exception as exc:
        return {"updated": False, "error": type(exc).__name__}
    finally:
        if owns_engine and _STATUS_ENGINE is not None:
            _STATUS_ENGINE.dispose()
            _STATUS_ENGINE = None
