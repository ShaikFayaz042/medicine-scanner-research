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
        key = None if not settings else tuple(sorted((k, v) for k, v in settings.items()))
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


if __name__ == "__main__":
    unittest.main()
