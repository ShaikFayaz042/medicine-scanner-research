from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint, create_engine, event
from sqlalchemy.exc import IntegrityError

import pdf_ingestion_system.ingester.append_ingest as append_ingest
from pdf_ingestion_system.ingester.append_ingest import ingest_document_folder
from pdf_ingestion_system.shared.scraper_status import set_scraper_document_status


@pytest.fixture(autouse=True)
def stub_scraper_db_status(monkeypatch):
    status_update = Mock(return_value={"updated": True, "matched_by": "s3_object_key"})
    monkeypatch.setattr(
        append_ingest,
        "set_scraper_document_status",
        status_update,
    )
    return status_update


def _create_db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    metadata = MetaData()

    Table(
        "organizations",
        metadata,
        Column("organization_id", Integer, primary_key=True),
        Column("organization_key", String(64), unique=True, nullable=False),
        Column("organization_name", Text, nullable=False),
        Column("normalized_name", Text),
        Column("address", Text),
        Column("state", String(200)),
        Column("country", String(200), default="India"),
        Column("created_at", String),
    )

    Table(
        "ingredients",
        metadata,
        Column("ingredient_id", Integer, primary_key=True),
        Column("ingredient_key", String(64), unique=True, nullable=False),
        Column("ingredient_name", Text, nullable=False),
        Column("normalized_name", Text, unique=True),
        Column("cas_number", String(100)),
    )

    Table(
        "products",
        metadata,
        Column("product_id", Integer, primary_key=True),
        Column("product_key", String(64), unique=True, nullable=False),
        Column("product_name", Text, nullable=False),
        Column("normalized_name", Text),
        Column("brand_name", Text),
        Column("dosage_form", Text),
        Column("strength", Text),
        Column("product_category", String(50), nullable=False),
        CheckConstraint("product_category IN ('DRUG', 'MEDICAL_DEVICE', 'IVD_KIT', 'VACCINE', 'FDC', 'COSMETIC')"),
    )

    Table(
        "product_ingredients",
        metadata,
        Column("product_id", ForeignKey("products.product_id", ondelete="CASCADE"), primary_key=True),
        Column("ingredient_id", ForeignKey("ingredients.ingredient_id", ondelete="CASCADE"), primary_key=True),
        Column("ingredient_strength", Text),
    )

    Table(
        "product_organizations",
        metadata,
        Column("product_id", ForeignKey("products.product_id", ondelete="CASCADE"), primary_key=True),
        Column("organization_id", ForeignKey("organizations.organization_id", ondelete="CASCADE"), primary_key=True),
        Column("role", String(50), nullable=False, primary_key=True),
        CheckConstraint("role IN ('MANUFACTURER', 'IMPORTER', 'APPLICANT', 'MARKETING_AUTHORIZATION_HOLDER')"),
    )

    Table(
        "regulatory_documents",
        metadata,
        Column("document_id", Integer, primary_key=True),
        Column("source_organization", Text, nullable=False),
        Column("source_document_id", Text),
        Column("filename", Text, nullable=False),
        Column("document_title", Text),
        Column("publication_date", Date),
        Column("reporting_period", String(200)),
        Column("source_url", Text, nullable=False),
        Column("file_hash", String(64), unique=True),
        Column("document_type", String(100)),
        Column("created_at", String),
        UniqueConstraint("source_organization", "source_document_id"),
        CheckConstraint("document_type IN ('BANNED_DRUGS', 'PVPI_ADR', 'NSQ_STATE', 'SPURIOUS', 'NSQ_CDSCO', 'LEGACY_CDSCO', 'MEDICAL_DEVICE', 'APPROVED_DRUGS', 'NOC_IMPORT_FDC', 'MIXED_ALERT', 'UNKNOWN')"),
    )

    Table(
        "raw_source_records",
        metadata,
        Column("raw_source_id", Integer, primary_key=True),
        Column("document_id", ForeignKey("regulatory_documents.document_id", ondelete="CASCADE"), nullable=False),
        Column("source_record_id", String, nullable=False),
        Column("page_number", Integer),
        Column("source_location", Text),
        Column("extraction_method", String(50)),
        Column("source_text", Text),
        Column("raw_json", Text),
        UniqueConstraint("document_id", "source_record_id"),
    )

    Table(
        "batches",
        metadata,
        Column("batch_id", Integer, primary_key=True),
        Column("batch_key", String(64), unique=True, nullable=False),
        Column("product_id", ForeignKey("products.product_id")),
        Column("organization_id", ForeignKey("organizations.organization_id")),
        Column("batch_number", Text, nullable=False),
        Column("manufacturing_date", Date),
        Column("expiry_date", Date),
        UniqueConstraint("product_id", "organization_id", "batch_number"),
    )

    Table(
        "regulatory_events",
        metadata,
        Column("event_id", Integer, primary_key=True),
        Column("event_key", String(64), unique=True, nullable=False),
        Column("document_id", ForeignKey("regulatory_documents.document_id"), nullable=False),
        Column("source_record_id", Text, nullable=False),
        Column("event_type", String(100), nullable=False),
        Column("event_date", Date),
        Column("scope", String(50), nullable=False),
        Column("product_id", ForeignKey("products.product_id")),
        Column("batch_id", ForeignKey("batches.batch_id")),
        Column("manufacturer_organization_id", ForeignKey("organizations.organization_id")),
        Column("reporting_organization_id", ForeignKey("organizations.organization_id")),
        Column("status", String(100)),
        Column("reason", Text),
        Column("action", Text),
        Column("legal_status", Text),
        Column("additional_data", Text),
        Column("created_at", String),
        CheckConstraint("event_type IN ('BANNED', 'PROHIBITED', 'NSQ', 'SPURIOUS', 'ADR', 'RECALL', 'APPROVAL', 'NOC', 'IMPORT_PERMISSION', 'SAFETY_ADVISORY', 'SUSPENSION', 'WITHDRAWAL', 'UNDER_INVESTIGATION', 'OTHER')"),
        CheckConstraint("scope IN ('BATCH', 'PRODUCT', 'INGREDIENT', 'COMBINATION', 'DOCUMENT')"),
    )

    Table(
        "staging_key_map",
        metadata,
        Column("staging_key_map_id", Integer, primary_key=True),
        Column("entity_type", String(32), nullable=False),
        Column("staging_key", String(64), nullable=False),
        Column("organization_id", ForeignKey("organizations.organization_id"), unique=True),
        Column("ingredient_id", ForeignKey("ingredients.ingredient_id"), unique=True),
        Column("product_id", ForeignKey("products.product_id"), unique=True),
        Column("batch_id", ForeignKey("batches.batch_id"), unique=True),
        Column("event_id", ForeignKey("regulatory_events.event_id"), unique=True),
        Column("created_at", String),
        UniqueConstraint("entity_type", "staging_key"),
        CheckConstraint("entity_type IN ('organization', 'ingredient', 'product', 'batch', 'event')"),
        CheckConstraint("(entity_type = 'organization' AND organization_id IS NOT NULL AND ingredient_id IS NULL AND product_id IS NULL AND batch_id IS NULL AND event_id IS NULL) OR (entity_type = 'ingredient' AND organization_id IS NULL AND ingredient_id IS NOT NULL AND product_id IS NULL AND batch_id IS NULL AND event_id IS NULL) OR (entity_type = 'product' AND organization_id IS NULL AND ingredient_id IS NULL AND product_id IS NOT NULL AND batch_id IS NULL AND event_id IS NULL) OR (entity_type = 'batch' AND organization_id IS NULL AND ingredient_id IS NULL AND product_id IS NULL AND batch_id IS NOT NULL AND event_id IS NULL) OR (entity_type = 'event' AND organization_id IS NULL AND ingredient_id IS NULL AND product_id IS NULL AND batch_id IS NULL AND event_id IS NOT NULL)"),
    )

    metadata.create_all(engine)
    return engine


