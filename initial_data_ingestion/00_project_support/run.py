"""Run the active ingestion batch from the pipeline root."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.batch_process import run_batch_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the medicine regulatory ingestion batch")
    parser.add_argument("--input", default="08_json_conversion/output", help="JSON record directory")
    parser.add_argument("--staging", default="09_normalization/01_staging/batch_run", help="Batch staging output directory")
    parser.add_argument("--reports", default="09_normalization/04_reports", help="Report output directory")
    args = parser.parse_args()
    return run_batch_pipeline(args.input, args.staging, args.reports)


if __name__ == "__main__":
    sys.exit(main())