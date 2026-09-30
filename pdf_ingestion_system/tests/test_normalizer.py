import csv
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch

from pdf_ingestion_system.normalizer import normalizer


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