def _write_csv(path, headers, rows, encoding="utf-8"):
    with path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _write_document_header(doc_dir, source_document_id="doc_minimal", file_hash="d" * 64, encoding="utf-8"):
    _write_csv(
        doc_dir / "regulatory_documents.csv",
        ["source_organization", "source_document_id", "filename", "document_title", "publication_date", "reporting_period", "source_url", "file_hash", "document_type"],
        [{"source_organization": "CDSCO", "source_document_id": source_document_id, "filename": "minimal.pdf", "document_title": "Minimal", "publication_date": "", "reporting_period": "", "source_url": "https://example.com/minimal.pdf", "file_hash": file_hash, "document_type": "UNKNOWN"}],
        encoding=encoding,
    )


def test_ingester_inserts_only_new_rows(tmp_path, stub_scraper_db_status):
    engine = _create_db()
    doc_id = "doc_123"
    org_key = "org_hash_1"
    ing_key = "ing_hash_1"
    prod_key = "prod_hash_1"
    batch_key = "batch_hash_1"
    event_key = "event_hash_1"
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()

    _write_csv(
        doc_dir / "regulatory_documents.csv",
        [
            "source_organization",
            "source_document_id",
            "filename",
            "document_title",
            "publication_date",
            "reporting_period",
            "source_url",
            "file_hash",
            "document_type",
        ],
        [{
            "source_organization": "CDSCO",
            "source_document_id": doc_id,
            "filename": "demo.json",
            "document_title": "Demo doc",
            "publication_date": "Jun-2026",
            "reporting_period": "",
            "source_url": "https://example.com/demo.pdf",
            "file_hash": "abc123" * 8,
            "document_type": "UNKNOWN",
        }],
    )
    _write_csv(
        doc_dir / "organizations.csv",
        ["organization_key", "organization_name", "normalized_name", "address", "state", "country"],
        [{"organization_key": org_key, "organization_name": "Acme Pharma", "normalized_name": "acme pharma", "address": "", "state": "", "country": "India"}],
    )
    _write_csv(
        doc_dir / "ingredients.csv",
        ["ingredient_key", "ingredient_name", "normalized_name", "cas_number"],
        [{"ingredient_key": ing_key, "ingredient_name": "Paracetamol", "normalized_name": "paracetamol", "cas_number": ""}],
    )
    _write_csv(
        doc_dir / "products.csv",
        ["product_key", "product_name", "normalized_name", "brand_name", "dosage_form", "strength", "product_category"],
        [{"product_key": prod_key, "product_name": "Paracetamol 500mg", "normalized_name": "paracetamol 500mg", "brand_name": "", "dosage_form": "Tablet", "strength": "500mg", "product_category": "DRUG"}],
    )
    _write_csv(
        doc_dir / "product_ingredients.csv",
        ["product_key", "ingredient_key", "ingredient_strength"],
        [{"product_key": prod_key, "ingredient_key": ing_key, "ingredient_strength": "500mg"}],
    )
    _write_csv(
        doc_dir / "product_organizations.csv",
        ["product_key", "organization_key", "role"],
        [{"product_key": prod_key, "organization_key": org_key, "role": "MANUFACTURER"}],
    )
    _write_csv(
        doc_dir / "batches.csv",
        ["batch_key", "product_key", "organization_key", "batch_number", "manufacturing_date", "expiry_date"],
        [{"batch_key": batch_key, "product_key": prod_key, "organization_key": org_key, "batch_number": "B1", "manufacturing_date": "Jun-2026", "expiry_date": "Dec-2026"}],
    )
    _write_csv(
        doc_dir / "raw_source_records.csv",
        ["source_document_id", "source_record_id", "page_number", "source_location", "extraction_method", "source_text", "raw_json"],
        [{"source_document_id": doc_id, "source_record_id": "rec_1", "page_number": "1", "source_location": "Page 1", "extraction_method": "TEXT", "source_text": "paracetamol", "raw_json": json.dumps({"name": "paracetamol"})}],
    )
    _write_csv(
        doc_dir / "regulatory_events.csv",
        ["event_key", "source_document_id", "source_record_id", "event_type", "event_date", "scope", "product_key", "batch_key", "manufacturer_organization_key", "reporting_organization_key", "status", "reason", "action", "legal_status", "additional_data"],
        [{
            "event_key": event_key,
            "source_document_id": doc_id,
            "source_record_id": "rec_1",
            "event_type": "BANNED",
            "event_date": "Jun-2026",
            "scope": "PRODUCT",
            "product_key": prod_key,
            "batch_key": batch_key,
            "manufacturer_organization_key": org_key,
            "reporting_organization_key": org_key,
            "status": "BANNED",
            "reason": "",
            "action": "BAN",
            "legal_status": "",
            "additional_data": json.dumps({"note": "demo"}),
        }],
    )
    _write_csv(
        doc_dir / "normalization_manifest.csv",
        ["source_record_id", "source_document_id", "source_file", "source_page", "source_row", "source_document_type", "organization_key", "product_key", "batch_key", "event_key", "normalization_status", "validation_status", "review_reason", "error_message"],
        [{
            "source_record_id": "rec_1",
            "source_document_id": doc_id,
            "source_file": "demo.json",
            "source_page": "1",
            "source_row": "1",
            "source_document_type": "UNKNOWN",
            "organization_key": org_key,
            "product_key": prod_key,
            "batch_key": batch_key,
            "event_key": event_key,
            "normalization_status": "COMPLETE",
            "validation_status": "VALID",
            "review_reason": "",
            "error_message": "",
        }],
    )

    first = ingest_document_folder(doc_dir, engine=engine)
    _write_csv(
        doc_dir / "regulatory_documents.csv",
        ["source_organization", "source_document_id", "filename", "document_title", "publication_date", "reporting_period", "source_url", "file_hash", "document_type"],
        [{"source_organization": "CDSCO", "source_document_id": "different_source_id", "filename": "demo.json", "document_title": "Demo doc", "publication_date": "", "reporting_period": "", "source_url": "https://example.com/demo.pdf", "file_hash": "abc123" * 8, "document_type": "UNKNOWN"}],
    )
    second = ingest_document_folder(doc_dir, engine=engine)
    assert first["status"] == "inserted"
    assert second["status"] == "skipped_duplicate_document"

    with engine.connect() as conn:
        doc_count = conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0]
        product_count = conn.exec_driver_sql("SELECT COUNT(*) FROM products").fetchone()[0]
        event_count = conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_events").fetchone()[0]
        mappings = conn.exec_driver_sql(
            "SELECT entity_type, staging_key, organization_id, ingredient_id, product_id, batch_id, event_id "
            "FROM staging_key_map ORDER BY entity_type"
        ).fetchall()
        raw_json = conn.exec_driver_sql("SELECT raw_json FROM raw_source_records").fetchone()[0]
        additional_data = conn.exec_driver_sql("SELECT additional_data FROM regulatory_events").fetchone()[0]
        empty_dates = conn.exec_driver_sql(
            "SELECT publication_date FROM regulatory_documents"
        ).fetchone()[0]
        partial_batch_dates = conn.exec_driver_sql(
            "SELECT manufacturing_date, expiry_date FROM batches"
        ).fetchone()
        partial_event_date = conn.exec_driver_sql(
            "SELECT event_date FROM regulatory_events"
        ).fetchone()[0]

    assert doc_count == 1
    assert product_count == 1
    assert event_count == 1
    assert first["inserted_counts"]["regulatory_documents"] == 1
    assert first["inserted_counts"]["organizations"] == 1
    assert first["inserted_counts"]["staging_key_map"] == 5
    assert second["inserted_counts"]["regulatory_documents"] == 0
    assert [call.kwargs["status"] for call in stub_scraper_db_status.call_args_list] == ["ingested", "ingested"]
    assert len(mappings) == 5
    assert {row[0] for row in mappings} == {"organization", "ingredient", "product", "batch", "event"}
    assert json.loads(raw_json) == {"name": "paracetamol"}
    assert json.loads(additional_data) == {"note": "demo"}
    assert empty_dates is None
    assert partial_batch_dates == (None, None)
    assert partial_event_date is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-06-15", date(2026, 6, 15)),
        ("15/06/2026", date(2026, 6, 15)),
        ("Jun-2026", None),
        ("2026-02-30", None),
        ("", None),
    ],
)
def test_parse_database_date_requires_day_precision(value, expected):
    assert append_ingest._parse_database_date(value) == expected


