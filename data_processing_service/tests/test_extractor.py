import io
import json
import unittest
from unittest.mock import Mock, patch

from data_processing_service.extractor import run as extractor
from data_processing_service.extractor.run import (
    _extract_document_from_bytes,
    _extract_table_rows_from_page,
    _flatten_table_rows,
    _is_valid_table_candidate,
    _is_valid_text_strategy_table,
)


class DummyPage:
    def __init__(self, default_tables=None, text_tables=None, mixed_h_tables=None, mixed_v_tables=None):
        self._tables_by_strategy = {
            None: default_tables or [],
            "default": default_tables or [],
            "text": text_tables or [],
            "mixed_h_text": mixed_h_tables or [],
            "mixed_v_text": mixed_v_tables or [],
        }

    def extract_tables(self, settings=None):
        strategy = {k: v for k, v in (settings or {}).items() if k.endswith("_strategy")}
        key = None if not strategy else tuple(sorted(strategy.items()))
        if key == (('horizontal_strategy', 'text'), ('vertical_strategy', 'text')):
            return self._tables_by_strategy["text"]
        if key == (('horizontal_strategy', 'text'), ('vertical_strategy', 'lines')):
            return self._tables_by_strategy["mixed_h_text"]
        if key == (('horizontal_strategy', 'lines'), ('vertical_strategy', 'text')):
            return self._tables_by_strategy["mixed_v_text"]
        return self._tables_by_strategy["default"]


class ExtractorTableDetectionTests(unittest.TestCase):
    def test_extract_table_rows_falls_back_to_text_strategy(self):
        page = DummyPage(default_tables=[], text_tables=[[
            ['Drug', 'Batch'],
            ['Ibuprofen', 'B-12'],
            ['Paracetamol', 'C-34'],
        ]])

        rows, strategy = _extract_table_rows_from_page(page)

        self.assertEqual(strategy, "text")
        self.assertEqual(rows, [[
            ['Drug', 'Batch'],
            ['Ibuprofen', 'B-12'],
            ['Paracetamol', 'C-34'],
        ]])

    def test_flatten_table_rows_keeps_table_boundaries(self):
        rows = [
            [['Drug', 'Batch'], ['Ibuprofen', 'B-12']],
            [['Reason', 'Status'], ['Theft', 'Notice']],
        ]

        flattened = _flatten_table_rows(rows)

        self.assertEqual(flattened[0]["table_index"], 0)
        self.assertEqual(flattened[0]["cells"], ['Drug', 'Batch'])
        self.assertEqual(flattened[2]["table_index"], 1)
        self.assertEqual(flattened[2]["cells"], ['Reason', 'Status'])

    def test_sparse_pdf_table_rows_are_not_rejected(self):
        rows = [
            ['', 'Sr. No.', '', '', 'Drugs Name', '', '', 'Notificatio', ''],
            ['', '', '', '', '', '', '', 'n No. &', ''],
            ['', '13.', '', '', 'Fixed dose combinations of Hydroxyquinoline group of drugs', '', '', 'Substituted', ''],
            ['', '', '', '', 'with any other drug except for preparations meant for', '', '', 'vide GSR NO.', ''],
        ]

        self.assertTrue(_is_valid_table_candidate(rows))

    def test_text_strategy_rejects_prose_like_tables(self):
        rows = [
            ['The committee reviewed the matter and issued a direction.', 'The text continues in a long sentence.'],
            ['This page is narrative prose with no clean tabular structure.', 'Further text continues across multiple lines.'],
            ['The last row is still prose and not a table.', 'No headers are present.'],
        ]

        self.assertFalse(_is_valid_text_strategy_table(rows))

    def test_text_strategy_accepts_real_tabular_rows(self):
        rows = [
            ['Drug Name', 'Batch No'],
            ['Paracetamol', 'AB1234'],
            ['Ibuprofen', 'CD5678'],
        ]

        self.assertTrue(_is_valid_text_strategy_table(rows))

    def test_extract_document_reports_table_counts_and_zero_pages(self):
        class FakePymupdfPage:
            def get_text(self, *_args, **_kwargs):
                return "drug warning text"

        class FakePymupdfDoc:
            metadata = {"title": "Example"}
            needs_pass = False

            def __init__(self):
                self.pages = [FakePymupdfPage(), FakePymupdfPage()]

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, index):
                return self.pages[index]

            def close(self):
                pass

        class FakePlumberPage:
            def extract_tables(self, settings=None):
                return []

        class FakePlumberDoc:
            def __init__(self):
                self.pages = [FakePlumberPage(), FakePlumberPage()]

            def close(self):
                pass

        with patch("data_processing_service.extractor.run.pymupdf.open", return_value=FakePymupdfDoc()), \
            patch("data_processing_service.extractor.run.pdfplumber.open", return_value=FakePlumberDoc()):
            payload = _extract_document_from_bytes(b"%PDF-1.4", "source/example.pdf", "source")

        self.assertEqual(payload["pages"][0]["table_count"], 0)
        self.assertEqual(payload["pages"][1]["table_count"], 0)
        self.assertEqual(payload["extraction_meta"]["pages_with_zero_tables"], [1, 2])
        self.assertEqual(
            payload["extraction_meta"]["table_strategies_used"],
            {"default": 0, "text": 0, "mixed_v": 0, "mixed_h": 0, "none": 2},
        )

    def test_extract_document_warns_on_profiler_extractor_mismatch(self):
        class FakePymupdfPage:
            def get_text(self, *_args, **_kwargs):
                return "drug warning text"

        class FakePymupdfDoc:
            metadata = {"title": "Mismatch"}
            needs_pass = False

            def __init__(self):
                self.pages = [FakePymupdfPage()]

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, index):
                return self.pages[index]

            def close(self):
                pass

        class FakePlumberPage:
            def extract_tables(self, settings=None):
                return []

        class FakePlumberDoc:
            def __init__(self):
                self.pages = [FakePlumberPage()]

            def close(self):
                pass

        with patch("data_processing_service.extractor.run.pymupdf.open", return_value=FakePymupdfDoc()), \
            patch("data_processing_service.extractor.run.pdfplumber.open", return_value=FakePlumberDoc()), \
            patch("sys.stderr", new_callable=io.StringIO) as stderr:
            payload = _extract_document_from_bytes(
                b"%PDF-1.4",
                "source/example.pdf",
                "source",
                profiler_page_profile=[{"page": 1, "has_table": True}],
            )

        self.assertEqual(payload["pages"][0]["table_count"], 0)
        self.assertIn("WARN profiler/extractor mismatch", stderr.getvalue())


