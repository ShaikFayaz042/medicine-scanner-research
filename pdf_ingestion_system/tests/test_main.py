from pdf_ingestion_system import main as pipeline


def _stub_stage(monkeypatch, stage_name, calls, result=0):
    def run(argv):
        calls.append((stage_name, argv))
        return result

    monkeypatch.setattr(pipeline, stage_name, run)


def test_main_runs_pipeline_in_order_and_defaults_to_ingest_dry_run(monkeypatch):
    calls = []
    for stage_name in ("extract_main", "classify_main", "parse_main", "normalize_main", "ingest_main"):
        _stub_stage(monkeypatch, stage_name, calls)

    result = pipeline.main([
        "--bucket", "test-bucket",
        "--region", "eu-west-1",
        "--source-prefix", "input/pdfs",
        "--limit", "2",
    ])

    assert result == 0
    assert [stage_name for stage_name, _ in calls] == [
        "extract_main",
        "classify_main",
        "parse_main",
        "normalize_main",
        "ingest_main",
    ]
    assert "--s3-output-prefix" in calls[0][1]
    assert "input/pdfs" in calls[0][1]
    assert "input/pdfs/extracted_json" not in calls[0][1]
    assert "--classifier-csv-key" in calls[2][1]
    assert calls[-1][1][-1] == "--dry-run"


def test_main_commit_mode_and_custom_prefixes(monkeypatch):
    calls = []
    for stage_name in ("extract_main", "classify_main", "parse_main", "normalize_main", "ingest_main"):
        _stub_stage(monkeypatch, stage_name, calls)

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
    _stub_stage(monkeypatch, "extract_main", calls, result=1)
    _stub_stage(monkeypatch, "classify_main", calls)
    _stub_stage(monkeypatch, "parse_main", calls)
    _stub_stage(monkeypatch, "normalize_main", calls)
    _stub_stage(monkeypatch, "ingest_main", calls)

    result = pipeline.main(["--bucket", "test-bucket"])

    assert result == 1
    assert [stage_name for stage_name, _ in calls] == ["extract_main"]