def test_ingester_dry_run_never_writes(tmp_path, stub_scraper_db_status):
    engine = _create_db()
    doc_dir = tmp_path / "doc2"
    doc_dir.mkdir()
    _write_csv(
        doc_dir / "regulatory_documents.csv",
        [
            "source_organization",
            "source_document_id",
            "filename",
            "document_title",
            "publication_date",
            "reporting_period",
            "source_url",
            "file_hash",
            "document_type",
        ],
        [{
            "source_organization": "CDSCO",
            "source_document_id": "doc_456",
            "filename": "demo2.json",
            "document_title": "Demo doc 2",
            "publication_date": "",
            "reporting_period": "",
            "source_url": "https://example.com/demo2.pdf",
            "file_hash": "zzz999",
            "document_type": "UNKNOWN",
        }],
    )
    _write_csv(
        doc_dir / "organizations.csv",
        ["organization_key", "organization_name", "normalized_name", "address", "state", "country"],
        [{"organization_key": "org_hash_2", "organization_name": "Beta", "normalized_name": "beta", "address": "", "state": "", "country": "India"}],
    )
    _write_csv(doc_dir / "ingredients.csv", ["ingredient_key", "ingredient_name", "normalized_name", "cas_number"], [{"ingredient_key": "ing_hash_2", "ingredient_name": "Ibuprofen", "normalized_name": "ibuprofen", "cas_number": ""}])
    _write_csv(doc_dir / "products.csv", ["product_key", "product_name", "normalized_name", "brand_name", "dosage_form", "strength", "product_category"], [{"product_key": "prod_hash_2", "product_name": "Ibuprofen 200mg", "normalized_name": "ibuprofen 200mg", "brand_name": "", "dosage_form": "Tablet", "strength": "200mg", "product_category": "DRUG"}])
    _write_csv(doc_dir / "product_ingredients.csv", ["product_key", "ingredient_key", "ingredient_strength"], [{"product_key": "prod_hash_2", "ingredient_key": "ing_hash_2", "ingredient_strength": "200mg"}])
    _write_csv(doc_dir / "product_organizations.csv", ["product_key", "organization_key", "role"], [{"product_key": "prod_hash_2", "organization_key": "org_hash_2", "role": "MANUFACTURER"}])
    _write_csv(doc_dir / "batches.csv", ["batch_key", "product_key", "organization_key", "batch_number", "manufacturing_date", "expiry_date"], [{"batch_key": "batch_hash_2", "product_key": "prod_hash_2", "organization_key": "org_hash_2", "batch_number": "B2", "manufacturing_date": "", "expiry_date": ""}])
    _write_csv(doc_dir / "raw_source_records.csv", ["source_document_id", "source_record_id", "page_number", "source_location", "extraction_method", "source_text", "raw_json"], [{"source_document_id": "doc_456", "source_record_id": "rec_2", "page_number": "1", "source_location": "Page 1", "extraction_method": "TEXT", "source_text": "ibuprofen", "raw_json": json.dumps({"name": "ibuprofen"})}])
    _write_csv(doc_dir / "regulatory_events.csv", ["event_key", "source_document_id", "source_record_id", "event_type", "event_date", "scope", "product_key", "batch_key", "manufacturer_organization_key", "reporting_organization_key", "status", "reason", "action", "legal_status", "additional_data"], [{"event_key": "event_hash_2", "source_document_id": "doc_456", "source_record_id": "rec_2", "event_type": "BANNED", "event_date": "", "scope": "PRODUCT", "product_key": "prod_hash_2", "batch_key": "batch_hash_2", "manufacturer_organization_key": "org_hash_2", "reporting_organization_key": "org_hash_2", "status": "BANNED", "reason": "", "action": "BAN", "legal_status": "", "additional_data": json.dumps({"note": "demo2"})}])
    _write_csv(doc_dir / "normalization_manifest.csv", ["source_record_id", "source_document_id", "source_file", "source_page", "source_row", "source_document_type", "organization_key", "product_key", "batch_key", "event_key", "normalization_status", "validation_status", "review_reason", "error_message"], [{"source_record_id": "rec_2", "source_document_id": "doc_456", "source_file": "demo2.json", "source_page": "1", "source_row": "1", "source_document_type": "UNKNOWN", "organization_key": "org_hash_2", "product_key": "prod_hash_2", "batch_key": "batch_hash_2", "event_key": "event_hash_2", "normalization_status": "COMPLETE", "validation_status": "VALID", "review_reason": "", "error_message": ""}])

    result = ingest_document_folder(doc_dir, engine=engine, dry_run=True)
    assert result["status"] == "dry_run"
    stub_scraper_db_status.assert_not_called()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM staging_key_map").fetchone()[0] == 0


