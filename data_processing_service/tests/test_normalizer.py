import csv
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch

from data_processing_service.normalizer import run as normalizer
from data_processing_service.normalizer import pipeline


def test_main_normalizes_scraper_nsq_aa_data_from_source_files():
    input_key = "medicine-data-storage/source_files/nsq/nsq_2026-08.json"
    payload = {
        "source": "cdsco_nsq",
        "record_type": "nsq",
        "reporting_period": "August 2026",
        "aaData": [{
            "str_product_name": "Example Paracetamol Tablets 500 mg",
            "str_batch_no": "B-123",
            "str_manufactured_by": "Example Pharma Ltd",
            "str_nsq_result": "Not of Standard Quality",
            "str_reporting_source": "State Drug Laboratory",
            "dt_reporting_month_year": "August 2026",
        }],
    }
    s3_client = Mock()
    s3_client.get_paginator.return_value.paginate.side_effect = lambda **kwargs: [{
        "Contents": ([{"Key": input_key}] if kwargs["Prefix"].endswith("/nsq") else [])
    }]
    s3_client.get_object.return_value = {
        "Body": io.BytesIO(json.dumps(payload).encode("utf-8"))
    }
    uploaded_files = {}

    def capture_upload(filename, bucket, key):
        uploaded_files[key] = Path(filename).read_text(encoding="utf-8")

    s3_client.upload_file.side_effect = capture_upload
    with (
        patch.object(normalizer.boto3, "client", return_value=s3_client),
        patch.object(
            normalizer,
            "set_scraper_document_status",
            return_value={"updated": True, "matched_by": "s3_object_key"},
        ) as update_status,
    ):
        result = normalizer.main([
            "--bucket", "input-bucket",
            "--prefix", "medicine-data-storage/processed_files/parsed_json",
            "--profiler-prefix", "medicine-data-storage/processed_files/profiler_output",
            "--nsq-prefix", "medicine-data-storage/source_files/nsq",
            "--region", "ap-south-1",
            "--s3-output-bucket", "output-bucket",
            "--s3-output-prefix", "normalized",
        ])

    raw_records_key = "normalized/nsq/nsq_2026-08/raw_source_records.csv"
    assert result == 0
    assert raw_records_key in uploaded_files
    raw_records = list(csv.DictReader(io.StringIO(uploaded_files[raw_records_key])))
    assert len(raw_records) == 1

    products_key = "normalized/nsq/nsq_2026-08/products.csv"
    products = list(csv.DictReader(io.StringIO(uploaded_files[products_key])))
    assert len(products) == 1
    assert products[0]["product_name"] == "Example Paracetamol Tablets 500 mg"

    regulatory_key = "normalized/nsq/nsq_2026-08/regulatory_documents.csv"
    regulatory_rows = list(csv.DictReader(io.StringIO(uploaded_files[regulatory_key])))
    assert regulatory_rows[0]["document_type"] == "NSQ_CDSCO"
    assert regulatory_rows[0]["source_url"] == input_key
    update_status.assert_called_once()
    assert update_status.call_args.kwargs["status"] == "normalized"
    assert update_status.call_args.kwargs["source_s3_key"] == input_key


def test_manifest_run_normalizes_only_parser_result_keys(monkeypatch):
    run_id = "run-1"
    parsed_key = (
        "medicine-data-storage/processed_files/runs/run-1/parsed_json/"
        "ipc/Drug_Safety_Alert_Feb_2026.json"
    )
    parser_result_key = "medicine-data-storage/processed_files/runs/run-1/results/parsed.json"
    s3_client = Mock()
    s3_client.get_object.side_effect = [
        {"Body": io.BytesIO(json.dumps({
            "schema_version": 1,
            "stage": "parser",
            "run_id": run_id,
            "output_keys": [parsed_key],
        }).encode("utf-8"))},
        {"Body": io.BytesIO(json.dumps({
            "run_id": run_id,
            "json_keys": [parsed_key],
        }).encode("utf-8"))},
    ]
    s3_client.get_paginator.side_effect = AssertionError("manifest run must not prefix-scan")
    seen = {}

    monkeypatch.setattr(normalizer.boto3, "client", lambda *_args, **_kwargs: s3_client)
    def fake_normalize(*args, **_kwargs):
        seen["key"] = args[3]
        return 0

    monkeypatch.setattr(normalizer, "_normalize_s3_file", fake_normalize)
    monkeypatch.setattr(normalizer, "write_result", lambda *args, **_kwargs: None)

    result = normalizer.main([
        "--bucket", "test-bucket",
        "--manifest-s3-key", "medicine-data-storage/processed_files/runs/run-1/manifest.json",
        "--run-id", run_id,
        "--s3-output-bucket", "output-bucket",
        "--s3-output-prefix", "normalized",
    ])

    assert result == 0
    assert any(
        call.kwargs["Key"] == parser_result_key
        for call in s3_client.get_object.call_args_list
    )
    assert not s3_client.get_paginator.called
    assert seen["key"] == parsed_key


