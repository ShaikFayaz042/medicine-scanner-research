# PDF Ingestion System

Run these commands from the repository root in PowerShell. The tools use the AWS settings in the project `.env` files. AWS authentication must also be available through an IAM role/profile or the standard `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` environment variables. The scraper metadata DB settings use the `SCRAPER_DB_*` prefix.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1

$Bucket = "medicine-data-storage-449902674528-ap-south-1-an"
$Region = "ap-south-1"
$SourcePrefix = "medicine-data-storage/source_files"
```

## Run the Full Pipeline

Run the required stages sequentially from the repository root:

```powershell
python pdf_ingestion_system/main.py --bucket $Bucket --region $Region --source-prefix $SourcePrefix
```

This runs extraction, classification, parsing, normalization, and append-only database ingest. The optional profiler can be included with `--profile` when its `pdf_processing_pipeline` dependency is available. Database ingest defaults to a dry-run; pass `--commit` to insert normalized records. Earlier stages still write their outputs to S3 and update scraper status as documented below. Use `--limit N` to cap each stage during a small test run.

## 1. Optional PDF Profile Report

This optional inventory scans source PDFs and JSON from S3, writes its CSV report locally to `pdf_ingestion_system/profiler/file_profiles.csv` by default, and updates profile status in the scraper database. Override the report path with `--output`. It does not create the `nsq_json/` or `spurious_json/` folders; those JSON inputs are consumed separately by the normalizer in Step 6.

```powershell
python -m pdf_ingestion_system.profiler.collect_and_profile `
  --bucket $Bucket `
  --prefix $SourcePrefix `
  --region $Region
```

## 2. Extract PDFs

Reads PDFs from `source_files/` and writes extracted text/table JSON to S3.

```powershell
python -m pdf_ingestion_system.extractor.extractor `
  --bucket $Bucket `
  --prefix $SourcePrefix `
  --region $Region `
  --s3-output-bucket $Bucket `
  --s3-output-prefix medicine-data-storage/processed_files/extracted_json
```

## 3. Classify Extracted Documents

Writes `classification_summary.csv` and one enriched verdict JSON per input document under `classifier_output/per_doc/`. Step 4 uses the summary CSV to select only `event-bearing` documents for parsing.

```powershell
python -m pdf_ingestion_system.classifier.classifier `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/extracted_json `
  --region $Region `
  --s3-output-bucket $Bucket `
  --s3-output-prefix medicine-data-storage/processed_files/classifier_output
```

## 4. Parse Extracted Documents

Converts the extractor JSON files into structured parsed JSON files. Requires the classifier summary CSV from Step 3 and parses only rows whose `bucket` is `event-bearing`. By default, the CSV is read from `medicine-data-storage/processed_files/classifier_output/classification_summary.csv` in the input bucket. Use `--classifier-csv-key` or `--classifier-csv-bucket` if the classifier output is stored elsewhere.

```powershell
python -m pdf_ingestion_system.parser.parser `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/extracted_json `
  --region $Region `
  --s3-output-bucket $Bucket `
  --s3-output-prefix medicine-data-storage/processed_files/parsed_json
```

## 5. Normalize Both JSON Inputs

The normalizer processes the parsed PDF input and the scraper's direct JSON input:

- All JSON files under `medicine-data-storage/processed_files/parsed_json/` (PDF-derived parsed outputs).
- NSQ and spurious JSON files under `medicine-data-storage/source_files/nsq/` (the scraper's `aaData` JSON exports).
- For backwards compatibility, JSON files directly under `medicine-data-storage/processed_files/profiler_output/nsq_json/` and `.../spurious_json/` are also included when present.

It validates each document and writes per-document staging CSVs under `processed_files/normalized/`. It does not insert normalized records into a database. After all CSVs upload successfully, it marks the exact matching scraper `documents` row `normalized` in `status` and, when available, `processing_stage`.

```powershell
python -m pdf_ingestion_system.normalizer.normalizer `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/parsed_json `
  --profiler-prefix medicine-data-storage/processed_files/profiler_output `
  --nsq-prefix medicine-data-storage/source_files/nsq `
  --region $Region `
  --s3-output-bucket $Bucket `
  --s3-output-prefix medicine-data-storage/processed_files/normalized
```

The default normalizer prefixes already match these paths, so `--prefix`, `--profiler-prefix`, and `--nsq-prefix` can be omitted when using the standard layout. Override `--nsq-prefix` if the scraper's `source_files/nsq/` location differs. Use `--limit 1` to test one document from the combined inputs.

## Append-Only Database Ingest

Before the first ingest, apply the additive mapping migration in `pdf_ingestion_system/migrations/001_staging_key_map.sql` to the medicine database. It creates only `staging_key_map` and backfills it with INSERT-only statements from existing key columns; it does not alter or delete existing records. The migration can be re-run safely. The ingester writes each normalized staging key and its database ID to this table in the same transaction as the document rows. Do not run the ingester until the migration has succeeded.

The frozen schema already has unique `organization_key`, `ingredient_key`, `product_key`, `batch_key`, and `event_key` columns. The mapping table provides an explicit, durable staging-key-to-primary-key registry in addition to those native unique keys.

After the medicine transaction commits, the ingester marks the corresponding scraper document `ingested` in `status` and `processing_stage` when that column exists. Status synchronization matches a unique source S3 key/URL or document key; missing or ambiguous matches are reported instead of updating multiple rows. Configure valid `SCRAPER_DB_*` credentials before running normalization or ingest. Dry-runs never update scraper status.

Run a one-folder dry-run first. `--bucket` is required for S3 ingestion:

```powershell
.\.venv\Scripts\python.exe -m pdf_ingestion_system.ingester.append_ingest `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/normalized `
  --region $Region `
  --limit 1 `
  --dry-run
```

To dry-run every normalized folder, omit `--limit 1`. Review the per-document `would_insert` counts and the aggregate `table_counts`. To commit all normalized folders, omit both `--limit` and `--dry-run`:

```powershell
.\.venv\Scripts\python.exe -m pdf_ingestion_system.ingester.append_ingest `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/normalized `
  --region $Region
```

`skipped_duplicate_document` with zero insert counts is the expected idempotent result for a document already present; it is not a new-row dry-run. A real duplicate rerun reconciles the scraper row to `ingested`. The summary reports document count, per-table insert counts, and scraper status-update failures. A nonzero exit code indicates at least one scraper status could not be synchronized.

## Local Normalizer Test

To run normalization and validation on one local parsed JSON file without S3 writes or database loading:

```powershell
python -m pdf_ingestion_system.normalizer.normalizer `
  --input initial_data_ingestion/tests/fixtures/parsed_json/nsq_test.json `
  --out pdf_ingestion_system/normalizer/local_output/nsq_test
```