def test_empty_document_csv_is_skipped(tmp_path):
    engine = _create_db()
    doc_dir = tmp_path / "empty"
    doc_dir.mkdir()
    _write_csv(doc_dir / "regulatory_documents.csv", ["file_hash"], [])

    result = ingest_document_folder(doc_dir, engine=engine)

    assert result["status"] == "skipped_no_document"


@pytest.mark.parametrize("validation_status", ["INVALID", ""])
def test_invalid_manifest_rows_are_not_ingested(tmp_path, validation_status):
    engine = _create_db()
    doc_dir = tmp_path / "invalid"
    doc_dir.mkdir()
    _write_document_header(doc_dir, "doc_invalid", "i" * 64)
    _write_csv(
        doc_dir / "normalization_manifest.csv",
        ["source_record_id", "event_key", "validation_status"],
        [{"source_record_id": "rec_invalid", "event_key": "event_invalid", "validation_status": validation_status}],
    )
    _write_csv(
        doc_dir / "raw_source_records.csv",
        ["source_record_id", "page_number", "raw_json"],
        [{"source_record_id": "rec_invalid", "page_number": "1", "raw_json": "{\"bad\": true}"}],
    )
    _write_csv(
        doc_dir / "regulatory_events.csv",
        ["event_key", "source_record_id", "event_type", "scope"],
        [{"event_key": "event_invalid", "source_record_id": "rec_invalid", "event_type": "BANNED", "scope": "PRODUCT"}],
    )
    _write_csv(doc_dir / "organizations.csv", ["organization_key", "organization_name"], [{"organization_key": "org_invalid", "organization_name": "Invalid Org"}])
    _write_csv(doc_dir / "ingredients.csv", ["ingredient_key", "ingredient_name"], [{"ingredient_key": "ing_invalid", "ingredient_name": "Invalid Ingredient"}])
    _write_csv(doc_dir / "products.csv", ["product_key", "product_name", "product_category"], [{"product_key": "prod_invalid", "product_name": "Invalid Product", "product_category": "DRUG"}])
    _write_csv(doc_dir / "product_ingredients.csv", ["product_key", "ingredient_key"], [{"product_key": "prod_invalid", "ingredient_key": "ing_invalid"}])
    _write_csv(doc_dir / "product_organizations.csv", ["product_key", "organization_key", "role"], [{"product_key": "prod_invalid", "organization_key": "org_invalid", "role": "MANUFACTURER"}])
    _write_csv(doc_dir / "batches.csv", ["batch_key", "product_key", "organization_key", "batch_number"], [{"batch_key": "batch_invalid", "product_key": "prod_invalid", "organization_key": "org_invalid", "batch_number": "B1"}])

    result = ingest_document_folder(doc_dir, engine=engine)

    assert result["status"] == "inserted"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM raw_source_records").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_events").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM ingredients").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM staging_key_map").fetchone()[0] == 0


