import io
import unittest
from unittest.mock import patch

from pdf_ingestion_system.extractor.extractor import (
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

        with patch("pdf_ingestion_system.extractor.extractor.pymupdf.open", return_value=FakePymupdfDoc()), \
             patch("pdf_ingestion_system.extractor.extractor.pdfplumber.open", return_value=FakePlumberDoc()):
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

        with patch("pdf_ingestion_system.extractor.extractor.pymupdf.open", return_value=FakePymupdfDoc()), \
             patch("pdf_ingestion_system.extractor.extractor.pdfplumber.open", return_value=FakePlumberDoc()), \
             patch("sys.stderr", new_callable=io.StringIO) as stderr:
            payload = _extract_document_from_bytes(
                b"%PDF-1.4",
                "source/example.pdf",
                "source",
                profiler_page_profile=[{"page": 1, "has_table": True}],
            )

        self.assertEqual(payload["pages"][0]["table_count"], 0)
        self.assertIn("WARN profiler/extractor mismatch", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
