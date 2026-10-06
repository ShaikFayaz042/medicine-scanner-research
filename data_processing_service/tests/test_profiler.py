import csv
import io
from unittest.mock import patch

from data_processing_service.profiler import run as profiler


def test_profile_s3_json_object(fake_s3_client):
    fake_s3_client.get_object.return_value = {
        "Body": io.BytesIO(b'{"records": [{"name": "Example"}]}')
    }

    row = profiler.profile_s3_object(
        fake_s3_client,
        "test-bucket",
        "source/example.json",
        "source",
    )

    assert row["status"] == "ok"
    assert row["json_root_type"] == "object"
    assert row["json_record_count"] == 1
    assert row["structure_classification"] == "object-with-record-arrays"


def test_main_writes_report_locally_without_s3_upload(fake_s3_client, tmp_path):
    fake_s3_client.get_paginator.return_value.paginate.return_value = [{
        "Contents": [{"Key": "source/example.json"}]
    }]
    fake_s3_client.get_object.return_value = {
        "Body": io.BytesIO(b'{"records": [{"name": "Example"}]}')
    }
    output_path = tmp_path / "profiles.csv"

    with (
        patch.object(profiler.boto3, "client", return_value=fake_s3_client),
        patch.object(profiler, "update_profiled_documents", return_value=(1, 0, {})),
    ):
        assert profiler.main([
            "--bucket", "test-bucket",
            "--prefix", "source",
            "--output", str(output_path),
        ]) == 0

    assert output_path.is_file()
    with output_path.open(newline="", encoding="utf-8") as report:
        rows = list(csv.DictReader(report))
    assert len(rows) == 1
    fake_s3_client.upload_file.assert_not_called()
