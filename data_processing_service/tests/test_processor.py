import io
import json

from data_processing_service.processor import run as processor
from data_processing_service.shared.manifest import manifest_key, result_key, write_result


class FakeS3Client:
    def __init__(self, manifest):
        self.manifest = manifest
        self.puts = []

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(json.dumps(self.manifest).encode("utf-8"))}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def test_manifest_and_result_keys_use_run_scoped_prefix():
    assert manifest_key("run-7") == (
        "medicine-data-storage/processed_files/runs/run-7/manifest.json"
    )
    assert result_key("run-7", "extractor") == (
        "medicine-data-storage/processed_files/runs/run-7/results/extracted.json"
    )


def test_write_result_writes_separate_stage_object():
    client = FakeS3Client({})

    key = write_result(client, "bucket", "run-7", "parser", {"status": "success"})

    assert key.endswith("/runs/run-7/results/parsed.json")
    assert client.puts[0]["Key"] == key
    assert json.loads(client.puts[0]["Body"]) == {"status": "success"}


def test_processor_reads_manifest_and_runs_stages_in_order(monkeypatch):
    client = FakeS3Client({
        "run_id": "run-7",
        "extracted_prefix": "custom/extracted",
        "parsed_prefix": "global/parsed_json",
        "normalized_prefix": "global/normalized",
    })
    calls = []
    monkeypatch.setattr(processor.boto3, "client", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(
        processor,
        "_stage_main",
        lambda stage: lambda argv: calls.append((stage, argv)) or 0,
    )

    assert processor.main(["--bucket", "bucket", "--manifest-s3-key", "input/manifest.json"]) == 0

    assert [stage for stage, _ in calls] == ["parser", "normalizer", "ingester"]
    assert "custom/extracted" in calls[0][1]
    assert "medicine-data-storage/processed_files/runs/run-7/parsed_json" in calls[0][1]
    assert "medicine-data-storage/processed_files/runs/run-7/normalized" in calls[1][1]
    assert "global/parsed_json" not in calls[0][1]
    assert "global/normalized" not in calls[1][1]
    assert "--dry-run" in calls[2][1]
    assert client.puts[0]["Key"] == result_key("run-7", "processor")
    assert client.puts[0]["Key"] != "input/manifest.json"
    processor_result = json.loads(client.puts[0]["Body"])
    assert processor_result["output_keys"] == [
        "medicine-data-storage/processed_files/runs/run-7/parsed_json/",
        "medicine-data-storage/processed_files/runs/run-7/normalized/",
    ]


def test_processor_stops_on_first_failed_stage(monkeypatch):
    client = FakeS3Client({"run_id": "run-8"})
    calls = []
    monkeypatch.setattr(processor.boto3, "client", lambda *_args, **_kwargs: client)

    def stage_main(stage):
        def run(_argv):
            calls.append(stage)
            return 4 if stage == "normalizer" else 0
        return run

    monkeypatch.setattr(processor, "_stage_main", stage_main)

    assert processor.main(["--bucket", "bucket", "--run-id", "run-8"]) == 4

    assert calls == ["parser", "normalizer"]
    processor_result = json.loads(client.puts[0]["Body"])
    assert processor_result["status"] == "failure"
    assert processor_result["error"] == "normalizer exited with status 4"