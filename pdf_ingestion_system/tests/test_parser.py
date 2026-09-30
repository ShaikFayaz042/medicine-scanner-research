import io
import json
import unittest
from unittest.mock import Mock, patch

from pdf_ingestion_system.parser import parser


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
            patch.object(parser, "ensure_profile_columns"),
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


if __name__ == "__main__":
    unittest.main()