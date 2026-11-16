from __future__ import annotations

import hashlib

import pymupdf


def test_main_runs_manifest_profiler_extractor_and_context(tmp_path, monkeypatch, capsys):
    import main

    monkeypatch.setenv("IDP_DATA_DIR", str(tmp_path / "data"))
    pdf_path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 80), "Product information", fontsize=12)
    page.insert_text((50, 120), "This is a representative digital PDF page.", fontsize=12)
    document.save(pdf_path)
    document.close()
    monkeypatch.setattr("sys.argv", ["main.py", str(pdf_path)])

    assert main.main() == 0

    output = capsys.readouterr().out
    doc_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert "classification context:" in output
    assert "document_manifest.json" in output
    assert "profile.json" in output
    assert "02_extraction\\index.json" in output
    assert "classification_context.json" in output
    root = tmp_path / "data" / "artifacts" / doc_id
    assert (root / "00_manifest" / "document_manifest.json").is_file()
    assert (root / "01_profiler" / "profile.json").is_file()
    assert (root / "02_extraction" / "index.json").is_file()
    assert (root / "02_extraction" / "batches" / "b0000.json").is_file()
    assert (root / "02_extraction" / "markdown" / "p001.md").is_file()
    assert (
        root / "03_classification_context" / "classification_context.json"
    ).is_file()


def test_main_persists_quality_for_empty_pdf_context(tmp_path, monkeypatch, capsys):
    import hashlib

    import main
    from idp.schemas.classification_context import ClassificationContext
    from idp.storage import artifacts

    monkeypatch.setenv("IDP_DATA_DIR", str(tmp_path / "data"))
    pdf_path = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(pdf_path)
    document.close()
    monkeypatch.setattr("sys.argv", ["main.py", str(pdf_path)])

    assert main.main() == 1

    doc_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    context = artifacts.load(
        "03_classification_context/classification_context", doc_id, ClassificationContext,
    )
    assert context is not None
    assert not context.quality.has_classifiable_content
    assert "no_classifiable_content" in context.quality.warnings
    assert "page_1:ocr_no_classifiable_content" not in context.quality.warnings
    assert "no_classifiable_content" in capsys.readouterr().out
