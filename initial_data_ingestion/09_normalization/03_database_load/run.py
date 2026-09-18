"""Load one validated staging directory into PostgreSQL."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.load_db import load_staging_to_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Load validated staging CSVs into PostgreSQL")
    parser.add_argument("--staging", default="09_normalization/01_staging/batch_run", help="Validated staging directory")
    parser.add_argument("--db-uri", default=None, help="PostgreSQL connection URI")
    args = parser.parse_args()
    counts = load_staging_to_db(args.staging, db_uri=args.db_uri)
    for table, count in counts.items():
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())