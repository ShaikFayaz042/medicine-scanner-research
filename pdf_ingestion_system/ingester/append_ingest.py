"""Append-only ingest of normalized regulatory CSVs into the medicine database.

This loader intentionally does not update existing DB rows. It inserts only rows
that are not already present in the database, based on the canonical unique
keys already defined in the frozen DDL: organization_key, ingredient_key,
product_key, batch_key, event_key, and file_hash.
"""

from __future__ import annotations

import csv
import json
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import boto3
from sqlalchemy import create_engine, text

from pdf_ingestion_system.shared.config import AWS_REGION, MEDICINE_DATABASE_URL, S3_INPUT_BUCKET
from pdf_ingestion_system.shared.scraper_status import set_scraper_document_status

_INSERT_TABLES = (
    "regulatory_documents",
    "organizations",
    "ingredients",
    "products",
    "product_organizations",
    "product_ingredients",
    "batches",
    "raw_source_records",
    "regulatory_events",
    "staging_key_map",
)

_MAP_ID_COLUMNS = {
    "organization": "organization_id",
    "ingredient": "ingredient_id",
    "product": "product_id",
    "batch": "batch_id",
    "event": "event_id",
}


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        return value
    return value


def _parse_database_date(value: Any) -> date | None:
    clean = _clean_value(value)
    if not isinstance(clean, str):
        return None
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(clean, date_format).date()
        except ValueError:
            continue
        if parsed.strftime(date_format) == clean:
            return parsed
    return None


def _parse_json_value(value: Any) -> Any:
    clean = _clean_value(value)
    if clean is None:
        return None
    if isinstance(clean, str):
        stripped = clean.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return clean


