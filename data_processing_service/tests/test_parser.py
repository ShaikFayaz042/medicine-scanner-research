import io
import json
import unittest
from unittest.mock import Mock, patch

from data_processing_service.parser import run as parser


class ParserClassifierFilterTests(unittest.TestCase):
    def test_main_parses_only_event_bearing_documents(self):
        extracted_documents = {
            "extracted_json/alerts/keep.json": {
                "doc_id": "keep",
                "s3_object_key": "source_files/alerts/keep.pdf",
            },
            "extracted_json/alerts/skip.json": {
                "doc_id": "skip",
                "s3_object_key": "source_files/alerts/skip.pdf",
            },
        }
        classifier_csv = (
            "bucket,s3_object_key\n"
            "event-bearing,source_files/alerts/keep.pdf\n"
            "context-only,source_files/alerts/skip.pdf\n"
        ).encode("utf-8")
        s3_client = Mock()
        s3_client.get_paginator.return_value.paginate.return_value = [{
            "Contents": [{"Key": key} for key in extracted_documents]
        }]

        def get_object(*, Bucket, Key):
            if Key == "classifier/classification_summary.csv":
                return {"Body": io.BytesIO(classifier_csv)}
            return {
                "Body": io.BytesIO(
                    json.dumps(extracted_documents[Key]).encode("utf-8")
                )
            }

        s3_client.get_object.side_effect = get_object
        with (
            patch.object(parser.boto3, "client", return_value=s3_client),
            patch.object(parser, "get_document_metadata", return_value={}),
            patch.object(
                parser,
                "_process_single_payload",
                side_effect=lambda payload: {
                    "title": payload["doc_id"],
                    "records": [],
                },
            ) as process_payload,
            patch.object(parser, "update_parsed_documents") as update_parsed,
        ):
            result = parser.main([
                "--bucket", "input-bucket",
                "--prefix", "extracted_json",
                "--region", "ap-south-1",
                "--classifier-csv-key", "classifier/classification_summary.csv",
                "--s3-output-bucket", "output-bucket",
                "--s3-output-prefix", "parsed",
            ])

        self.assertEqual(result, 0)
        process_payload.assert_called_once_with(extracted_documents[
            "extracted_json/alerts/keep.json"
        ])
        update_parsed.assert_called_once_with(["source_files/alerts/keep.pdf"])
        output_writes = [
            call.kwargs
            for call in s3_client.put_object.call_args_list
            if call.kwargs["Key"].startswith("parsed/")
        ]
        self.assertEqual(len(output_writes), 1)
        self.assertEqual(output_writes[0]["Key"], "parsed/alerts/keep.json")

    def test_manifest_input_prefix_keeps_classifier_per_doc_tree(self):
        keys = [
            "medicine-data-storage/processed_files/runs/run-1/classifier_output/per_doc/banned/CDSCO.json",
            "medicine-data-storage/processed_files/runs/run-1/classifier_output/per_doc/ipc/Drug.json",
        ]
        self.assertEqual(
            parser._manifest_input_prefix(keys, "medicine-data-storage/processed_files/extracted_json"),
            "medicine-data-storage/processed_files/runs/run-1/classifier_output/per_doc",
        )
        key = keys[0]
        self.assertEqual(
            parser._output_key_for_document(
                key,
                parser._manifest_input_prefix(keys, "medicine-data-storage/processed_files/extracted_json"),
                "medicine-data-storage/processed_files/parsed_json",
                title="CDSCO banned document",
            ),
            "medicine-data-storage/processed_files/parsed_json/banned/CDSCO_banned_document.json",
        )


