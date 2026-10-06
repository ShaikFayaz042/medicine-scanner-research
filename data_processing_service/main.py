"""Run the complete PDF ingestion workflow from one command."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from data_processing_service.shared.config import AWS_REGION, S3_INPUT_BUCKET, S3_INPUT_PREFIX
from data_processing_service.shared.manifest import manifest_key


STAGE_MODULES = {
	"processor": "data_processing_service.processor.run",
	"profiler": "data_processing_service.profiler.run",
	"extractor": "data_processing_service.extractor.run",
	"classifier": "data_processing_service.classifier.run",
	"parser": "data_processing_service.parser.run",
	"normalizer": "data_processing_service.normalizer.run",
	"ingester": "data_processing_service.ingester.run",
}
_shutdown = False


EXTRACTED_PREFIX = "medicine-data-storage/processed_files/extracted_json"
CLASSIFIER_PREFIX = "medicine-data-storage/processed_files/classifier_output"
PARSED_PREFIX = "medicine-data-storage/processed_files/parsed_json"
PROFILER_PREFIX = "medicine-data-storage/processed_files/profiler_output"
NORMALIZED_PREFIX = "medicine-data-storage/processed_files/normalized"


def _load_stage_main(stage: str) -> Callable[[list[str]], int]:
	return importlib.import_module(STAGE_MODULES[stage]).main


def _handle_sigterm(signum, frame) -> None:
	global _shutdown
	_shutdown = True
	print("SIGTERM received, will finish current item", file=sys.stderr, flush=True)


def _first_env(*names: str) -> str | None:
	for name in names:
		value = os.environ.get(name)
		if value:
			return value
	return None


def _args_from_env() -> list[str]:
	args: list[str] = []
	pairs = (
		(("PDF_S3_BUCKET", "AWS_S3_INPUT_BUCKET"), "--bucket"),
		(("PDF_S3_PREFIX", "AWS_S3_INPUT_PREFIX"), "--prefix"),
		(("AWS_REGION",), "--region"),
		(("PDF_LIMIT",), "--limit"),
		(("RUN_ID",), "--run-id"),
		(("MANIFEST_S3_KEY",), "--manifest-s3-key"),
	)
	for variables, option in pairs:
		value = _first_env(*variables)
		if value:
			args.extend([option, value])

	message_body = os.environ.get("SQS_MESSAGE_BODY")
	if message_body:
		try:
			payload = json.loads(message_body)
		except json.JSONDecodeError:
			payload = {}
		if isinstance(payload, dict) and payload.get("s3_key"):
			args.extend(["--doc-id", str(payload["s3_key"])])
	run_id = _first_env("RUN_ID")
	if run_id and "--manifest-s3-key" not in args:
		args.extend(["--manifest-s3-key", manifest_key(run_id)])
	return args


def _run_pipeline(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(
		description="Run profiler, extraction, classification, parsing, normalization, and database ingest."
	)
	parser.add_argument("--bucket", default=S3_INPUT_BUCKET, help="S3 input/output bucket")
	parser.add_argument("--region", default=AWS_REGION, help="AWS region")
	parser.add_argument("--source-prefix", default=S3_INPUT_PREFIX, help="S3 prefix containing source PDFs")
	parser.add_argument("--extracted-prefix", default=EXTRACTED_PREFIX, help="S3 prefix for extracted JSON")
	parser.add_argument("--classifier-prefix", default=CLASSIFIER_PREFIX, help="S3 prefix for classifier outputs")
	parser.add_argument("--parsed-prefix", default=PARSED_PREFIX, help="S3 prefix for parsed JSON")
	parser.add_argument("--profiler-prefix", default=PROFILER_PREFIX, help="Legacy profiler JSON prefix read by normalization")
	parser.add_argument("--nsq-prefix", help="S3 prefix containing scraper NSQ/spurious JSON")
	parser.add_argument("--normalized-prefix", default=NORMALIZED_PREFIX, help="S3 prefix for normalized staging CSVs")
	parser.add_argument("--profile-output", type=Path, help="Local CSV path for the optional profiler report")
	parser.add_argument("--profile", action="store_true", help="Run the optional local profile report before extraction")
	parser.add_argument("--run-id", help="Run identifier for the manifest ledger")
	parser.add_argument("--manifest-s3-key", help="S3 object key for the pipeline manifest JSON")
	parser.add_argument("--limit", type=int, default=0, help="Maximum number of objects each stage processes; 0 means all")
	parser.add_argument("--commit", action="store_true", help="Commit normalized records to the medicine database")
	args = parser.parse_args(argv)

	if not args.bucket:
		parser.error("--bucket is required; set AWS_S3_INPUT_BUCKET or pass --bucket")
	if args.limit < 0:
		parser.error("--limit must be zero or greater")

	source_prefix = args.source_prefix.strip("/")
	extracted_prefix = args.extracted_prefix.strip("/")
	classifier_prefix = args.classifier_prefix.strip("/")
	parsed_prefix = args.parsed_prefix.strip("/")
	normalized_prefix = args.normalized_prefix.strip("/")
	nsq_prefix = (args.nsq_prefix or f"{source_prefix}/nsq").strip("/")
	limit_args = ["--limit", str(args.limit)] if args.limit else []
	manifest_args: list[str] = []
	if args.run_id:
		manifest_args.extend(["--run-id", args.run_id])
	manifest_s3_key = args.manifest_s3_key or (manifest_key(args.run_id) if args.run_id else None)
	if manifest_s3_key:
		manifest_args.extend(["--manifest-s3-key", manifest_s3_key])

	stages: list[tuple[str, list[str]]] = []
	if args.profile:
		profile_args = [
			"--bucket", args.bucket,
			"--prefix", source_prefix,
			"--region", args.region,
		]
		if args.profile_output is not None:
			profile_args.extend(["--output", str(args.profile_output)])
		profile_args.extend(limit_args)
		profile_args.extend(manifest_args)
		stages.append(("profiler", profile_args))

	stages.extend([
		("extractor", [
			"--bucket", args.bucket,
			"--prefix", source_prefix,
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", extracted_prefix,
			*limit_args,
			*manifest_args,
		]),
		("classifier", [
			"--bucket", args.bucket,
			"--prefix", extracted_prefix,
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", classifier_prefix,
			*limit_args,
			*manifest_args,
		]),
		("parser", [
			"--bucket", args.bucket,
			"--prefix", extracted_prefix,
			"--classifier-csv-bucket", args.bucket,
			"--classifier-csv-key", f"{classifier_prefix}/classification_summary.csv",
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", parsed_prefix,
			*limit_args,
			*manifest_args,
		]),
		("normalizer", [
			"--bucket", args.bucket,
			"--prefix", parsed_prefix,
			"--profiler-prefix", args.profiler_prefix.strip("/"),
			"--nsq-prefix", nsq_prefix,
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", normalized_prefix,
			*limit_args,
			*manifest_args,
		]),
	])

	ingest_args = [
		"--bucket", args.bucket,
		"--prefix", normalized_prefix,
		"--region", args.region,
		*limit_args,
		*manifest_args,
	]
	if not args.commit:
		ingest_args.append("--dry-run")
	stages.append(("ingester", ingest_args))

	stage_labels = {
		"profiler": "Profiler",
		"extractor": "Extractor",
		"classifier": "Classifier",
		"parser": "Parser",
		"normalizer": "Normalizer",
		"ingester": "Database ingest",
	}
	for stage, stage_args in stages:
		print(f"\n=== {stage_labels[stage]} ===", flush=True)
		stage_main = _load_stage_main(stage)
		result = stage_main(stage_args)
		if result:
			print(f"Pipeline stopped: {stage_labels[stage]} exited with status {result}", file=sys.stderr)
			return result

	print("\nPipeline completed successfully.")
	if not args.commit:
		print("Database ingest was a dry-run. Pass --commit to insert normalized records.")
	return 0


def main(argv: list[str] | None = None) -> int:
	stage = os.environ.get("STAGE")
	if not stage:
		return _run_pipeline(argv)
	if stage not in STAGE_MODULES:
		print(
			f"ERROR: STAGE must be one of: {', '.join(STAGE_MODULES)}",
			file=sys.stderr,
		)
		return 2

	signal.signal(signal.SIGTERM, _handle_sigterm)
	cli_args = list(argv) if argv is not None else sys.argv[1:]
	stage_args = cli_args if cli_args else _args_from_env()
	return _load_stage_main(stage)(stage_args)


if __name__ == "__main__":
	raise SystemExit(main())