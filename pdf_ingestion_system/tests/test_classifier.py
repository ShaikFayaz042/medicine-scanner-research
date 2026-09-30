"""Local regression tests for the S3-backed classifier adapter."""

import io
import json
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from pdf_ingestion_system.classifier import classifier
from pdf_ingestion_system.classifier.classifier import (
    _apply_classifier,
    _s3_output_key_for,
    main,
    write_classifier_json_to_s3,
)
from pdf_ingestion_system.classifier.classifier_payload import (
    language_text_from_payload,
    normalize_extracted_payload,
)
from pdf_ingestion_system.classifier.classifier_schema import (
    _has_event_context,
    complete_classifier_fields,
)
from pdf_ingestion_system.classifier.driver import (
    _detect_table_headers,
    classify_document,
    load_medicine_lexicons,
)


class S3ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "doc_id": "alerts/example.pdf",
            "source_name": "alerts",
            "pdf_title": "Example alert",
            "s3_object_key": "source_files/alerts/example.pdf",
            "pages": [{
                "page": 1,
                "text": "",
                "tables": [
                    {"cells": ["Drug Name", "Batch No"]},
                    {"cells": ["Paracetamol", "AB1234"]},
                ],
            }],
            "tables": [{
                "page": 1,
                "cells": [
                    {"cells": ["Drug Name", "Batch No"]},
                    {"cells": ["Paracetamol", "AB1234"]},
                ],
            }],
            "extraction_meta": {"text_pages": 0, "ocr_pages": 1},
        }

    def test_local_medicine_lexicon_is_loaded_and_used(self):
        products, ingredients = load_medicine_lexicons()
        self.assertGreater(len(products), 0)
        self.assertEqual(ingredients, [])

        verdict = classify_document({
            "doc_id": "alerts/lexicon-test.pdf",
            "source_name": "alerts",
            "pages": [],
            "tables": [{
                "page": 1,
                "cells": [["Drug Name", "Batch No"], [products[0], "AB123"]],
            }],
        }, products, ingredients)

        self.assertEqual(verdict["deterministic"]["rule_matched"], "D2")

    def test_extractor_table_shape_is_normalized_and_included_in_text(self):
        normalized = normalize_extracted_payload(self.payload)

        self.assertEqual(
            normalized["tables"][0]["cells"],
            [["Drug Name", "Batch No"], ["Paracetamol", "AB1234"]],
        )
        self.assertIn("Paracetamol", language_text_from_payload(normalized))

    def test_table_classification_uses_real_extractor_shape(self):
        verdict = _apply_classifier(self.payload, ["Paracetamol"], [])

        self.assertEqual(verdict["bucket"], "event-bearing")
        self.assertEqual(verdict["deterministic"]["rule_matched"], "D2")
        self.assertEqual(verdict["deterministic"]["table_drug_matches"], 1)
        self.assertFalse(verdict["ocr_pending"])
        self.assertGreater(verdict["topical_score"], 0)
        self.assertTrue(verdict["score_band"])

    def test_weak_manufacturer_only_signal_is_deferred(self):
        verdict = {
            "bucket": "event-bearing",
            "bucket_reason": "deterministic_event_signal",
            "is_relevant": True,
            "needs_review": False,
            "needs_review_reasons": [],
            "deterministic": {
                "rule_matched": "D4",
                "paragraph_manufacturer_matches": 97,
                "paragraph_batch_matches": 0,
            },
        }

        completed = complete_classifier_fields(
            verdict, "Paracetamol named in a BA/BE centre directory."
        )

        self.assertEqual(completed["bucket"], "context-only")

    def test_explicit_pvpi_adr_alert_is_event_bearing(self):
        verdict = {
            "bucket": "unimportant",
            "deterministic": {"rule_matched": "D6"},
        }

        completed = complete_classifier_fields(
            verdict,
            "Drug Safety Alert: PvPI reports an ADR signal for a medicine.",
        )

        self.assertEqual(completed["bucket"], "event-bearing")
        self.assertEqual(completed["deterministic"]["rule_matched"], "D4")

    def test_event_terms_use_word_boundaries(self):
        self.assertFalse(_has_event_context("This document was abandoned."))
        self.assertFalse(_has_event_context("The panel unbanned nothing."))
        self.assertFalse(_has_event_context("The bannedlist was circulated."))
        self.assertTrue(_has_event_context("The drug is banned under Section 26A."))
        self.assertFalse(_has_event_context("PVPI published an administrative notice."))
        self.assertFalse(_has_event_context("The ADR form was updated."))
        self.assertTrue(_has_event_context("PvPI reported an ADR signal."))

    def test_fdc_event_term_requires_action_context(self):
        self.assertFalse(_has_event_context("Fixed dose combination evaluation committee."))
        self.assertTrue(_has_event_context("Unapproved fixed dose combination listed."))

    def test_url_notice_d4_signal_is_not_auto_upgraded(self):
        verdict = {
            "bucket": "event-bearing",
            "deterministic": {
                "rule_matched": "D4",
                "paragraph_drug_matches": 1,
                "paragraph_batch_matches": 0,
                "paragraph_manufacturer_matches": 0,
                "table_drug_matches": 0,
                "table_fdc_matches": 0,
            },
        }

        result = complete_classifier_fields(
            verdict,
            "NSQ NSQ NSQ NSQ NSQ NSQ NSQ NSQ alerts are available at the new URL on the CDSCO website.",
        )

        self.assertEqual(result["bucket"], "context-only")
        self.assertTrue(result["needs_review"])
        self.assertIn("weak_event_signal", result["needs_review_reasons"])

    def test_theft_alert_with_table_evidence_upgrades(self):
        verdict = {
            "bucket": "context-only",
            "deterministic": {
                "rule_matched": "D5",
                "table_drug_matches": 6,
                "table_fdc_matches": 0,
                "paragraph_batch_matches": 0,
            },
        }

        result = complete_classifier_fields(
            verdict,
            "Alert on theft of multiple drug products during transit. Batch numbers listed.",
        )

        self.assertEqual(result["bucket"], "event-bearing")

    def test_dtab_minutes_with_weak_banned_fdc_terms_need_review(self):
        verdict = {
            "bucket": "event-bearing",
            "deterministic": {
                "rule_matched": "D4",
                "paragraph_drug_matches": 1,
                "paragraph_batch_matches": 0,
                "paragraph_manufacturer_matches": 0,
                "table_drug_matches": 0,
                "table_fdc_matches": 0,
            },
        }

        result = complete_classifier_fields(
            verdict,
            "DTAB committee minutes discuss whether an FDC combination should be banned.",
        )

        self.assertEqual(result["bucket"], "context-only")
        self.assertTrue(result["needs_review"])

    def test_unapproved_fdc_table_signal_upgrades(self):
        verdict = {
            "bucket": "context-only",
            "deterministic": {
                "rule_matched": "D5",
                "table_drug_matches": 46,
                "table_fdc_matches": 0,
                "paragraph_batch_matches": 0,
            },
        }

        result = complete_classifier_fields(
            verdict, "List concerning unapproved FDC products."
        )

        self.assertEqual(result["bucket"], "event-bearing")
        self.assertEqual(result["deterministic"]["rule_matched"], "D2")

    def test_weak_event_context_is_flagged_for_review(self):
        verdict = {
            "bucket": "context-only",
            "deterministic": {"rule_matched": "D5"},
        }

        result = complete_classifier_fields(
            verdict, "Committee recommends the combination should be banned."
        )

        self.assertEqual(result["bucket"], "context-only")
        self.assertTrue(result["needs_review"])
        self.assertIn("weak_event_signal", result["needs_review_reasons"])

    def test_weak_event_review_survives_gliclass_enrichment(self):
        def enrich_without_review(verdict, text_map):
            verdict["bucket"] = "context-only"
            verdict["needs_review"] = False
            verdict["needs_review_reasons"] = []
            verdict["gliclass"] = {"verdict": "not_relevant"}
            return verdict

        payload = {
            "doc_id": "alerts/weak-nsq.pdf",
            "source_name": "alerts",
            "pages": [{"page": 1, "text": "Paracetamol is NSQ."}],
            "tables": [],
        }
        with patch.object(classifier, "enrich_verdict", side_effect=enrich_without_review):
            verdict = _apply_classifier(payload, ["Paracetamol"], [])

        self.assertEqual(verdict["bucket"], "context-only")
        self.assertTrue(verdict["needs_review"])
        self.assertIn("weak_event_signal", verdict["needs_review_reasons"])

    def test_header_search_finds_header_after_title_rows(self):
        rows = [
            ["Annual report"],
            ["Table summary"],
            ["Published 2025"],
            ["Drug details"],
            ["Annexure"],
            ["S.No.", "Drugs Name", "Batch No"],
            ["1", "Paracetamol", "AB1234"],
        ] + [["", str(index)] for index in range(20)]

        header = _detect_table_headers([{"page": 1, "cells": rows}])[0]

        self.assertEqual(header["header_row"], 5)
        self.assertEqual(header["columns"]["drug_name_column"], [1])

    def test_serial_number_does_not_map_to_other_header_category(self):
        header = _detect_table_headers([{
            "page": 1,
            "cells": [["S.No.", "Drugs Name", "Batch No"]],
        }])[0]

        self.assertNotEqual(header["columns"].get("batch_column"), [0])
        self.assertNotEqual(header["columns"].get("notification_column"), [0])
        self.assertEqual(header["columns"]["drug_name_column"], [1])

    def test_continuation_table_inherits_previous_header(self):
        tables = [
            {
                "page": 5,
                "cells": [
                    ["S.No.", "Drug Name", "Batch No"],
                    ["1", "Paracetamol", "AB1234"],
                ],
            },
            {
                "page": 6,
                "cells": [
                    ["13.", "Hydroxyquinoline compound", "Notified"],
                    ["14.", "Ibuprofen", "CD5678"],
                ],
            },
        ]

        headers = _detect_table_headers(tables)

        self.assertTrue(headers[1]["header_inherited_from_previous"])
        self.assertEqual(headers[1]["header_row"], None)
        self.assertEqual(headers[1]["columns"]["drug_name_column"], [1])

    def test_suspected_drugs_header_maps_to_drug_name_column(self):
        header = _detect_table_headers([{
            "page": 1,
            "cells": [["S. No.", "Suspected Drugs", "Indication(s)", "Adverse Drug Reactions"]],
        }])[0]

        self.assertEqual(header["columns"]["drug_name_column"], [1])
        self.assertEqual(header["columns"]["indication_column"], [2])
        self.assertEqual(header["columns"]["alert_column"], [3])

    def test_ipc_pvpi_table_keeps_drug_match_on_suspected_drugs_header(self):
        verdict = classify_document({
            "doc_id": "alerts/ipc_pvpi.pdf",
            "source_name": "alerts",
            "pages": [{"text": "PvPI report of adverse drug reactions."}],
            "tables": [{
                "page": 1,
                "cells": [
                    ["S. No.", "Suspected Drugs", "Indication(s)", "Adverse Drug Reactions"],
                    ["1", "Naproxen", "Pain", "Vomiting"],
                ],
            }],
        }, ["Naproxen"], [])

        self.assertEqual(verdict["bucket"], "event-bearing")
        self.assertEqual(verdict["deterministic"]["rule_matched"], "D2")
        self.assertGreater(verdict["deterministic"]["table_drug_matches"], 0)

    def test_numeric_data_row_is_not_detected_as_header(self):
        headers = _detect_table_headers([{
            "page": 6,
            "cells": [[
                "13.",
                "Fixed dose combination of Hydroxyquinoline substituted compounds",
                "Substituted",
            ]],
        }])

        self.assertEqual(headers[0]["columns"], {})

    def test_d5_requires_multiple_context_signals_or_filename_hint(self):
        weak = classify_document({
            "doc_id": "sample.pdf",
            "source_name": "alerts",
            "pages": [{"text": "Drug"}],
            "tables": [],
        })
        hinted = classify_document({
            "doc_id": "guideline.pdf",
            "source_name": "alerts",
            "pages": [{"text": "General information"}],
            "tables": [],
        })

        self.assertEqual(weak["bucket"], "unimportant")
        self.assertEqual(hinted["bucket"], "context-only")

    def test_d5_is_suppressed_when_a_table_header_was_detected(self):
        verdict = classify_document({
            "doc_id": "sample.pdf",
            "source_name": "alerts",
            "pages": [{"text": "CDSCO drug administration notice"}],
            "tables": [{"page": 1, "cells": [["Drug Name", "Batch No"], ["", ""]]}],
        })

        self.assertEqual(verdict["bucket"], "unimportant")

    def test_clean_context_only_does_not_surface_gliclass_uncertainty(self):
        def uncertain_enrichment(verdict, text_map):
            verdict["bucket"] = "context-only"
            verdict["needs_review"] = False
            verdict["needs_review_reasons"] = []
            verdict["gliclass"] = {
                "verdict": "needs_review",
                "reason": "gliclass_uniform",
            }
            return verdict

        payload = {
            "doc_id": "alerts/example.pdf",
            "source_name": "alerts",
            "pages": [{"page": 1, "text": "CDSCO notice with sufficient text."}],
            "tables": [],
        }
        with patch.object(classifier, "enrich_verdict", side_effect=uncertain_enrichment):
            verdict = _apply_classifier(payload, [], [])

        self.assertEqual(verdict["bucket"], "context-only")
        self.assertFalse(verdict["needs_review"])
        self.assertNotIn("gliclass_uncertain", verdict.get("needs_review_reasons", []))

    def test_filename_gate_for_unapproved_fdc_is_treated_as_event_context(self):
        verdict = {
            "bucket": "context-only",
            "deterministic": {"rule_matched": "D5", "table_drug_matches": 0},
        }

        result = complete_classifier_fields(
            verdict,
            "General guidance on marketed medicines.",
            filename="Manufacturing_and_marketing_of_unapproved_FDCs_regarding.pdf",
        )

        self.assertEqual(result["bucket"], "event-bearing")
        self.assertFalse(result["needs_review"])

    def test_paragraph_theft_signal_uses_d4_with_drug_match(self):
        verdict = classify_document({
            "doc_id": "alerts/theft.pdf",
            "source_name": "alerts",
            "pages": [{"text": "Alert on theft of Paracetamol during transit."}],
            "tables": [],
        }, ["Paracetamol"], [])

        self.assertEqual(verdict["bucket"], "event-bearing")
        self.assertEqual(verdict["deterministic"]["rule_matched"], "D4")

    def test_scanned_product_list_with_batch_ids_uses_d8(self):
        verdict = classify_document({
            "doc_id": "alerts/scanned-theft.pdf",
            "source_name": "alerts",
            "pages": [{
                "type": "image",
                "method": "rapidocr",
                "text": (
                    "Alert on theft of multiple products during transit. "
                    "Name of the product Batch No Insulin degludec/Insulin "
                    "Aspart solution for injection 1. RT6GY96 "
                    "Semaglutide Injection 0.5mg 2. RP5S233"
                ),
            }],
            "tables": [],
            "extraction_meta": {
                "ocr_pages": 1,
                "text_pages": 0,
                "stage3_ocr_completed_pages": 1,
            },
        })

        self.assertEqual(verdict["bucket"], "event-bearing")
        self.assertEqual(verdict["deterministic"]["rule_matched"], "D8")
        self.assertGreaterEqual(verdict["deterministic"]["paragraph_batch_matches"], 2)

    def test_scanned_nsq_url_notice_does_not_use_d8(self):
        verdict = classify_document({
            "doc_id": "alerts/nsq-url-notice.pdf",
            "source_name": "alerts",
            "pages": [{
                "type": "image",
                "method": "rapidocr",
                "text": (
                    "Notice: NSQ alerts are available at a new URL. "
                    "Details like Name of product, manufacturing details, "
                    "and NSQ result will be searchable."
                ),
            }],
            "tables": [],
            "extraction_meta": {
                "ocr_pages": 1,
                "text_pages": 0,
                "stage3_ocr_completed_pages": 1,
            },
        }, [], [])

        self.assertNotEqual(verdict["deterministic"]["rule_matched"], "D8")
        self.assertNotEqual(verdict["bucket"], "event-bearing")

    def test_generic_lexicon_match_is_not_scanned_drug_detail(self):
        verdict = classify_document({
            "doc_id": "alerts/scanned-admin-notice.pdf",
            "source_name": "alerts",
            "pages": [{
                "type": "image",
                "method": "rapidocr",
                "text": (
                    "Government of India notice. Name of product and batch "
                    "details will be published on the website."
                ),
            }],
            "tables": [],
            "extraction_meta": {
                "ocr_pages": 1,
                "text_pages": 0,
                "stage3_ocr_completed_pages": 1,
            },
        }, ["India"], [])

        self.assertNotEqual(verdict["deterministic"]["rule_matched"], "D8")

    def test_expanded_event_keyword_still_requires_drug_match(self):
        verdict = classify_document({
            "doc_id": "notice.pdf",
            "source_name": "alerts",
            "pages": [{"text": "Theft incident reported during transit."}],
            "tables": [],
        }, ["Paracetamol"], [])

        self.assertNotEqual(verdict["deterministic"]["rule_matched"], "D4")

    def test_per_document_key_preserves_relative_input_path(self):
        output_key = _s3_output_key_for(
            self.payload,
            "extracted_json",
            "classifier_output",
            input_key="extracted_json/alerts/example.pdf.json",
        )

        self.assertEqual(
            output_key,
            "classifier_output/per_doc/alerts/example.pdf.json",
        )

    def test_per_document_json_is_written_as_json(self):
        s3_client = Mock()

        write_classifier_json_to_s3(
            s3_client, "bucket", "output.json", {"bucket": "event-bearing"}
        )

        s3_client.put_object.assert_called_once()
        call = s3_client.put_object.call_args.kwargs
        self.assertEqual(call["ContentType"], "application/json; charset=utf-8")
        self.assertEqual(call["Body"], b'{"bucket": "event-bearing"}')

    def test_main_persists_verdict_and_summary_before_db_status_update(self):
        s3_client = Mock()
        s3_client.get_paginator.return_value.paginate.return_value = [{
            "Contents": [{"Key": "extracted_json/alerts/example.pdf.json"}]
        }]
        s3_client.get_object.return_value = {
            "Body": io.BytesIO(json.dumps(self.payload).encode("utf-8"))
        }

        with (
            patch.object(classifier.boto3, "client", return_value=s3_client),
            patch.object(classifier, "ensure_profile_columns"),
            patch.object(classifier, "load_medicine_lexicons", return_value=(
                ["Paracetamol"], []
            )),
            patch.object(classifier, "update_classified_documents") as update_status,
        ):
            result = main([
                "--bucket", "input-bucket",
                "--prefix", "extracted_json",
                "--region", "ap-south-1",
                "--s3-output-bucket", "output-bucket",
                "--s3-output-prefix", "classifier_output",
            ])

        self.assertEqual(result, 0)
        writes = [call.kwargs for call in s3_client.put_object.call_args_list]
        json_write = next(write for write in writes if write["Key"].endswith(".json"))
        csv_write = next(write for write in writes if write["Key"].endswith(".csv"))
        self.assertEqual(
            json_write["Key"],
            "classifier_output/per_doc/alerts/example.pdf.json",
        )
        self.assertEqual(csv_write["Key"], "classifier_output/classification_summary.csv")
        self.assertEqual(json.loads(json_write["Body"])["bucket"], "event-bearing")
        update_status.assert_called_once_with(["source_files/alerts/example.pdf"])


if __name__ == "__main__":
    unittest.main()