class FakeS3:
    """Dict-backed S3 client: get_object reads `objects`, put_object stores into it."""

    def __init__(self, objects):
        self.objects = dict(objects)
        self.read_keys = []

    def get_object(self, *, Bucket, Key):
        self.read_keys.append(Key)
        body = self.objects[Key]
        return {"Body": io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))}

    def put_object(self, *, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = json.loads(Body)

    def get_paginator(self, _name):
        raise AssertionError("manifest runs must not prefix-scan")


RUN = "medicine-data-storage/processed_files/runs/run-1"
SOURCE_PDF = "medicine-data-storage/source_files/alerts/12927_NSQ_ALERT.pdf"
EXTRACTED_KEY = f"{RUN}/extracted_json/alerts/12927_NSQ_ALERT.json"
VERDICT_KEY = f"{RUN}/classifier_output/per_doc/alerts/12927_NSQ_ALERT.json"
CSV_KEY = f"{RUN}/classifier_output/classification_summary.csv"


def _manifest_run(manifest, csv_rows, extracted_payload=None):
    objects = {
        f"{RUN}/manifest.json": manifest,
        f"{RUN}/results/extracted.json": {"run_id": "run-1", "stage": "extractor", "output_keys": [EXTRACTED_KEY]},
        f"{RUN}/results/classified.json": {"run_id": "run-1", "stage": "classifier", "output_keys": [VERDICT_KEY, CSV_KEY]},
        CSV_KEY: ("bucket,needs_review,needs_review_reasons,s3_object_key\n" + csv_rows).encode("utf-8"),
        # The classifier's per-document verdict has no pages or tables; parsing it yields nothing.
        VERDICT_KEY: {"doc_id": "alerts/12927_NSQ_ALERT.pdf", "bucket": "event-bearing", "s3_object_key": SOURCE_PDF},
    }
    if extracted_payload is not None:
        objects[EXTRACTED_KEY] = extracted_payload
    s3 = FakeS3(objects)
    with (
        patch.object(parser.boto3, "client", return_value=s3),
        patch.object(parser, "get_document_metadata", return_value={}),
        patch.object(parser, "update_parsed_documents") as update_parsed,
    ):
        result = parser.main([
            "--bucket", "bucket", "--manifest-s3-key", f"{RUN}/manifest.json", "--run-id", "run-1",
            "--s3-output-bucket", "bucket", "--s3-output-prefix", f"{RUN}/parsed_json",
        ])
    return result, s3, update_parsed


EXTRACTED_PAYLOAD = {
    "doc_id": "alerts/12927_NSQ_ALERT.pdf",
    "s3_object_key": SOURCE_PDF,
    "pdf_title": "CDSCO NSQ ALERT FOR THE MONTH OF June 2025",
    "pages": [{"page": 1, "text": "NOT OF STANDARD QUALITY ALERT"}],
    "tables": [{"page": 1, "cells": [
        {"cells": ["S.No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date"], "table_index": 0},
        {"cells": ["1.", "Dextrose Injection I.P. 5%w/v (D5)", "1-3098", "01/2025", "12/2027"], "table_index": 0},
    ]}],
}
PDF_MANIFEST = {"run_id": "run-1", "has_pdfs": True, "documents": [{"s3_key": SOURCE_PDF, "kind": "pdf"}]}


def test_manifest_run_parses_extractor_output_not_classifier_verdicts():
    result, s3, update_parsed = _manifest_run(
        PDF_MANIFEST, f"event-bearing,False,[],{SOURCE_PDF}\n", EXTRACTED_PAYLOAD
    )

    assert result == 0
    assert EXTRACTED_KEY in s3.read_keys and VERDICT_KEY not in s3.read_keys
    parsed = s3.objects[f"{RUN}/parsed_json/alerts/12927_NSQ_ALERT.json"]
    assert parsed["records"][0]["Name of Drugs/medical device/cosmetics"] == "Dextrose Injection I.P. 5%w/v (D5)"
    assert parsed["records"][0]["Batch No"] == "1-3098"
    assert s3.objects[f"{RUN}/results/parsed.json"]["output_keys"] == [f"{RUN}/parsed_json/alerts/12927_NSQ_ALERT.json"]
    update_parsed.assert_called_once_with([SOURCE_PDF])


def test_json_only_run_is_a_successful_no_op():
    manifest = {"run_id": "run-1", "has_pdfs": False, "documents": [{"s3_key": "src/nsq/nsq_2025-06.json", "kind": "json"}]}

    result, s3, update_parsed = _manifest_run(manifest, "")

    assert result == 0
    assert s3.objects[f"{RUN}/results/parsed.json"]["status"] == "success"
    assert s3.objects[f"{RUN}/results/parsed.json"]["input_keys"] == []
    update_parsed.assert_not_called()


def test_documents_flagged_for_review_are_parsed_and_marked():
    result, s3, _ = _manifest_run(
        PDF_MANIFEST, f'context-only,True,"[""weak_event_signal""]",{SOURCE_PDF}\n', EXTRACTED_PAYLOAD
    )

    assert result == 0
    parsed = s3.objects[f"{RUN}/parsed_json/alerts/12927_NSQ_ALERT.json"]
    assert parsed["classifier_review"] == {"bucket": "context-only", "reasons": ["weak_event_signal"]}
    assert s3.objects[f"{RUN}/results/parsed.json"]["review_documents"] == [SOURCE_PDF]


def test_documents_neither_event_bearing_nor_flagged_are_skipped():
    result, s3, update_parsed = _manifest_run(
        PDF_MANIFEST, f"unimportant,False,[],{SOURCE_PDF}\n", EXTRACTED_PAYLOAD
    )

    assert result == 0
    assert s3.objects[f"{RUN}/results/parsed.json"]["output_keys"] == []
    update_parsed.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()