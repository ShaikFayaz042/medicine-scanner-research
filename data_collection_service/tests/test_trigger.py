import re

from data_collection_service.scraper.trigger import (
    build_manifest,
    build_run_id,
    manifest_s3_key,
)


def test_build_run_id_matches_step_functions_name_format():
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", build_run_id())


def test_manifest_tracks_pdf_and_json_artifacts():
    documents = [
        {"s3_key": "source_files/example.pdf", "kind": "pdf"},
        {"s3_key": "source_files/example.json", "kind": "json"},
    ]

    manifest = build_manifest("run-123", documents)

    assert manifest["run_id"] == "run-123"
    assert manifest["has_pdfs"] is True
    assert manifest["has_json"] is True
    assert manifest["documents"] == documents


def test_manifest_key_is_scoped_to_run():
    assert manifest_s3_key("run-123").endswith(
        "/processed_files/runs/run-123/manifest.json"
    )