"""
 Batch Processor: Scans 08_json_conversion/output/ directories (excluding gazette, public_notices, and explicit excluded files),
runs the ETL pipeline for active document types, generates staging datasets,
collects reconciliation metrics, and writes summary reports.
"""

import os
import sys
import glob
import csv
import json
from typing import Dict, Any, List
from .run import run_pipeline
from .validate import read_csv_rows

EXCLUDED_FOLDERS = {"gazette", "public_notices", "test_fixtures", "scripts"}

EXCLUDED_FILE_PATTERNS = [
    "514_Notice_Order_regarding_Examination_of_Safety_and_efficacy_of_FDCs",
    "8616_Medical_Device_Alert_date_14_June_2022",
    "7684_Alert_FSN-Medtronic_Heartware_HVAD",
    "3259_Surveillance_of_Drugs_Manufactured_in_the_Country_by_CDSCO"
]


def is_file_excluded(filename: str) -> bool:
    """Check if filename matches any explicitly excluded file patterns."""
    for pattern in EXCLUDED_FILE_PATTERNS:
        if pattern.lower() in filename.lower():
            return True
    return False


def discover_json_files(base_dir: str = "08_json_conversion/output") -> List[str]:
    """Find all valid parsed JSON files in the JSON conversion output."""
    json_files = []
    for root, dirs, files in os.walk(base_dir):
        # Prune excluded directories in-place
        dirs[:] = [d for d in dirs if d not in EXCLUDED_FOLDERS]
        for file in files:
            if file.endswith(".json") and not file.startswith("_"):
                if not is_file_excluded(file):
                    json_files.append(os.path.join(root, file))
    return sorted(json_files)