def _manifest_normalizer_run(monkeypatch, manifest, status_result):
    run = "medicine-data-storage/processed_files/runs/run-1"
    nsq_key = "medicine-data-storage/source_files/nsq/nsq_2025-06.json"
    objects = {
        f"{run}/results/parsed.json": {"run_id": "run-1", "stage": "parser", "output_keys": []},
        f"{run}/manifest.json": manifest,
        nsq_key: {"source": "cdsco_nsq", "record_type": "nsq", "reporting_period": "2025-06",
                  "aaData": [{"str_product_name": "Paracetamol Tablets", "str_batch_no": "B-1"}]},
    }
    s3_client = Mock()
    s3_client.get_object.side_effect = lambda Bucket, Key: {"Body": io.BytesIO(json.dumps(objects[Key]).encode("utf-8"))}
    s3_client.get_paginator.side_effect = AssertionError("manifest run must not prefix-scan")
    uploads, results = [], []
    s3_client.upload_file.side_effect = lambda filename, bucket, key: uploads.append(key)
    monkeypatch.setattr(normalizer.boto3, "client", lambda *_args, **_kwargs: s3_client)
    monkeypatch.setattr(normalizer, "set_scraper_document_status", lambda **_kwargs: status_result)
    monkeypatch.setattr(normalizer, "write_result", lambda *args: results.append(args[4]))
    exit_code = normalizer.main([
        "--bucket", "b", "--manifest-s3-key", f"{run}/manifest.json", "--run-id", "run-1",
        "--s3-output-prefix", f"{run}/normalized",
    ])
    return exit_code, uploads, results[0]


def test_manifest_json_documents_from_the_scraper_are_normalized(monkeypatch):
    manifest = {"run_id": "run-1", "has_pdfs": False,
                "documents": [{"s3_key": "medicine-data-storage/source_files/nsq/nsq_2025-06.json", "kind": "json"}]}

    exit_code, uploads, result = _manifest_normalizer_run(monkeypatch, manifest, {"updated": True})

    assert exit_code == 0
    assert result["input_keys"] == ["medicine-data-storage/source_files/nsq/nsq_2025-06.json"]
    assert "medicine-data-storage/processed_files/runs/run-1/normalized/nsq/nsq_2025-06/products.csv" in uploads


def test_missing_scraper_row_is_reported_without_failing_the_document(monkeypatch):
    manifest = {"run_id": "run-1", "documents": [{"s3_key": "medicine-data-storage/source_files/nsq/nsq_2025-06.json", "kind": "json"}]}

    exit_code, uploads, result = _manifest_normalizer_run(monkeypatch, manifest, {"updated": False, "reason": "scraper document row not found"})

    assert exit_code == 0
    assert result["status"] == "success"
    assert len(uploads) == 10
    assert result["status_update_failures"] == [
        "medicine-data-storage/source_files/nsq/nsq_2025-06.json: scraper document row not found"
    ]


def test_document_type_unknown_is_replaced_with_supported_enum():
    assert pipeline._document_type({"document_type": "GENERAL REGULATORY DOCUMENT"}, "example.json") == "UNKNOWN"

def test_placeholder_batch_and_manufacturer_are_left_empty():
    record = {"S No": "1", "Name of Drugs/medical device/cosmetics": "Purport to contain Amoxycillin",
              "Batch No": "Not Specified", "Manufactured By": "Not mentioned", "Date of Expiry": "Not Specified"}
    kept = dict(record, **{"Batch No": "37", "Manufactured By": "M/s. Sundaram Surgical"})

    empty = pipeline._normalize_record("doc.pdf", "SPURIOUS", record, 0)
    real = pipeline._normalize_record("doc.pdf", "SPURIOUS", kept, 0)

    assert (empty["batch_number"], empty["batch_key"], empty["manufacturer_name"]) == ("", "", "")
    assert (real["batch_number"], real["manufacturer_name"]) == ("37", "M/s. Sundaram Surgical")
