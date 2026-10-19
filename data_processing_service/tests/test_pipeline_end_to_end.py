"""Parser -> normalizer -> ingester on realistic documents, against a database with the real CHECK constraints."""

import csv
import json

import pytest

import data_processing_service.ingester.run as ingester
from data_processing_service.normalizer import pipeline
from data_processing_service.parser import run as parser
from data_processing_service.tests.test_ingester import _create_db


@pytest.fixture(autouse=True)
def no_scraper_db(monkeypatch):
    monkeypatch.setattr(ingester, "set_scraper_document_status", lambda **_kwargs: {"updated": True})


def _extracted(title, header_rows, data_rows, source="cdsco_alerts", release_date="2025-Jul-18"):
    rows = [{"cells": row, "table_index": 0} for row in [*header_rows, *data_rows]]
    return {
        "doc_id": f"alerts/{title[:12]}.pdf",
        "s3_object_key": f"medicine-data-storage/source_files/alerts/{title[:12]}.pdf",
        "pdf_title": title,
        "pages": [{"page": 1, "text": title, "tables": rows}],
        "tables": [{"page": 1, "cells": rows}],
        "scraper_metadata": {"title": title, "source": source, "release_date": release_date},
    }


NSQ_HEADER = [["S.No", "Product/Drug Name", "Batch No.", "Date of", "", "Manufactured By", "NSQ Result", "Reported by"],
              ["", "", "", "Manufacture", "Expiry", "", "", ""]]
NSQ_ROWS = [
    ["1.", "Co-trimoxazole Oral Suspension IP", "CTS1187", "03/2024", "02/2026", "M/s. PQR Healthcare Pvt. Ltd., Ahmedabad", "Assay", "CDL, Kolkata"],
    ["2.", "Paracetamol Tablets IP 500 mg", "PCT2401", "Jul-24", "Jun-26", "M/s. XYZ Pharma Ltd., Baddi", "Dissolution", "CDL, Kolkata"],
]


def _normalize(tmp_path, structured):
    source = tmp_path / "parsed.json"
    source.write_text(json.dumps(structured), encoding="utf-8")
    out = tmp_path / "staging"
    assert pipeline.run_pipeline(str(source), str(out)) == 0
    return out


def _rows(folder, name):
    with (folder / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_nsq_alert_flows_into_every_table(tmp_path):
    structured = parser._process_single_payload(_extracted("CDSCO NSQ ALERT FOR THE MONTH OF June 2025", NSQ_HEADER, NSQ_ROWS))
    staging = _normalize(tmp_path, structured)
    engine = _create_db()

    result = ingester.ingest_document_folder(staging, engine=engine, dry_run=False)

    assert result["status"] == "inserted"
    counts = result["inserted_counts"]
    assert (counts["regulatory_documents"], counts["products"], counts["batches"], counts["regulatory_events"]) == (1, 2, 2, 2)
    assert counts["organizations"] == 3  # two manufacturers and the reporting laboratory
    with engine.connect() as connection:
        document = connection.exec_driver_sql(
            "SELECT document_title, publication_date, document_type FROM regulatory_documents").one()
        products = dict(connection.exec_driver_sql("SELECT product_name, normalized_name FROM products").all())
        batches = connection.exec_driver_sql(
            "SELECT batch_number, manufacturing_date, expiry_date FROM batches ORDER BY batch_number").all()
        events = connection.exec_driver_sql(
            "SELECT event_type, event_date, scope, reporting_organization_id IS NOT NULL FROM regulatory_events").all()
    assert document[0] == "CDSCO NSQ ALERT FOR THE MONTH OF June 2025"
    assert str(document[1]) == "2025-07-18"
    assert document[2] == "NSQ_CDSCO"
    assert products["Co-trimoxazole Oral Suspension IP"] == "co trimoxazole oral suspension ip"
    assert [(row[0], str(row[1]), str(row[2])) for row in batches] == [
        ("CTS1187", "2024-03-01", "2026-02-01"),
        ("PCT2401", "2024-07-01", "2026-06-01"),
    ]
    assert {(row[0], str(row[1]), row[2], row[3]) for row in events} == {("NSQ", "2025-07-18", "BATCH", 1)}


def test_reingesting_the_same_document_inserts_nothing(tmp_path):
    staging = _normalize(tmp_path, parser._process_single_payload(
        _extracted("CDSCO NSQ ALERT FOR THE MONTH OF June 2025", NSQ_HEADER, NSQ_ROWS)))
    engine = _create_db()
    ingester.ingest_document_folder(staging, engine=engine, dry_run=False)

    again = ingester.ingest_document_folder(staging, engine=engine, dry_run=False)

    assert again["status"] == "skipped_duplicate_document"


def test_spurious_list_uses_spurious_types_and_skips_placeholder_manufacturer(tmp_path):
    header = [["S.No.", "Name of Drugs/medical device/cosmetics", "Batch No.", "Manufactured By", "Reason for failure"]]
    rows = [["1.", "Cefixime Tablets IP (TAXIM-O 200 TABLETS)", "24460967", "Under Investigation", "Identification"]]
    staging = _normalize(tmp_path, parser._process_single_payload(
        _extracted("List of spurious Drugs for the month of June-2025", header, rows)))

    assert _rows(staging, "regulatory_documents.csv")[0]["document_type"] == "SPURIOUS"
    assert _rows(staging, "regulatory_events.csv")[0]["event_type"] == "SPURIOUS"
    assert _rows(staging, "organizations.csv") == []
    assert ingester.ingest_document_folder(staging, engine=_create_db())["status"] == "inserted"


def test_pvpi_alert_keeps_the_suspected_drug(tmp_path):
    structured = {
        "document_id": "ipc/alert.pdf", "pdf_path": "src/ipc/alert.pdf", "title": "Drug Safety Alert",
        "document_type": "Doc 2: List of Drugs Safety Alerts issued by PvPI",
        "document_metadata": {"issuing_authority": "Indian Pharmacopoeia Commission", "date_of_issue": "27.07.2026"},
        "records": [{"S No": "1", "Suspected Drugs": "Ceftriaxone", "Indication(s)": "Infections", "Adverse Drug Reactions": "DRESS syndrome"}],
    }
    staging = _normalize(tmp_path, structured)

    event = _rows(staging, "regulatory_events.csv")[0]
    assert _rows(staging, "products.csv")[0]["product_name"] == "Ceftriaxone"
    assert (event["event_type"], event["event_date"], event["reason"]) == ("ADR", "2026-07-27", "DRESS syndrome")
    assert _rows(staging, "normalization_manifest.csv")[0]["validation_status"] == "VALID"


def test_notice_without_products_becomes_a_document_level_event(tmp_path):
    structured = {
        "document_id": "fdc/circular.pdf", "pdf_path": "src/fdc/circular.pdf", "title": "Prohibition of 80 FDCs",
        "document_type": "Doc 1: Banned Drugs", "release_date": "2019-Jan-22",
        "records": [{"S No": "1", "Subject": "Prohibition of 80 Fixed Dose Combinations", "Notification No. & Date": "S.O. 180(E) to S.O. 259(E)"}],
    }
    staging = _normalize(tmp_path, structured)
    engine = _create_db()

    result = ingester.ingest_document_folder(staging, engine=engine, dry_run=False)

    assert result["inserted_counts"]["regulatory_events"] == 1
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT event_type, scope, legal_status FROM regulatory_events").one() == (
            "BANNED", "DOCUMENT", "S.O. 180(E) to S.O. 259(E)")


