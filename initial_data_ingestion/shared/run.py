"""
CLI Pipeline Runner: Orchestrates Extraction -> Resolution -> Staging -> Validation -> (Optional) DB Loading
"""

import sys
import os
import argparse
import json
from .extract import load_parsed_json, extract_record_lineage
from .resolve import resolve_record
from .stage import write_staging_csvs
from .validate import validate_staging_dir
from .load_db import load_staging_to_db


def run_pipeline(input_filepath: str, output_dir: str, load_db_flag: bool = False, db_uri: str = None) -> int:
    """Run full ETL pipeline for a single input parsed JSON file."""
    print(f"Starting ETL Pipeline for: {input_filepath}")
    
    if not os.path.exists(input_filepath):
        print(f"Error: Input file not found: {input_filepath}")
        return 1

    header, raw_records = load_parsed_json(input_filepath)
    doc_id = header.get("source_document_id") or header["filename"]

    print(f"Header Metadata Loaded: Document ID '{doc_id}', Type '{header['document_type']}', Rows: {len(raw_records)}")

    # 1. Extraction & Lineage Assignment
    extracted = extract_record_lineage(doc_id, raw_records)

    # A document date is only an approximate event date; preserve its provenance.
    for record in extracted:
        if record.get("event_date"):
            record["event_date_source"] = "EXTRACTED"
        elif header.get("publication_date"):
            record["event_date"] = header["publication_date"]
            record["event_date_source"] = "DOCUMENT_PUBLICATION_DATE"
        else:
            record["event_date_source"] = "MISSING"

    # 2. Entity Resolution & Taxonomy Check
    resolved = []
    for rec in extracted:
        resolved.append(resolve_record(doc_id, header["document_type"], rec))

    # 3. Staging CSV Export
    created_files = write_staging_csvs(header, resolved, output_dir)
    print(f"Staging CSVs generated in: {output_dir}")

    # 4. Validation
    is_valid, val_errors = validate_staging_dir(output_dir)
    if not is_valid:
        print("Validation FAILED with errors:")
        for err in val_errors:
            print(f"  - {err}")
        return 1
    
    print("Staging Validation PASSED successfully!")

    # 5. Optional DB Loading
    if load_db_flag:
        print("Loading validated records into PostgreSQL database...")
        try:
            db_counts = load_staging_to_db(output_dir, db_uri=db_uri)
            print("Database Load Successful! Row counts:")
            for tbl, cnt in db_counts.items():
                print(f"  - {tbl}: {cnt}")
        except Exception as e:
            print(f"Database Load Failed: {e}")
            return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description="Medicine Scanner Regulatory Data ETL Pipeline")
    parser.add_argument("--input", "-i", required=True, help="Path to input parsed JSON file")
    parser.add_argument("--out", "-o", default="staging/run1", help="Output directory for staging CSVs")
    parser.add_argument("--load-db", action="store_true", help="Load staging CSVs into PostgreSQL database after validation")
    parser.add_argument("--db-uri", default=None, help="PostgreSQL connection URI string")

    args = parser.parse_args()
    sys.exit(run_pipeline(args.input, args.out, args.load_db, args.db_uri))


if __name__ == "__main__":
    main()
