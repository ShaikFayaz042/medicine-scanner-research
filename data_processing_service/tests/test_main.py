from data_processing_service import main as pipeline


def _stub_stage(monkeypatch, stage_name, calls, result=0):
    def run(argv):
        calls.append((stage_name, argv))
        return result

    return run


def test_main_runs_pipeline_in_order_and_defaults_to_ingest_dry_run(monkeypatch):
    calls = []
    stages = {
        "extractor": _stub_stage(monkeypatch, "extract_main", calls),
        "classifier": _stub_stage(monkeypatch, "classify_main", calls),
        "parser": _stub_stage(monkeypatch, "parse_main", calls),
        "normalizer": _stub_stage(monkeypatch, "normalize_main", calls),
        "ingester": _stub_stage(monkeypatch, "ingest_main", calls),
    }
    monkeypatch.setattr(pipeline, "_load_stage_main", stages.__getitem__)

    result = pipeline.main([
        "--bucket", "test-bucket",
        "--region", "eu-west-1",
        "--source-prefix", "input/pdfs",
        "--limit", "2",
    ])

    assert result == 0
    assert [stage_name for stage_name, _ in calls] == [
        "extract_main", "classify_main", "parse_main", "normalize_main", "ingest_main",
    ]
    assert "--s3-output-prefix" in calls[0][1]
    assert "input/pdfs" in calls[0][1]
    assert "input/pdfs/extracted_json" not in calls[0][1]
    assert "--classifier-csv-key" in calls[2][1]
    assert calls[-1][1][-1] == "--dry-run"


def test_main_commit_mode_and_custom_prefixes(monkeypatch):
    calls = []
    stages = {
        "extractor": _stub_stage(monkeypatch, "extract_main", calls),
        "classifier": _stub_stage(monkeypatch, "classify_main", calls),
        "parser": _stub_stage(monkeypatch, "parse_main", calls),
        "normalizer": _stub_stage(monkeypatch, "normalize_main", calls),
        "ingester": _stub_stage(monkeypatch, "ingest_main", calls),
    }
    monkeypatch.setattr(pipeline, "_load_stage_main", stages.__getitem__)

    result = pipeline.main([
        "--bucket", "test-bucket",
        "--source-prefix", "source",
        "--extracted-prefix", "custom/extracted",
        "--normalized-prefix", "custom/normalized",
        "--commit",
    ])

    assert result == 0
    assert "custom/extracted" in calls[0][1]
    assert "custom/normalized" in calls[-1][1]
    assert "--dry-run" not in calls[-1][1]


def test_main_stops_after_a_failed_stage(monkeypatch):
    calls = []
    stages = {
        "extractor": _stub_stage(monkeypatch, "extract_main", calls, result=1),
        "classifier": _stub_stage(monkeypatch, "classify_main", calls),
        "parser": _stub_stage(monkeypatch, "parse_main", calls),
        "normalizer": _stub_stage(monkeypatch, "normalize_main", calls),
        "ingester": _stub_stage(monkeypatch, "ingest_main", calls),
    }
    monkeypatch.setattr(pipeline, "_load_stage_main", stages.__getitem__)

    result = pipeline.main(["--bucket", "test-bucket"])

    assert result == 1
    assert [stage_name for stage_name, _ in calls] == ["extract_main"]


def test_stage_dispatch_bridges_environment_to_args(monkeypatch):
    calls = []
    monkeypatch.setenv("STAGE", "extractor")
    monkeypatch.setenv("PDF_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("PDF_S3_PREFIX", "source/files")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("PDF_LIMIT", "3")
    monkeypatch.setenv("SQS_MESSAGE_BODY", '{"s3_key":"source/files/example.pdf"}')
    monkeypatch.setattr(pipeline.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline,
        "_load_stage_main",
        lambda stage: lambda args: calls.append((stage, args)) or 0,
    )

    assert pipeline.main([]) == 0
    stage, args = calls[0]
    assert stage == "extractor"
    assert args == [
        "--bucket", "test-bucket",
        "--prefix", "source/files",
        "--region", "eu-west-1",
        "--limit", "3",
        "--doc-id", "source/files/example.pdf",
    ]


def test_stage_dispatch_prefers_explicit_cli_args(monkeypatch):
    calls = []
    monkeypatch.setenv("STAGE", "parser")
    monkeypatch.setenv("PDF_S3_BUCKET", "env-bucket")
    monkeypatch.setattr(pipeline.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline,
        "_load_stage_main",
        lambda stage: lambda args: calls.append((stage, args)) or 0,
    )

    assert pipeline.main(["--bucket", "cli-bucket"]) == 0
    assert calls == [("parser", ["--bucket", "cli-bucket"])]


def test_stage_dispatch_includes_manifest_metadata(monkeypatch):
    calls = []
    monkeypatch.delenv("PDF_LIMIT", raising=False)
    monkeypatch.delenv("AWS_S3_OUTPUT_BUCKET", raising=False)
    monkeypatch.delenv("AWS_S3_OUTPUT_PREFIX", raising=False)
    monkeypatch.setenv("STAGE", "extractor")
    monkeypatch.setenv("PDF_S3_BUCKET", "env-bucket")
    monkeypatch.setenv("PDF_S3_PREFIX", "source/files")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("RUN_ID", "run-42")
    monkeypatch.setenv(
        "MANIFEST_S3_KEY",
        "medicine-data-storage/processed_files/runs/run-42/manifest.json",
    )
    monkeypatch.setattr(pipeline.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline,
        "_load_stage_main",
        lambda stage: lambda args: calls.append((stage, args)) or 0,
    )

    assert pipeline.main([]) == 0
    assert calls == [(
        "extractor",
        [
            "--bucket", "env-bucket",
            "--prefix", "source/files",
            "--region", "eu-west-1",
            "--run-id", "run-42",
            "--manifest-s3-key", "medicine-data-storage/processed_files/runs/run-42/manifest.json",
        ],
    )]