def test_classifier_review_flag_is_carried_into_the_manifest(tmp_path):
    structured = parser._process_single_payload(_extracted("CDSCO NSQ ALERT FOR THE MONTH OF June 2025", NSQ_HEADER, NSQ_ROWS[:1]))
    structured["classifier_review"] = {"bucket": "context-only", "reasons": ["weak_event_signal"]}

    row = _rows(_normalize(tmp_path, structured), "normalization_manifest.csv")[0]

    assert row["validation_status"] == "VALID"
    assert row["review_reason"] == "classifier_review:weak_event_signal"


@pytest.mark.parametrize("number", range(1, 18))
def test_every_parser_document_type_maps_to_an_allowed_value(number):
    allowed = {"BANNED_DRUGS", "PVPI_ADR", "NSQ_STATE", "SPURIOUS", "NSQ_CDSCO", "LEGACY_CDSCO",
               "MEDICAL_DEVICE", "APPROVED_DRUGS", "NOC_IMPORT_FDC", "MIXED_ALERT", "UNKNOWN"}
    doc_type = parser.DOCUMENT_TYPES[f"Doc {number}"][0]

    assert pipeline._document_type({"document_type": doc_type}, "x.json") in allowed


@pytest.mark.parametrize(
    "raw, expected",
    [("2025-Jul-18", "2025-07-18"), ("01-12-2023", "2023-12-01"), ("07/2023.", "2023-07-01"), ("Jul-24", "2024-07-01"),
     ("Feb.2023", "2023-02-01"), ("Sep.2026", "2026-09-01"), ("12-2024", "2024-12-01"), ("06.06.2024", "2024-06-06"),
     ("August 2026", "2026-08-01"), ("22nd May, 2025", "2025-05-22"), ("2025-06", "2025-06-01"), ("Under Investigation", "Under Investigation")],
)
def test_dates_are_normalized_to_iso(raw, expected):
    assert pipeline._date_value(raw) == expected


def test_missing_product_and_action_is_not_marked_valid(tmp_path):
    structured = {"document_id": "x.pdf", "pdf_path": "x.pdf", "document_type": "Doc 5: CDSCO Drug Alerts", "records": [{"S No": "1"}]}

    row = _rows(_normalize(tmp_path, structured), "normalization_manifest.csv")[0]

    assert (row["validation_status"], row["review_reason"]) == ("NEEDS_REVIEW", "missing_product_name")
