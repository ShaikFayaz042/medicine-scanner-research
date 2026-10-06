"""Run parser, normalizer, and ingester for an immutable S3 run manifest."""

from __future__ import annotations

import argparse
import importlib
import sys

import boto3

from data_processing_service.shared.config import AWS_REGION, S3_INPUT_BUCKET
from data_processing_service.shared.manifest import manifest_key, read_manifest, utc_now_iso, write_result

DEFAULT_EXTRACTED_PREFIX = "medicine-data-storage/processed_files/extracted_json"
DEFAULT_CLASSIFIER_PREFIX = "medicine-data-storage/processed_files/classifier_output"
DEFAULT_PARSED_PREFIX = "medicine-data-storage/processed_files/parsed_json"
DEFAULT_PROFILER_PREFIX = "medicine-data-storage/processed_files/profiler_output"
DEFAULT_NORMALIZED_PREFIX = "medicine-data-storage/processed_files/normalized"


def _stage_main(stage: str):
    return importlib.import_module(f"data_processing_service.{stage}.run").main


def _manifest_value(manifest: dict, name: str, default: str) -> str:
    value = manifest.get(name)
    return str(value) if value else default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run parser, normalizer, and ingester for one manifest-backed run.")
    parser.add_argument("--bucket", default=None, help="S3 bucket containing the manifest and pipeline data")
    parser.add_argument("--region", default=AWS_REGION, help="AWS region")
    parser.add_argument("--run-id", help="Run identifier; defaults to run_id inside the manifest")
    parser.add_argument("--manifest-s3-key", help="Optional override for the immutable input manifest key")
    parser.add_argument("--prefix", help="Compatibility input prefix from the common stage environment bridge")
    parser.add_argument("--extracted-prefix", default=None)
    parser.add_argument("--classifier-prefix", default=None)
    parser.add_argument("--parsed-prefix", default=None)
    parser.add_argument("--profiler-prefix", default=None)
    parser.add_argument("--nsq-prefix", default=None)
    parser.add_argument("--normalized-prefix", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--commit", action="store_true", help="Commit ingester inserts; defaults to dry-run")
    args = parser.parse_args(argv)
    del args.prefix

    bucket = args.bucket or S3_INPUT_BUCKET
    if not bucket:
        parser.error("--bucket is required")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    s3_client = boto3.client("s3", region_name=args.region)
    key = args.manifest_s3_key or (manifest_key(args.run_id) if args.run_id else None)
    if not key:
        parser.error("--run-id or --manifest-s3-key is required")
    started_at = utc_now_iso()
    try:
        manifest = read_manifest(s3_client, bucket, key)
        run_id = args.run_id or str(manifest.get("run_id") or "")
        if not run_id:
            raise ValueError("The manifest must contain run_id or --run-id must be supplied")

        run_prefix = f"medicine-data-storage/processed_files/runs/{run_id}"
        extracted_prefix = args.extracted_prefix or _manifest_value(manifest, "extracted_prefix", f"{run_prefix}/extracted_json")
        classifier_prefix = args.classifier_prefix or _manifest_value(manifest, "classifier_prefix", f"{run_prefix}/classifier_output")
        parsed_prefix = f"{run_prefix}/parsed_json"
        profiler_prefix = args.profiler_prefix or _manifest_value(manifest, "profiler_prefix", DEFAULT_PROFILER_PREFIX)
        nsq_prefix = args.nsq_prefix or _manifest_value(manifest, "nsq_prefix", "medicine-data-storage/source_files/nsq")
        normalized_prefix = f"{run_prefix}/normalized"
        limit_args = ["--limit", str(args.limit)] if args.limit else []
        stage_args = {
            "parser": [
                "--bucket", bucket, "--prefix", extracted_prefix,
                "--classifier-csv-bucket", bucket,
                "--classifier-csv-key", f"{classifier_prefix}/classification_summary.csv",
                "--region", args.region, "--s3-output-bucket", bucket,
                "--s3-output-prefix", parsed_prefix, *limit_args,
                "--run-id", run_id, "--manifest-s3-key", key,
            ],
            "normalizer": [
                "--bucket", bucket, "--prefix", parsed_prefix,
                "--profiler-prefix", profiler_prefix, "--nsq-prefix", nsq_prefix,
                "--region", args.region, "--s3-output-bucket", bucket,
                "--s3-output-prefix", normalized_prefix, *limit_args,
                "--run-id", run_id, "--manifest-s3-key", key,
            ],
            "ingester": [
                "--bucket", bucket, "--prefix", normalized_prefix,
                "--region", args.region, *limit_args,
                "--run-id", run_id, "--manifest-s3-key", key,
                *([] if args.commit else ["--dry-run"]),
            ],
        }
        for stage, stage_argv in stage_args.items():
            print(f"\n=== {stage.title()} ===", flush=True)
            result = _stage_main(stage)(stage_argv)
            if result:
                write_result(s3_client, bucket, run_id, "processor", {
                    "schema_version": 1,
                    "stage": "processor",
                    "run_id": run_id,
                    "started_at": started_at,
                    "finished_at": utc_now_iso(),
                    "status": "failure",
                    "input_keys": [key],
                    "output_keys": [],
                    "error": f"{stage} exited with status {result}",
                })
                return result
        write_result(s3_client, bucket, run_id, "processor", {
            "schema_version": 1,
            "stage": "processor",
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "status": "success",
            "input_keys": [key],
            "output_keys": [
                f"{parsed_prefix}/",
                f"{normalized_prefix}/",
            ],
            "error": None,
        })
        return 0
    except Exception as exc:
        print(f"Processor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())