def test_duplicate_source_identity_skips_different_file_hash(tmp_path):
    engine = _create_db()
    doc_dir = tmp_path / "source-duplicate"
    doc_dir.mkdir()
    _write_document_header(doc_dir, "same_source_id", "a" * 64)
    first = ingest_document_folder(doc_dir, engine=engine)

    _write_document_header(doc_dir, "same_source_id", "b" * 64)
    second = ingest_document_folder(doc_dir, engine=engine)

    assert first["status"] == "inserted"
    assert second["status"] == "skipped_duplicate_document"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0] == 1


def test_invalid_json_field_is_skipped_without_failing_document(tmp_path):
    engine = _create_db()
    doc_dir = tmp_path / "invalid-json"
    doc_dir.mkdir()
    _write_document_header(doc_dir, "doc_invalid_json", "j" * 64)
    _write_csv(
        doc_dir / "raw_source_records.csv",
        ["source_record_id", "page_number", "source_text", "raw_json"],
        [{"source_record_id": "rec_invalid_json", "page_number": "1", "source_text": "source remains useful", "raw_json": "{not valid json"}],
    )

    result = ingest_document_folder(doc_dir, engine=engine)

    assert result["status"] == "inserted"
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT source_text, raw_json FROM raw_source_records").fetchone()
    assert row == ("source remains useful", None)


