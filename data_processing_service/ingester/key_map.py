"""Append-only staging-key to database-ID mapping helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


_MAP_ID_COLUMNS = {
    "organization": "organization_id",
    "ingredient": "ingredient_id",
    "product": "product_id",
    "batch": "batch_id",
    "event": "event_id",
}


def _fetch_id(conn, table: str, id_column: str, key_column: str, key_value: Any) -> int | None:
    result = conn.execute(
        text(f"SELECT {id_column} FROM {table} WHERE {key_column} = :key_value"),
        {"key_value": key_value},
    ).fetchone()
    return int(result[0]) if result else None


def _mapped_id(conn, entity_type: str, staging_key: str) -> int | None:
    id_column = _MAP_ID_COLUMNS[entity_type]
    result = conn.execute(
        text(f"SELECT {id_column} FROM staging_key_map WHERE entity_type = :entity_type AND staging_key = :staging_key"),
        {"entity_type": entity_type, "staging_key": staging_key},
    ).fetchone()
    return int(result[0]) if result else None


def _save_staging_mapping(conn, entity_type: str, staging_key: str, entity_id: int, inserted_counts: dict[str, int]) -> None:
    id_column = _MAP_ID_COLUMNS[entity_type]
    result = conn.execute(
        text(
            f"INSERT INTO staging_key_map (entity_type, staging_key, {id_column}) "
            f"VALUES (:entity_type, :staging_key, :entity_id) "
            "ON CONFLICT (entity_type, staging_key) DO NOTHING"
        ),
        {"entity_type": entity_type, "staging_key": staging_key, "entity_id": entity_id},
    )
    if result.rowcount > 0:
        inserted_counts["staging_key_map"] += result.rowcount
    mapped_id = _mapped_id(conn, entity_type, staging_key)
    if mapped_id != entity_id:
        raise RuntimeError(f"Conflicting staging key mapping for {entity_type}:{staging_key}")


def _resolve_staging_id(conn, entity_type: str, table: str, id_column: str, key_column: str, key: str, inserted_counts: dict[str, int]) -> int | None:
    mapped_id = _mapped_id(conn, entity_type, key)
    if mapped_id is not None:
        return mapped_id
    entity_id = _fetch_id(conn, table, id_column, key_column, key)
    if entity_id is not None:
        _save_staging_mapping(conn, entity_type, key, entity_id, inserted_counts)
    return entity_id