def test_table_with_full_width_section_row_is_accepted():
    rows = [
        ["B. State Laboratories", "", "", "", "", "", "", ""],
        ["S.No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date", "Manufactured By", "NSQ Result", "Reported by"],
        ["1.", "Enrofloxacin Inj IP", "VT4072", "Jul-24", "Jun-26", "Alpha Laboratories", "Particulate Matter", "CFDL Jammu"],
    ]

    assert _is_valid_table_candidate(rows)
    page = DummyPage(default_tables=[rows], mixed_v_tables=[rows[1:]])
    assert _extract_table_rows_from_page(page) == ([rows], "default")


def _pdf_with_text(text: str) -> bytes:
    import pymupdf

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    return document.tobytes()


def test_garbled_text_layer_is_sent_to_ocr(monkeypatch):
    calls = []
    monkeypatch.setattr(extractor.page_ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(
        extractor.page_ocr,
        "ocr_page",
        lambda page, **_kwargs: calls.append(page) or {"text": "Batch No - C 2009", "lines": [], "table": [], "rotation": 0, "mean_score": 0.9},
    )
    garbled = "Batch No � C 2009 �� D/Mfg � 07/2012 �"
    monkeypatch.setattr(extractor, "_page_text", lambda _page: garbled)

    payload = _extract_document_from_bytes(_pdf_with_text("placeholder"), "src/alerts/old.pdf", "src")

    page = payload["pages"][0]
    assert calls and page["ocr"]["reason"] == "garbled_text_layer"
    assert page["text"] == "Batch No - C 2009"
    assert "�" in page["text_layer"]


def test_ocr_failure_is_reported_not_swallowed(monkeypatch, capsys):
    monkeypatch.setattr(extractor.page_ocr, "ocr_available", lambda: True)

    def broken_ocr(_page, **_kwargs):
        raise RuntimeError("model file missing")

    monkeypatch.setattr(extractor.page_ocr, "ocr_page", broken_ocr)
    monkeypatch.setattr(extractor, "_page_text", lambda _page: "�" * 40)
    payload = _extract_document_from_bytes(_pdf_with_text("placeholder"), "src/alerts/scan.pdf", "src")

    assert payload["pages"][0]["ocr_error"] == "RuntimeError: model file missing"
    assert payload["extraction_meta"]["ocr_failed_pages"] == 1
    assert "WARN OCR failed: src/alerts/scan.pdf page 1: model file missing" in capsys.readouterr().err


def test_unreadable_pdf_fails_the_document_instead_of_passing_as_empty():
    import pytest

    with pytest.raises(Exception):
        _extract_document_from_bytes(b"not a pdf", "src/alerts/broken.pdf", "src")


def test_output_key_is_named_after_the_pdf_not_its_title():
    s3_client = Mock()
    payload = {"pdf_title": "NSQ ALERT FOR THE MONTH OF MAY-2025"}

    first = extractor.write_json_to_s3(s3_client, "bucket", "src/alerts/12001_NSQ_ALERT.pdf", "src", "out", payload)
    second = extractor.write_json_to_s3(s3_client, "bucket", "src/alerts/12002_NSQ_ALERT.pdf", "src", "out", payload)

    assert first == "out/alerts/12001_NSQ_ALERT.json"
    assert second == "out/alerts/12002_NSQ_ALERT.json"


def test_extractor_uses_only_pdf_keys_from_manifest(monkeypatch):
    manifest_key = "medicine-data-storage/processed_files/runs/manual-test-001/manifest.json"
    input_key = "medicine-data-storage/source_files/ipc/Drug-Safety-Alert-February-20-2026.pdf"
    manifest = {
        "schema_version": 1,
        "run_id": "manual-test-001",
        "documents": [
            {"s3_key": input_key, "kind": "pdf", "source": "ipc_pvpi"},
            {"s3_key": "medicine-data-storage/source_files/alerts/other.pdf", "kind": "json"},
        ],
    }
    s3_client = Mock()
    s3_client.get_object.side_effect = [
        {"Body": io.BytesIO(json.dumps(manifest).encode("utf-8"))},
        {"Body": io.BytesIO(b"pdf-bytes")},
    ]
    s3_client.get_paginator.side_effect = AssertionError("manifest run must not prefix-scan")
    monkeypatch.setattr(extractor.boto3, "client", lambda *_args, **_kwargs: s3_client)
    monkeypatch.setattr(extractor, "get_document_metadata", lambda keys: {})
    monkeypatch.setattr(extractor, "_extract_document_from_bytes", lambda *_args: {"pdf_title": "Test"})
    monkeypatch.setattr(extractor, "write_json_to_s3", lambda *_args: "run-output/extracted.json")
    monkeypatch.setattr(extractor, "update_extracted_documents", lambda _keys: 1)
    written_results = []
    monkeypatch.setattr(extractor, "write_result", lambda *args: written_results.append(args))

    result = extractor.main([
        "--bucket", "test-bucket",
        "--region", "ap-south-1",
        "--manifest-s3-key", manifest_key,
        "--run-id", "manual-test-001",
        "--s3-output-bucket", "test-bucket",
        "--s3-output-prefix", "run-output",
    ])

    assert result == 0
    assert [call.kwargs["Key"] for call in s3_client.get_object.call_args_list] == [
        manifest_key,
        input_key,
    ]
    assert written_results[0][2:4] == ("manual-test-001", "extractor")
    assert written_results[0][4]["input_keys"] == [input_key]
    assert written_results[0][4]["output_keys"] == ["run-output/extracted.json"]



def test_fake_bold_text_printed_several_times_is_read_once():
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    for offset in (0, 0.25, 0.5, 0.75):  # how some gazettes draw bold headings
        page.insert_text((72 + offset, 72), "S.O. 4482(E).-Whereas", fontsize=11)
    page.insert_text((72, 100), "fixed dose combination of Metformin ER + Gliclazide MR", fontsize=11)
    page.insert_text((72, 128), "S.O. 4482(E) is cited twice on purpose", fontsize=11)

    text = extractor._page_text(pymupdf.open(stream=document.tobytes())[0])

    assert text.splitlines() == [
        "S.O. 4482(E).-Whereas",
        "fixed dose combination of Metformin ER + Gliclazide MR",
        "S.O. 4482(E) is cited twice on purpose",
    ]


def test_page_without_overprint_keeps_the_plain_text_layer():
    import pymupdf

    page = pymupdf.open(stream=_pdf_with_text("Batch No. AB1234  Exp 12/2025"))[0]

    assert extractor._without_overprint(page) is None
    assert extractor._page_text(page) == "Batch No. AB1234  Exp 12/2025"


if __name__ == "__main__":
    unittest.main()
