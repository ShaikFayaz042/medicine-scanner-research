"""Run the complete PDF ingestion workflow from one command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from pdf_ingestion_system.classifier.classifier import main as classify_main
from pdf_ingestion_system.extractor.extractor import main as extract_main
from pdf_ingestion_system.ingester.append_ingest import main as ingest_main
from pdf_ingestion_system.normalizer.normalizer import main as normalize_main
from pdf_ingestion_system.parser.parser import main as parse_main
from pdf_ingestion_system.shared.config import AWS_REGION, S3_INPUT_BUCKET, S3_INPUT_PREFIX


EXTRACTED_PREFIX = "medicine-data-storage/processed_files/extracted_json"
CLASSIFIER_PREFIX = "medicine-data-storage/processed_files/classifier_output"
PARSED_PREFIX = "medicine-data-storage/processed_files/parsed_json"
PROFILER_PREFIX = "medicine-data-storage/processed_files/profiler_output"
NORMALIZED_PREFIX = "medicine-data-storage/processed_files/normalized"


def main(argv: list[str] | None = None) -> int:
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

	stages: list[tuple[str, Callable[[list[str]], int], list[str]]] = []
	if args.profile:
		try:
			from pdf_ingestion_system.profiler.collect_and_profile import main as profile_main
		except ModuleNotFoundError as exc:
			if exc.name and exc.name.startswith("pdf_processing_pipeline"):
				parser.error(
					"--profile requires the pdf_processing_pipeline profiler package, "
					"which is not installed or available in this workspace"
				)
			raise
		profile_args = [
			"--bucket", args.bucket,
			"--prefix", source_prefix,
			"--region", args.region,
		]
		if args.profile_output is not None:
			profile_args.extend(["--output", str(args.profile_output)])
		profile_args.extend(limit_args)
		stages.append(("Profiler", profile_main, profile_args))

	stages.extend([
		("Extractor", extract_main, [
			"--bucket", args.bucket,
			"--prefix", source_prefix,
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", extracted_prefix,
			*limit_args,
		]),
		("Classifier", classify_main, [
			"--bucket", args.bucket,
			"--prefix", extracted_prefix,
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", classifier_prefix,
			*limit_args,
		]),
		("Parser", parse_main, [
			"--bucket", args.bucket,
			"--prefix", extracted_prefix,
			"--classifier-csv-bucket", args.bucket,
			"--classifier-csv-key", f"{classifier_prefix}/classification_summary.csv",
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", parsed_prefix,
			*limit_args,
		]),
		("Normalizer", normalize_main, [
			"--bucket", args.bucket,
			"--prefix", parsed_prefix,
			"--profiler-prefix", args.profiler_prefix.strip("/"),
			"--nsq-prefix", nsq_prefix,
			"--region", args.region,
			"--s3-output-bucket", args.bucket,
			"--s3-output-prefix", normalized_prefix,
			*limit_args,
		]),
	])

	ingest_args = [
		"--bucket", args.bucket,
		"--prefix", normalized_prefix,
		"--region", args.region,
		*limit_args,
	]
	if not args.commit:
		ingest_args.append("--dry-run")
	stages.append(("Database ingest", ingest_main, ingest_args))

	for stage_name, stage_main, stage_args in stages:
		print(f"\n=== {stage_name} ===", flush=True)
		result = stage_main(stage_args)
		if result:
			print(f"Pipeline stopped: {stage_name} exited with status {result}", file=sys.stderr)
			return result

	print("\nPipeline completed successfully.")
	if not args.commit:
		print("Database ingest was a dry-run. Pass --commit to insert normalized records.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())