def test_bom_encoded_csv_headers_are_read(tmp_path):
    engine = _create_db()
    doc_dir = tmp_path / "bom"
    doc_dir.mkdir()
    _write_document_header(doc_dir, "doc_bom", "b" * 64, encoding="utf-8-sig")

    result = ingest_document_folder(doc_dir, engine=engine)

    assert result["status"] == "inserted"
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT source_organization, source_document_id FROM regulatory_documents").fetchone()
    assert row == ("CDSCO", "doc_bom")


def test_staging_key_is_reused_across_documents(tmp_path):
    engine = _create_db()
    shared_key = "shared_org_key"
    for index in (1, 2):
        doc_dir = tmp_path / f"document-{index}"
        doc_dir.mkdir()
        _write_document_header(doc_dir, f"doc_shared_{index}", f"{index}" * 64)
        _write_csv(
            doc_dir / "organizations.csv",
            ["organization_key", "organization_name", "country"],
            [{"organization_key": shared_key, "organization_name": "Shared Pharma", "country": "India"}],
        )
        result = ingest_document_folder(doc_dir, engine=engine)
        assert result["status"] == "inserted"

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0] == 2
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM organizations WHERE organization_key = 'shared_org_key'").fetchone()[0] == 1
        mapping = conn.exec_driver_sql(
            "SELECT organization_id FROM staging_key_map WHERE entity_type = 'organization' AND staging_key = 'shared_org_key'"
        ).fetchone()
        organization = conn.exec_driver_sql(
            "SELECT organization_id FROM organizations WHERE organization_key = 'shared_org_key'"
        ).fetchone()
    assert mapping == organization