def run_batch_pipeline(
    parsing_dir: str = "08_json_conversion/output",
    staging_base_dir: str = "09_normalization/01_staging/batch_run",
    reports_dir: str = "09_normalization/04_reports"
) -> int:
    """Execute batch ETL processing across all active parsed JSON files."""
    json_files = discover_json_files(parsing_dir)
    print(f"Discovered {len(json_files)} active parsed JSON files in '{parsing_dir}' (excluded gazette, public_notices, and 3 explicit files)")

    os.makedirs(reports_dir, exist_ok=True)
    os.makedirs(staging_base_dir, exist_ok=True)

    summary_metrics = []
    all_needs_review_rows = []

    total_files = len(json_files)
    passed_files = 0
    failed_files = 0

    total_source_records = 0
    total_complete = 0
    total_needs_review = 0
    total_ignored = 0
    total_failed = 0

    for idx, filepath in enumerate(json_files, start=1):
        rel_path = os.path.relpath(filepath, parsing_dir)
        folder_category = os.path.dirname(rel_path) or "root"
        fname = os.path.basename(filepath)
        
        file_staging_dir = os.path.join(staging_base_dir, folder_category, os.path.splitext(fname)[0])

        try:
            exit_code = run_pipeline(filepath, file_staging_dir, load_db_flag=False)
            if exit_code == 0:
                passed_files += 1
            else:
                failed_files += 1

            # Read manifest metrics
            manifest_path = os.path.join(file_staging_dir, "normalization_manifest.csv")
            manifest_rows = read_csv_rows(manifest_path) if os.path.exists(manifest_path) else []

            counts = {'COMPLETE': 0, 'NEEDS_REVIEW': 0, 'IGNORED': 0, 'FAILED': 0}
            for r in manifest_rows:
                ns = r.get("normalization_status", "FAILED")
                counts[ns] = counts.get(ns, 0) + 1
                if ns == "NEEDS_REVIEW":
                    all_needs_review_rows.append(r)

            file_total = len(manifest_rows)
            file_sum = sum(counts.values())
            recon_pass = (file_total == file_sum)

            total_source_records += file_total
            total_complete += counts['COMPLETE']
            total_needs_review += counts['NEEDS_REVIEW']
            total_ignored += counts['IGNORED']
            total_failed += counts['FAILED']

            summary_metrics.append({
                "category": folder_category,
                "file": fname,
                "total_records": file_total,
                "complete": counts['COMPLETE'],
                "needs_review": counts['NEEDS_REVIEW'],
                "ignored": counts['IGNORED'],
                "failed": counts['FAILED'],
                "reconciliation": "PASS" if recon_pass else "FAIL"
            })

        except Exception as e:
            failed_files += 1
            print(f"Error processing {filepath}: {e}")
            summary_metrics.append({
                "category": folder_category,
                "file": fname,
                "total_records": 0,
                "complete": 0,
                "needs_review": 0,
                "ignored": 0,
                "failed": 1,
                "reconciliation": f"ERROR ({str(e)[:50]})"
            })

    # Write reports/needs_review.csv
    needs_review_path = os.path.join(reports_dir, "needs_review.csv")
    fieldnames = list(all_needs_review_rows[0].keys()) if all_needs_review_rows else [
        "source_record_id", "source_document_id", "source_file", "source_page",
        "source_row", "source_document_type", "organization_key", "product_key",
        "batch_key", "event_key", "normalization_status", "validation_status",
        "review_reason", "error_message"
    ]
    with open(needs_review_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_needs_review_rows)

    # Generate review-analysis artifacts from the current run only.
    org_groups = {}
    orphan_rows = []
    for root, _, files in os.walk(staging_base_dir):
        if "organizations.csv" in files:
            for row in read_csv_rows(os.path.join(root, "organizations.csv")):
                org_groups.setdefault(row.get("normalized_name", ""), set()).add(row.get("organization_name", ""))
        if "regulatory_events.csv" in files:
            for row in read_csv_rows(os.path.join(root, "regulatory_events.csv")):
                if row.get("product_key") == "" or (row.get("scope") == "BATCH" and row.get("batch_key") == ""):
                    orphan_rows.append(row)

    alias_path = os.path.join(reports_dir, "alias_candidates.csv")
    with open(alias_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["normalized_name", "raw_name_count", "raw_names"])
        for normalized, names in sorted(org_groups.items()):
            names.discard("")
            if normalized and len(names) > 1:
                writer.writerow([normalized, len(names), " | ".join(sorted(names))])

    orphan_path = os.path.join(reports_dir, "orphan_analysis.csv")
    with open(orphan_path, 'w', newline='', encoding='utf-8') as f:
        fields = list(orphan_rows[0].keys()) if orphan_rows else ["event_key", "source_record_id", "scope", "product_key", "batch_key"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(orphan_rows)

    failed_path = os.path.join(reports_dir, "failed_extractions.csv")
    with open(failed_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([row for row in all_needs_review_rows if row.get("normalization_status") == "FAILED"])

    # Write reports/metrics_summary.md
    metrics_path = os.path.join(reports_dir, "metrics_summary.md")
    with open(metrics_path, 'w', encoding='utf-8') as f:
        f.write("# ETL Pipeline Metrics Summary Report (Active Scope)\n\n")
        f.write(f"**Total JSON Files Processed:** {total_files}\n")
        f.write(f"**Passed Files:** {passed_files}\n")
        f.write(f"**Failed Files:** {failed_files}\n")
        f.write(f"**Excluded Folders:** `gazette`, `public_notices`\n")
        f.write("**Excluded Files:** Three explicitly removed non-useful datasets\n\n")

        f.write("## Overall Source Record Reconciliation\n\n")
        f.write(f"- **Total Source Records:** {total_source_records:,}\n")
        f.write(f"- **COMPLETE:** {total_complete:,} ({(total_complete/total_source_records*100):.2f}%)\n" if total_source_records else "- **COMPLETE:** 0\n")
        f.write(f"- **NEEDS_REVIEW:** {total_needs_review:,} ({(total_needs_review/total_source_records*100):.2f}%)\n" if total_source_records else "- **NEEDS_REVIEW:** 0\n")
        f.write(f"- **IGNORED:** {total_ignored:,} ({(total_ignored/total_source_records*100):.2f}%)\n" if total_source_records else "- **IGNORED:** 0\n")
        f.write(f"- **FAILED:** {total_failed:,}\n\n")

        f.write("## Per-Category Breakdown (Active Ingestion Scope)\n\n")
        f.write("| Category | Files | Total Records | Complete | Needs Review | Ignored | Failed |\n")
        f.write("|---|---|---|---|---|---|---|\n")

        cat_map = {}
        for m in summary_metrics:
            c = m["category"]
            if c not in cat_map:
                cat_map[c] = {"files": 0, "total": 0, "comp": 0, "nr": 0, "ign": 0, "fail": 0}
            cat_map[c]["files"] += 1
            cat_map[c]["total"] += m["total_records"]
            cat_map[c]["comp"] += m["complete"]
            cat_map[c]["nr"] += m["needs_review"]
            cat_map[c]["ign"] += m["ignored"]
            cat_map[c]["fail"] += m["failed"]

        for cat, stat in cat_map.items():
            f.write(f"| `{cat}` | {stat['files']} | {stat['total']:,} | {stat['comp']:,} | {stat['nr']:,} | {stat['ign']:,} | {stat['fail']:,} |\n")

    print("\n============================================================")
    print(f"Active Scope Batch Execution Completed: {passed_files}/{total_files} Files Passed Validation.")
    print(f"Total Source Records Processed: {total_source_records:,}")
    print(f"COMPLETE: {total_complete:,} | NEEDS_REVIEW: {total_needs_review:,} | IGNORED: {total_ignored:,} | FAILED: {total_failed:,}")
    print(f"Summary report written to: {metrics_path}")
    print("============================================================")

    return 0 if failed_files == 0 else 1


def main():
    sys.exit(run_batch_pipeline())


if __name__ == "__main__":
    main()