def _read_csv_rows(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []
        return [
            {key: _clean_value(value) for key, value in row.items()}
            for row in reader
        ]


def _validity_map(folder_path: Path) -> tuple[dict[str, set[str]] | None, bool]:
    manifest_path = folder_path / "normalization_manifest.csv"
    if not manifest_path.exists():
        return None, False

    valid_keys = {
        "source_record_id": set(),
        "organization_key": set(),
        "product_key": set(),
        "batch_key": set(),
        "event_key": set(),
    }
    manifest_rows = _read_csv_rows(manifest_path)
    for row in manifest_rows:
        status = (row.get("validation_status") or "").strip().upper()
        if status != "VALID":
            continue
        for key_column in valid_keys:
            key = (row.get(key_column) or "").strip()
            if key:
                valid_keys[key_column].add(key)
    return valid_keys, True


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


def _insert_new_and_get_id(
    conn,
    table: str,
    key_column: str,
    id_column: str,
    values: dict[str, Any],
) -> tuple[int | None, bool]:
    if not values:
        return None, False

    columns = list(values.keys())
    placeholders = ", ".join(f":{column}" for column in columns)
    sql = text(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({key_column}) DO NOTHING"
    )
    conn.execute(sql, values)
    return _fetch_id(conn, table, id_column, key_column, values[key_column]), True


def _lookup_or_insert_organization(conn, row: dict[str, Any], cache: dict[str, int], inserted_counts: dict[str, int]) -> int:
    key = row.get("organization_key")
    if not key:
        raise ValueError("organization_key is required for organizations.csv")
    if key in cache:
        return cache[key]

    org_id = _resolve_staging_id(conn, "organization", "organizations", "organization_id", "organization_key", key, inserted_counts)
    if org_id is not None:
        cache[key] = org_id
        return org_id

    values = {
        "organization_key": key,
        "organization_name": row.get("organization_name") or "",
        "normalized_name": row.get("normalized_name"),
        "address": row.get("address"),
        "state": row.get("state"),
        "country": row.get("country") or "India",
    }
    org_id = _resolve_staging_id(conn, "organization", "organizations", "organization_id", "organization_key", key, inserted_counts)
    if org_id is None:
        insert_sql = text(
            "INSERT INTO organizations (organization_key, organization_name, normalized_name, address, state, country) "
            "VALUES (:organization_key, :organization_name, :normalized_name, :address, :state, :country) "
            "ON CONFLICT (organization_key) DO NOTHING"
        )
        result = conn.execute(insert_sql, values)
        if result.rowcount > 0:
            inserted_counts["organizations"] += result.rowcount
        org_id = _resolve_staging_id(conn, "organization", "organizations", "organization_id", "organization_key", key, inserted_counts)
    if org_id is None:
        raise RuntimeError(f"Failed to insert organization {key}")
    _save_staging_mapping(conn, "organization", key, org_id, inserted_counts)
    cache[key] = org_id
    return org_id


def _lookup_or_insert_ingredient(conn, row: dict[str, Any], cache: dict[str, int], inserted_counts: dict[str, int]) -> int:
    key = row.get("ingredient_key")
    if not key:
        raise ValueError("ingredient_key is required for ingredients.csv")
    if key in cache:
        return cache[key]

    ing_id = _resolve_staging_id(conn, "ingredient", "ingredients", "ingredient_id", "ingredient_key", key, inserted_counts)
    if ing_id is not None:
        cache[key] = ing_id
        return ing_id

    values = {
        "ingredient_key": key,
        "ingredient_name": row.get("ingredient_name") or "",
        "normalized_name": row.get("normalized_name"),
        "cas_number": row.get("cas_number"),
    }
    insert_sql = text(
        "INSERT INTO ingredients (ingredient_key, ingredient_name, normalized_name, cas_number) "
        "VALUES (:ingredient_key, :ingredient_name, :normalized_name, :cas_number) "
        "ON CONFLICT (ingredient_key) DO NOTHING"
    )
    result = conn.execute(insert_sql, values)
    if result.rowcount > 0:
        inserted_counts["ingredients"] += result.rowcount
    ing_id = _fetch_id(conn, "ingredients", "ingredient_id", "ingredient_key", key)
    if ing_id is None:
        raise RuntimeError(f"Failed to insert ingredient {key}")
    _save_staging_mapping(conn, "ingredient", key, ing_id, inserted_counts)
    cache[key] = ing_id
    return ing_id


def _lookup_or_insert_product(conn, row: dict[str, Any], cache: dict[str, int], inserted_counts: dict[str, int]) -> int:
    key = row.get("product_key")
    if not key:
        raise ValueError("product_key is required for products.csv")
    if key in cache:
        return cache[key]

    product_id = _resolve_staging_id(conn, "product", "products", "product_id", "product_key", key, inserted_counts)
    if product_id is not None:
        cache[key] = product_id
        return product_id

    values = {
        "product_key": key,
        "product_name": row.get("product_name") or "",
        "normalized_name": row.get("normalized_name"),
        "brand_name": row.get("brand_name"),
        "dosage_form": row.get("dosage_form"),
        "strength": row.get("strength"),
        "product_category": row.get("product_category") or "DRUG",
    }
    insert_sql = text(
        "INSERT INTO products (product_key, product_name, normalized_name, brand_name, dosage_form, strength, product_category) "
        "VALUES (:product_key, :product_name, :normalized_name, :brand_name, :dosage_form, :strength, :product_category) "
        "ON CONFLICT (product_key) DO NOTHING"
    )
    result = conn.execute(insert_sql, values)
    if result.rowcount > 0:
        inserted_counts["products"] += result.rowcount
    product_id = _fetch_id(conn, "products", "product_id", "product_key", key)
    if product_id is None:
        raise RuntimeError(f"Failed to insert product {key}")
    _save_staging_mapping(conn, "product", key, product_id, inserted_counts)
    cache[key] = product_id
    return product_id


def _lookup_or_insert_batch(conn, row: dict[str, Any], product_cache: dict[str, int], org_cache: dict[str, int], inserted_counts: dict[str, int]) -> int:
    key = row.get("batch_key")
    if not key:
        raise ValueError("batch_key is required for batches.csv")

    batch_id = _resolve_staging_id(conn, "batch", "batches", "batch_id", "batch_key", key, inserted_counts)
    if batch_id is not None:
        return batch_id

    product_key = row.get("product_key")
    org_key = row.get("organization_key")
    product_id = product_cache.get(product_key) if product_key else None
    org_id = org_cache.get(org_key) if org_key else None
    if product_key and product_key not in product_cache:
        raise KeyError(f"Missing product cache entry for {product_key}")
    if org_key and org_key not in org_cache:
        raise KeyError(f"Missing organization cache entry for {org_key}")

    values = {
        "batch_key": key,
        "product_id": product_id,
        "organization_id": org_id,
        "batch_number": row.get("batch_number") or "",
        "manufacturing_date": _parse_database_date(row.get("manufacturing_date")),
        "expiry_date": _parse_database_date(row.get("expiry_date")),
    }
    insert_sql = text(
        "INSERT INTO batches (batch_key, product_id, organization_id, batch_number, manufacturing_date, expiry_date) "
        "VALUES (:batch_key, :product_id, :organization_id, :batch_number, :manufacturing_date, :expiry_date) "
        "ON CONFLICT (batch_key) DO NOTHING"
    )
    result = conn.execute(insert_sql, values)
    if result.rowcount > 0:
        inserted_counts["batches"] += result.rowcount
    batch_id = _fetch_id(conn, "batches", "batch_id", "batch_key", key)
    if batch_id is None:
        raise RuntimeError(f"Failed to insert batch {key}")
    _save_staging_mapping(conn, "batch", key, batch_id, inserted_counts)
    return batch_id


def _find_existing_document(conn, document_row: dict[str, Any]) -> tuple[int, str] | None:
    source_org = document_row.get("source_organization")
    source_document_id = document_row.get("source_document_id")
    file_hash = document_row.get("file_hash")

    existing = None
    if file_hash:
        existing = conn.execute(
            text("SELECT document_id FROM regulatory_documents WHERE file_hash = :file_hash"),
            {"file_hash": file_hash},
        ).fetchone()
    if not existing and source_org and source_document_id:
        existing = conn.execute(
            text(
                "SELECT document_id FROM regulatory_documents WHERE source_organization = :source_organization "
                "AND source_document_id = :source_document_id"
            ),
            {"source_organization": source_org, "source_document_id": source_document_id},
        ).fetchone()
    if existing:
        return int(existing[0]), (source_document_id or "")
    return None


def _ingest_document_rows(folder_path: Path, engine, dry_run: bool = False) -> dict[str, Any]:
    inserted_counts = {table: 0 for table in _INSERT_TABLES}
    document_rows = _read_csv_rows(folder_path / "regulatory_documents.csv")
    if not document_rows:
        return {"status": "skipped_no_document", "reason": "No regulatory_documents.csv row found"}
    document_row = document_rows[0]
    source_org = document_row.get("source_organization")
    source_document_id = document_row.get("source_document_id")
    file_hash = document_row.get("file_hash")

    valid_keys, has_manifest = _validity_map(folder_path)
    valid_keys = valid_keys or {}

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            existing = _find_existing_document(connection, document_row)

            if existing:
                transaction.rollback()
                result = {
                    "status": "skipped_duplicate_document",
                    "document_id": existing[0],
                    "inserted_counts": inserted_counts,
                    "reason": "Document already exists",
                }
                if not dry_run:
                    result["scraper_status"] = set_scraper_document_status(
                        status="ingested",
                        source_document_id=source_document_id,
                        source_url=document_row.get("source_url"),
                    )
                return result

            doc_values = {
                "source_organization": source_org or "UNKNOWN",
                "source_document_id": source_document_id,
                "filename": document_row.get("filename") or "",
                "document_title": document_row.get("document_title"),
                "publication_date": _parse_database_date(document_row.get("publication_date")),
                "reporting_period": document_row.get("reporting_period"),
                "source_url": document_row.get("source_url") or "",
                "file_hash": file_hash,
                "document_type": document_row.get("document_type") or "UNKNOWN",
            }
            insert_doc = text(
                "INSERT INTO regulatory_documents (source_organization, source_document_id, filename, document_title, publication_date, reporting_period, source_url, file_hash, document_type) "
                "VALUES (:source_organization, :source_document_id, :filename, :document_title, :publication_date, :reporting_period, :source_url, :file_hash, :document_type)"
            )
            connection.execute(insert_doc, doc_values)
            inserted_counts["regulatory_documents"] += 1
            document_id = connection.execute(
                text("SELECT document_id FROM regulatory_documents WHERE file_hash = :file_hash"),
                {"file_hash": file_hash},
            ).fetchone()[0]

            org_cache: dict[str, int] = {}
            for org_row in _read_csv_rows(folder_path / "organizations.csv"):
                if has_manifest and org_row.get("organization_key") not in valid_keys["organization_key"]:
                    continue
                _lookup_or_insert_organization(connection, org_row, org_cache, inserted_counts)

            product_ingredient_rows = _read_csv_rows(folder_path / "product_ingredients.csv")
            valid_ingredient_keys = {
                row.get("ingredient_key")
                for row in product_ingredient_rows
                if row.get("ingredient_key")
                and (not has_manifest or row.get("product_key") in valid_keys["product_key"])
            }
            ing_cache: dict[str, int] = {}
            for ing_row in _read_csv_rows(folder_path / "ingredients.csv"):
                if has_manifest and ing_row.get("ingredient_key") not in valid_ingredient_keys:
                    continue
                _lookup_or_insert_ingredient(connection, ing_row, ing_cache, inserted_counts)

            product_cache: dict[str, int] = {}
            for prod_row in _read_csv_rows(folder_path / "products.csv"):
                if has_manifest and prod_row.get("product_key") not in valid_keys["product_key"]:
                    continue
                _lookup_or_insert_product(connection, prod_row, product_cache, inserted_counts)

            product_org_rows = _read_csv_rows(folder_path / "product_organizations.csv")
            for prod_org_row in product_org_rows:
                product_key = prod_org_row.get("product_key")
                organization_key = prod_org_row.get("organization_key")
                if has_manifest and (
                    product_key not in valid_keys["product_key"]
                    or organization_key not in valid_keys["organization_key"]
                ):
                    continue
                product_id = product_cache.get(product_key)
                org_id = org_cache.get(organization_key)
                if product_id is None or org_id is None:
                    continue
                result = connection.execute(
                    text(
                        "INSERT INTO product_organizations (product_id, organization_id, role) "
                        "VALUES (:product_id, :organization_id, :role) "
                        "ON CONFLICT (product_id, organization_id, role) DO NOTHING"
                    ),
                    {
                        "product_id": product_id,
                        "organization_id": org_id,
                        "role": prod_org_row.get("role") or "MANUFACTURER",
                    },
                )
                if result.rowcount > 0:
                    inserted_counts["product_organizations"] += result.rowcount

            for link_row in product_ingredient_rows:
                product_key = link_row.get("product_key")
                ingredient_key = link_row.get("ingredient_key")
                if has_manifest and product_key not in valid_keys["product_key"]:
                    continue
                product_id = product_cache.get(product_key)
                ingredient_id = ing_cache.get(ingredient_key)
                if product_id is None or ingredient_id is None:
                    continue
                result = connection.execute(
                    text(
                        "INSERT INTO product_ingredients (product_id, ingredient_id, ingredient_strength) "
                        "VALUES (:product_id, :ingredient_id, :ingredient_strength) "
                        "ON CONFLICT (product_id, ingredient_id) DO NOTHING"
                    ),
                    {
                        "product_id": product_id,
                        "ingredient_id": ingredient_id,
                        "ingredient_strength": link_row.get("ingredient_strength"),
                    },
                )
                if result.rowcount > 0:
                    inserted_counts["product_ingredients"] += result.rowcount

            for batch_row in _read_csv_rows(folder_path / "batches.csv"):
                if has_manifest and batch_row.get("batch_key") not in valid_keys["batch_key"]:
                    continue
                _lookup_or_insert_batch(connection, batch_row, product_cache, org_cache, inserted_counts)

            for raw_row in _read_csv_rows(folder_path / "raw_source_records.csv"):
                source_record_id = (raw_row.get("source_record_id") or "").strip()
                if has_manifest and source_record_id not in valid_keys["source_record_id"]:
                    continue
                parsed_raw_json = _parse_json_value(raw_row.get("raw_json"))
                raw_values = {
                    "document_id": document_id,
                    "source_record_id": source_record_id,
                    "page_number": raw_row.get("page_number"),
                    "source_location": raw_row.get("source_location"),
                    "extraction_method": raw_row.get("extraction_method"),
                    "source_text": raw_row.get("source_text"),
                    "raw_json": json.dumps(parsed_raw_json) if parsed_raw_json is not None else None,
                }
                result = connection.execute(
                    text(
                        "INSERT INTO raw_source_records (document_id, source_record_id, page_number, source_location, extraction_method, source_text, raw_json) "
                        "VALUES (:document_id, :source_record_id, :page_number, :source_location, :extraction_method, :source_text, :raw_json) "
                        "ON CONFLICT (document_id, source_record_id) DO NOTHING"
                    ),
                    raw_values,
                )
                if result.rowcount > 0:
                    inserted_counts["raw_source_records"] += result.rowcount

            for event_row in _read_csv_rows(folder_path / "regulatory_events.csv"):
                source_record_id = (event_row.get("source_record_id") or "").strip()
                event_key = (event_row.get("event_key") or "").strip()
                if has_manifest and event_key not in valid_keys["event_key"]:
                    continue
                if has_manifest and source_record_id not in valid_keys["source_record_id"]:
                    continue
                if not event_key:
                    raise ValueError("event_key is required for regulatory_events.csv")

                product_key = event_row.get("product_key")
                batch_key = event_row.get("batch_key")
                manufacturer_key = event_row.get("manufacturer_organization_key")
                reporting_key = event_row.get("reporting_organization_key")

                product_id = product_cache.get(product_key) if product_key else None
                batch_id = connection.execute(
                    text("SELECT batch_id FROM batches WHERE batch_key = :batch_key"),
                    {"batch_key": batch_key},
                ).fetchone()
                batch_id = int(batch_id[0]) if batch_id else None
                manufacturer_organization_id = org_cache.get(manufacturer_key) if manufacturer_key else None
                reporting_organization_id = org_cache.get(reporting_key) if reporting_key else None
                parsed_additional_data = _parse_json_value(event_row.get("additional_data"))

                event_values = {
                    "event_key": event_key,
                    "document_id": document_id,
                    "source_record_id": source_record_id,
                    "event_type": event_row.get("event_type") or "OTHER",
                    "event_date": _parse_database_date(event_row.get("event_date")),
                    "scope": event_row.get("scope") or "PRODUCT",
                    "product_id": product_id,
                    "batch_id": batch_id,
                    "manufacturer_organization_id": manufacturer_organization_id,
                    "reporting_organization_id": reporting_organization_id,
                    "status": event_row.get("status"),
                    "reason": event_row.get("reason"),
                    "action": event_row.get("action"),
                    "legal_status": event_row.get("legal_status"),
                    "additional_data": json.dumps(parsed_additional_data) if parsed_additional_data is not None else None,
                }
                result = connection.execute(
                    text(
                        "INSERT INTO regulatory_events "
                        "(event_key, document_id, source_record_id, event_type, event_date, scope, product_id, batch_id, manufacturer_organization_id, reporting_organization_id, status, reason, action, legal_status, additional_data) "
                        "VALUES (:event_key, :document_id, :source_record_id, :event_type, :event_date, :scope, :product_id, :batch_id, :manufacturer_organization_id, :reporting_organization_id, :status, :reason, :action, :legal_status, :additional_data) "
                        "ON CONFLICT (event_key) DO NOTHING"
                    ),
                    event_values,
                )
                if result.rowcount > 0:
                    inserted_counts["regulatory_events"] += result.rowcount
                event_id = _fetch_id(connection, "regulatory_events", "event_id", "event_key", event_key)
                if event_id is None:
                    raise RuntimeError(f"Failed to insert or resolve event {event_key}")
                _save_staging_mapping(connection, "event", event_key, event_id, inserted_counts)

            if dry_run:
                transaction.rollback()
                return {
                    "status": "dry_run",
                    "document_id": document_id,
                    "inserted": True,
                    "would_insert": inserted_counts,
                    "reason": "Dry run rollback",
                }

            transaction.commit()
            scraper_status = set_scraper_document_status(
                status="ingested",
                source_document_id=source_document_id,
                source_url=document_row.get("source_url"),
            )
            return {
                "status": "inserted",
                "document_id": document_id,
                "file_hash": file_hash,
                "source_organization": source_org,
                "source_document_id": source_document_id,
                "inserted_counts": inserted_counts,
                "scraper_status": scraper_status,
            }
        except Exception:
            transaction.rollback()
            raise


def ingest_document_folder(folder_path: str | Path, engine=None, dry_run: bool = False) -> dict[str, Any]:
    """Ingest one normalized document folder into the medicine database.

    The loader is intentionally append-only: it only inserts rows that are not
    already present, keyed by the canonical unique values defined in the schema.
    """
    if engine is None:
        engine = create_engine(MEDICINE_DATABASE_URL, future=True)
    folder = Path(folder_path)
    return _ingest_document_rows(folder, engine, dry_run=dry_run)


def ingest_s3_prefix(
    bucket: str,
    prefix: str,
    region: str = AWS_REGION,
    limit: int = 0,
    dry_run: bool = False,
    engine=None,
) -> list[dict[str, Any]]:
    """Download normalized CSV folders from S3 and ingest each document."""
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if engine is None:
        engine = create_engine(MEDICINE_DATABASE_URL, future=True)

    s3_client = boto3.client("s3", region_name=region)
    paginator = s3_client.get_paginator("list_objects_v2")
    staging_files = {
        "regulatory_documents.csv",
        "raw_source_records.csv",
        "organizations.csv",
        "ingredients.csv",
        "products.csv",
        "product_ingredients.csv",
        "product_organizations.csv",
        "batches.csv",
        "regulatory_events.csv",
        "normalization_manifest.csv",
    }
    document_objects: dict[str, dict[str, str]] = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            filename = Path(key).name
            if filename not in staging_files:
                continue
            parent = key.rsplit("/", 1)[0]
            document_objects.setdefault(parent, {})[filename] = key

    documents = [
        (document_prefix, objects)
        for document_prefix, objects in sorted(document_objects.items())
        if "regulatory_documents.csv" in objects
    ]
    if limit:
        documents = documents[:limit]

    results = []
    total_documents = len(documents)
    for index, (document_prefix, objects) in enumerate(documents, start=1):
        started_at = time.time()
        print(f"[ingest] [{index}/{total_documents}] START  s3_prefix={document_prefix}  dry_run={dry_run}")

        with tempfile.TemporaryDirectory(prefix="medicine-ingest-") as temp_dir:
            folder = Path(temp_dir)
            doc_csv_key = objects.get("regulatory_documents.csv")
            if doc_csv_key:
                reg_doc_path = folder / "regulatory_documents.csv"
                s3_client.download_file(bucket, doc_csv_key, str(reg_doc_path))
                doc_rows = _read_csv_rows(reg_doc_path)
                if doc_rows:
                    with engine.connect() as connection:
                        existing = _find_existing_document(connection, doc_rows[0])
                        if existing:
                            document_id = existing[0]
                            skipped = {
                                "status": "skipped_duplicate_document",
                                "document_id": document_id,
                                "inserted_counts": {table: 0 for table in _INSERT_TABLES},
                                "reason": "Document already exists",
                                "s3_prefix": document_prefix,
                            }
                            if not dry_run:
                                skipped["scraper_status"] = set_scraper_document_status(
                                    status="ingested",
                                    source_document_id=(doc_rows[0].get("source_document_id") or ""),
                                    source_url=(doc_rows[0].get("source_url") or ""),
                                )
                            results.append(skipped)
                            elapsed = round(time.time() - started_at, 2)
                            print(f"[ingest] [{index}/{total_documents}] DUPLICATE  s3_prefix={document_prefix}  document_id={document_id}  elapsed={elapsed}s")
                            continue

            for filename, key in objects.items():
                if filename == "regulatory_documents.csv":
                    continue
                s3_client.download_file(bucket, key, str(folder / filename))

            result = ingest_document_folder(folder, engine=engine, dry_run=dry_run)
            result["s3_prefix"] = document_prefix
            results.append(result)
            elapsed = round(time.time() - started_at, 2)
            status = result.get("status", "unknown")
            document_id = result.get("document_id")
            counts = result.get("inserted_counts", {})
            if status == "inserted":
                print(f"[ingest] [{index}/{total_documents}] INSERTED  s3_prefix={document_prefix}  document_id={document_id}  counts={counts}  elapsed={elapsed}s")
            elif status == "dry_run":
                print(f"[ingest] [{index}/{total_documents}] DRY_RUN  s3_prefix={document_prefix}  document_id={document_id}  would_insert={counts}  elapsed={elapsed}s")
            else:
                print(f"[ingest] [{index}/{total_documents}] {status.upper()}  s3_prefix={document_prefix}  document_id={document_id}  elapsed={elapsed}s")
    return results


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Append-only ingest of normalized document CSVs into the medicine DB.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--folder", help="Local normalized document folder to ingest")
    source.add_argument("--bucket", help="S3 bucket containing normalized document folders")
    parser.add_argument("--prefix", help="S3 prefix containing normalized document folders")
    parser.add_argument("--region", default=AWS_REGION, help="AWS region for S3")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of S3 document folders to ingest; 0 means all")
    parser.add_argument("--dry-run", action="store_true", help="Run inserts in a transaction and then roll back")
    args = parser.parse_args(argv)

    if args.limit < 0:
        parser.error("--limit must be zero or greater")
    if args.folder:
        result = ingest_document_folder(args.folder, dry_run=args.dry_run)
        print(json.dumps(result, default=str))
        scraper_status = result.get("scraper_status")
        return 1 if scraper_status and not scraper_status.get("updated") else 0
    if not args.prefix:
        parser.error("--prefix is required with --bucket")

    results = ingest_s3_prefix(
        args.bucket,
        args.prefix,
        region=args.region,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    totals = {table: sum(result.get("would_insert" if args.dry_run else "inserted_counts", {}).get(table, 0) for result in results) for table in _INSERT_TABLES}
    status_update_failures = sum(
        1
        for result in results
        if result.get("scraper_status") and not result["scraper_status"].get("updated")
    )
    print(json.dumps({
        "documents_processed": len(results),
        "dry_run": args.dry_run,
        "table_counts": totals,
        "scraper_status_update_failures": status_update_failures,
    }, default=str))
    return 1 if status_update_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
