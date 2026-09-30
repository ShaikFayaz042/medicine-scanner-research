"""Database access local to the PDF ingestion tools."""

from sqlalchemy import Column, MetaData, String, Table, bindparam, create_engine, select, text, update

from pdf_ingestion_system.shared.config import DATABASE_URL


engine = create_engine(DATABASE_URL, echo=False, future=True)
_documents = Table(
    "documents",
    MetaData(),
    Column("s3_object_key", String),
    Column("title", String),
    Column("profile_status", String),
    Column("processing_stage", String),
)


def ensure_profile_columns() -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS profile_status VARCHAR"
        )
        connection.exec_driver_sql(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_stage VARCHAR"
        )


def get_document_metadata(s3_object_keys: list[str]) -> dict[str, dict]:
    """Fetch scraper-owned document metadata by the canonical PDF S3 key."""
    unique_keys = list(dict.fromkeys(key for key in s3_object_keys if key))
    if not unique_keys:
        return {}

    statement = text(
        """
        SELECT s3_object_key, title, source, source_key, document_type,
               release_date, metadata
        FROM documents
        WHERE s3_object_key = ANY(:s3_object_keys)
        """
    )
    metadata_by_key: dict[str, dict] = {}
    with engine.connect() as connection:
        for offset in range(0, len(unique_keys), 500):
            batch = unique_keys[offset:offset + 500]
            rows = connection.execute(
                statement, {"s3_object_keys": batch}
            ).mappings()
            for row in rows:
                metadata_by_key[row["s3_object_key"]] = {
                    "title": row["title"],
                    "source": row["source"],
                    "source_key": row["source_key"],
                    "document_type": row["document_type"],
                    "release_date": row["release_date"],
                    "metadata": row["metadata"] or {},
                }

    return metadata_by_key


def update_profiled_documents(
    profile_results: list[tuple[str, str]],
) -> tuple[int, int, dict[str, str]]:
    if not profile_results:
        return 0, 0, {}

    status_by_key = dict(profile_results)
    matched_keys: set[str] = set()
    titles_by_key: dict[str, str] = {}
    update_statement = (
        update(_documents)
        .where(_documents.c.s3_object_key == bindparam("match_s3_object_key"))
        .values(profile_status=bindparam("profile_status"), processing_stage="profiled")
    )

    with engine.begin() as connection:
        keys = list(status_by_key)
        for offset in range(0, len(keys), 500):
            batch_keys = keys[offset:offset + 500]
            matched_batch = connection.execute(
                select(_documents.c.s3_object_key, _documents.c.title).where(
                    _documents.c.s3_object_key.in_(batch_keys)
                )
            ).all()
            matched_keys.update(key for key, _ in matched_batch)
            titles_by_key.update({key: title or "" for key, title in matched_batch})
            if matched_batch:
                connection.execute(
                    update_statement,
                    [
                        {
                            "match_s3_object_key": key,
                            "profile_status": status_by_key[key],
                        }
                        for key, _ in matched_batch
                    ],
                )

    return len(matched_keys), len(status_by_key) - len(matched_keys), titles_by_key


def update_extracted_documents(s3_object_keys: list[str]) -> int:
    """Mark matched document rows as extracted using the same s3_object_key contract."""
    if not s3_object_keys:
        return 0

    unique_keys = list(dict.fromkeys(s3_object_keys))
    with engine.begin() as connection:
        matched = connection.execute(
            select(_documents.c.s3_object_key).where(
                _documents.c.s3_object_key.in_(unique_keys)
            )
        ).scalars().all()
        if not matched:
            return 0

        connection.execute(
            update(_documents)
            .where(_documents.c.s3_object_key == bindparam("match_s3_object_key"))
            .values(processing_stage="extracted"),
            [
                {"match_s3_object_key": key}
                for key in matched
            ],
        )

    return len(matched)


def update_classified_documents(s3_object_keys: list[str]) -> int:
    """Mark matched document rows as classified using the same s3_object_key contract."""
    if not s3_object_keys:
        return 0

    unique_keys = list(dict.fromkeys(s3_object_keys))
    with engine.begin() as connection:
        matched = connection.execute(
            select(_documents.c.s3_object_key).where(
                _documents.c.s3_object_key.in_(unique_keys)
            )
        ).scalars().all()
        if not matched:
            return 0

        connection.execute(
            update(_documents)
            .where(_documents.c.s3_object_key == bindparam("match_s3_object_key"))
            .values(processing_stage="classified"),
            [
                {"match_s3_object_key": key}
                for key in matched
            ],
        )

    return len(matched)


def update_parsed_documents(s3_object_keys: list[str]) -> int:
    """Mark matched document rows as parsed using the same s3_object_key contract."""
    if not s3_object_keys:
        return 0

    unique_keys = list(dict.fromkeys(s3_object_keys))
    with engine.begin() as connection:
        matched = connection.execute(
            select(_documents.c.s3_object_key).where(
                _documents.c.s3_object_key.in_(unique_keys)
            )
        ).scalars().all()
        if not matched:
            return 0

        connection.execute(
            update(_documents)
            .where(_documents.c.s3_object_key == bindparam("match_s3_object_key"))
            .values(processing_stage="parsed"),
            [
                {"match_s3_object_key": key}
                for key in matched
            ],
        )

    return len(matched)