def test_s3_prefix_ingest_groups_documents_and_obeys_limit(tmp_path, monkeypatch):
    engine = _create_db()
    object_keys = [
        "normalized/doc-a/regulatory_documents.csv",
        "normalized/doc-b/regulatory_documents.csv",
    ]

    class FakePaginator:
        def paginate(self, **kwargs):
            return [{"Contents": [{"Key": key} for key in object_keys]}]

    class FakeS3:
        def get_paginator(self, operation_name):
            assert operation_name == "list_objects_v2"
            return FakePaginator()

        def download_file(self, bucket, key, destination):
            document_name = key.split("/")[-2]
            _write_csv(
                Path(destination),
                ["source_organization", "source_document_id", "filename", "source_url", "file_hash", "document_type"],
                [{"source_organization": "CDSCO", "source_document_id": document_name, "filename": f"{document_name}.pdf", "source_url": "https://example.com", "file_hash": document_name * 32, "document_type": "UNKNOWN"}],
            )

    monkeypatch.setattr(append_ingest.boto3, "client", lambda *args, **kwargs: FakeS3())

    results = append_ingest.ingest_s3_prefix("bucket", "normalized", limit=1, engine=engine)

    assert len(results) == 1
    assert results[0]["s3_prefix"] == "normalized/doc-a"
    assert results[0]["inserted_counts"]["regulatory_documents"] == 1
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0] == 1


def test_scraper_status_moves_from_normalized_to_ingested_by_s3_key():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "documents",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("document_id", Integer, nullable=False),
        Column("source_key", String),
        Column("s3_object_key", String),
        Column("pdf_url", String),
        Column("status", String, nullable=False),
        Column("processing_stage", String),
        Column("updated_at", DateTime),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO documents (document_id, s3_object_key, status) VALUES (123, 'medicine-data-storage/source_files/alerts/123.pdf', 'downloaded')"
        )

    normalized = set_scraper_document_status(
        status="normalized",
        source_document_id="alerts/123.pdf",
        source_url="medicine-data-storage/source_files/alerts/123.pdf",
        engine=engine,
    )
    ingested = set_scraper_document_status(
        status="ingested",
        source_document_id="alerts/123.pdf",
        source_url="medicine-data-storage/source_files/alerts/123.pdf",
        engine=engine,
    )

    assert normalized["updated"] is True
    assert normalized["matched_by"] == "s3_object_key"
    assert ingested["updated"] is True
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT status, processing_stage FROM documents WHERE document_id = 123").fetchone()
    assert row == ("ingested", "ingested")


def test_foreign_key_failure_rolls_back_document_and_new_rows(tmp_path):
    engine = _create_db()
    doc_dir = tmp_path / "rollback"
    doc_dir.mkdir()
    _write_document_header(doc_dir, "doc_rollback", "r" * 64)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql(
            "INSERT INTO staging_key_map (entity_type, staging_key, product_id) "
            "VALUES ('product', 'prod_fk_failure', 999)"
        )
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    _write_csv(
        doc_dir / "organizations.csv",
        ["organization_key", "organization_name", "country"],
        [{"organization_key": "org_rollback", "organization_name": "Rollback Pharma", "country": "India"}],
    )
    _write_csv(doc_dir / "products.csv", ["product_key", "product_name", "product_category"], [{"product_key": "prod_fk_failure", "product_name": "Invalid mapped product", "product_category": "DRUG"}])
    _write_csv(
        doc_dir / "product_organizations.csv",
        ["product_key", "organization_key", "role"],
        [{"product_key": "prod_fk_failure", "organization_key": "org_rollback", "role": "MANUFACTURER"}],
    )

    with pytest.raises(IntegrityError):
        ingest_document_folder(doc_dir, engine=engine)

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM staging_key_map").fetchone()[0] == 1
