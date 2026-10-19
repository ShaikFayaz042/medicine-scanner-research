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
python data_processing_service/main.py --bucket $Bucket --region $Region --source-prefix $SourcePrefix
```

This runs extraction, classification, parsing, normalization, and append-only database ingest. The profiler can be included with `--profile`. Database ingest defaults to a dry-run; pass `--commit` to insert normalized records. Earlier stages still write their outputs to S3 and update scraper status as documented below. Use `--limit N` to cap each stage during a small test run.

## Local CLI (`_run_pipeline`) vs AWS (Step Functions)

The local `_run_pipeline()` uses prefix scans and applies `--limit N` independently at each stage. With `--limit 1`, stages can select different documents; this command is a pipeline smoke test, not exact document-level orchestration. For exact selection, run stages with a manifest and `--run-id`; the extractor uses only the manifest's PDF entries. The processor runs parser → normalizer → ingester. Production orchestration uses the Step Functions definition in `data_processing_service/sfn/pipeline.json` and ECS task definitions in `data_processing_service/tasks/`.

## Stage Dispatch and Docker

Set `STAGE` to run one stage through `main.py`; without `STAGE`, the full local CLI above remains available:

```powershell
$env:STAGE = "extractor"
$env:PDF_S3_BUCKET = $Bucket
$env:PDF_S3_PREFIX = $SourcePrefix
$env:AWS_REGION = $Region
$env:PDF_LIMIT = "10"
python data_processing_service/main.py
```

The supported stages are `processor`, `profiler`, `extractor`, `classifier`, `parser`, `normalizer`, and `ingester`. Explicit CLI arguments take precedence over the environment bridge. `SQS_MESSAGE_BODY` may contain `{"s3_key":"..."}` to select one input object/document.

### Manifest Processor

The `processor` stage reads, but never modifies, the run manifest. It runs parser, normalizer, and ingester sequentially; ingester defaults to dry-run. Set `RUN_ID` to use `medicine-data-storage/processed_files/runs/<run-id>/manifest.json`, or override the input key with `MANIFEST_S3_KEY`. Each stage writes its own result under that run's `results/` prefix (`extracted.json`, `classified.json`, `parsed.json`, `normalized.json`, or `ingested.json`); the processor writes `processor.json`. A nonzero stage exit stops the processor immediately.

```powershell
$env:STAGE = "processor"
$env:RUN_ID = "example-run"
python data_processing_service/main.py
```

Build the service images from the repository root so the Dockerfiles can copy the correct project files and the per-image requirements files (`requirements-common.txt`, `requirements-extractor.txt`, `requirements-classifier.txt`). Do not build from the service folder or from the repo-root `requirements.txt`; those files are not the actual runtime dependency set for the image.

```powershell
$AccountId = "449902674528"
$Region = "ap-south-1"
$EcrRegistry = "$AccountId.dkr.ecr.$Region.amazonaws.com"

# Sign in to ECR once
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 449902674528.dkr.ecr.ap-south-1.amazonaws.com
# Build CPU-only Linux images for the ECS Fargate runtime (x86_64)
docker build --platform linux/amd64 -f data_processing_service/Dockerfile.common -t data-processor:local .
docker build --platform linux/amd64 -f data_processing_service/Dockerfile.extractor -t data-extractor:local .
docker build --platform linux/amd64 -f data_processing_service/Dockerfile.classifier -t data-classifier:local .
```

Push the images to the ECR repos that match the task definitions already in the project:

```powershell
docker tag data-processor:local "$EcrRegistry/data-processor:v0.3.0"
docker tag data-extractor:local "$EcrRegistry/data-extractor:v0.3.0"
docker tag data-classifier:local "$EcrRegistry/data-classifier:v0.3.0"

docker push "$EcrRegistry/data-processor:v0.3.0"
docker push "$EcrRegistry/data-extractor:v0.3.0"
docker push "$EcrRegistry/data-classifier:v0.3.0"
```

Use `data-processor` for processor, profiler, parser, normalizer, and ingester; override `STAGE` in the task definition. `tasks/ingester-v1.json` defines `data-ingester-task`, which the server launches with `--commit` when an admin approves a run. After pushing new images, register the task definitions (`aws ecs register-task-definition --cli-input-json file://data_processing_service/tasks/<file>.json`) and update the task revisions referenced in `sfn/pipeline.json`. Use `data-extractor` for extraction and `data-classifier` for classification. The classifier uses GLiClass (`gliclass`), not GLiNER. Keep the repository-root `requirements.txt` only for non-container workspace tooling; the actual container dependency sets are the split service requirements files above.

## OCR

Scanned pages are read with RapidOCR using the English PP-OCRv5 recognition model (`extractor/ocr.py`). RapidOCR's default Chinese model drops the spaces between English words, so the model is set explicitly. `Dockerfile.extractor` downloads the models at build time into `OCR_MODEL_DIR`, so tasks never fetch them at runtime.

A page is OCR'd when it has no text layer, when its text layer is mostly undecodable glyphs, or when images cover most of it and its text layer is only a stamp or footer. OCR output keeps per-line boxes and confidence scores, sideways scans are rotated before reading, and ruled tables are rebuilt cell by cell so the parser can read scanned tables. When the ruling lines are dashed or broken, the table is rebuilt from text positions instead: columns come from the header row (or the previous page's columns on continuation pages) and rows start at each serial number, which is re-read from an enlarged strip of the first column because small serials are often missed on the full page. `OCR_DPI` (default 200) and `OCR_MAX_SIDE_LEN` (default 3000) tune the page rendering.

## Tests

```powershell
python -m pytest data_processing_service/tests
```

`tests/regression` scores the real extractor and parser against hand-checked records from 40 CDSCO PDFs (`golden.json`). The PDFs are not committed; fetch them into `initial_data_ingestion/01_downloads/` first. Tests skip when a PDF is missing.

```powershell
python -m data_processing_service.tests.regression.fetch_fixtures
python -m data_processing_service.tests.regression.harness                    # scorecard
python -m data_processing_service.tests.regression.harness --update-baseline  # record improvements
```

The test fails when any document scores below its recorded baseline. Baselines only move up.

## 1. Optional PDF Profile Report

This optional inventory scans source PDFs and JSON from S3, writes its CSV report locally to `data_processing_service/profiler/file_profiles.csv` by default, and updates profile status in the scraper database. Override the report path with `--output`. PDF profiling is implemented inside `data_processing_service/profiler/pdf_profile.py`. It does not create the `nsq_json/` or `spurious_json/` folders; those JSON inputs are consumed separately by the normalizer below.

```powershell
python -m data_processing_service.profiler.run `
  --bucket $Bucket `
  --prefix $SourcePrefix `
  --region $Region
```

## 2. Extract PDFs

Reads PDFs from `source_files/` and writes extracted text/table JSON to S3.

```powershell
python -m data_processing_service.extractor.run `
  --bucket $Bucket `
  --prefix $SourcePrefix `
  --region $Region `
  --s3-output-bucket $Bucket `
  --s3-output-prefix medicine-data-storage/processed_files/extracted_json
```

## 3. Classify Extracted Documents

Writes `classification_summary.csv` and one enriched verdict JSON per input document under `classifier_output/per_doc/`. Step 4 uses the summary CSV to select only `event-bearing` documents for parsing.

```powershell
python -m data_processing_service.classifier.run `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/extracted_json `
  --region $Region `
  --s3-output-bucket $Bucket `
  --s3-output-prefix medicine-data-storage/processed_files/classifier_output
```

## 4. Parse Extracted Documents

Converts the extractor JSON files into structured parsed JSON files. Requires the classifier summary CSV from Step 3 and parses rows whose `bucket` is `event-bearing`, plus rows the classifier flagged `needs_review` (their output carries a `classifier_review` block, and the run's `parsed.json` result lists them under `review_documents`). Tables are read with multi-row headers, section rows, page continuations and the 2013–2018 combined batch column. Column names are mapped to one standard set (`Name of Drugs/medical device/cosmetics`, `Batch No`, `Date of Manufacture`, ...). Documents without tables (gazette prohibitions, recall and falsified-drug alerts, circulars) are parsed by `parser/narrative.py`. In manifest runs the parser reads the extractor's output for the run. Runs without PDFs finish as a successful no-op. By default, the CSV is read from `medicine-data-storage/processed_files/classifier_output/classification_summary.csv` in the input bucket. Use `--classifier-csv-key` or `--classifier-csv-bucket` if the classifier output is stored elsewhere.

```powershell
python -m data_processing_service.parser.run `
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

It validates each document and writes per-document staging CSVs under `processed_files/normalized/`. It does not insert normalized records into a database. Records with a product, or product-less records that document a regulatory action, are marked `VALID` in `normalization_manifest.csv`; only `VALID` rows are ingested. Dates are written as ISO dates, and document types are mapped onto the database's allowed values. In manifest runs, the scraper's NSQ/spurious JSON documents (manifest `documents` of kind `json`) are normalized alongside the parser output. A scraper row that cannot be found is reported under `status_update_failures` instead of failing the document. After all CSVs upload successfully, it marks the exact matching scraper `documents` row `normalized` in `status` and, when available, `processing_stage`.

```powershell
python -m data_processing_service.normalizer.run `
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

Before the first ingest, apply the additive mapping migration in `data_processing_service/migrations/001_staging_key_map.sql` to the medicine database. It creates only `staging_key_map` and backfills it with INSERT-only statements from existing key columns; it does not alter or delete existing records. The migration can be re-run safely. The ingester writes each normalized staging key and its database ID to this table in the same transaction as the document rows. Do not run the ingester until the migration has succeeded.

The frozen schema already has unique `organization_key`, `ingredient_key`, `product_key`, `batch_key`, and `event_key` columns. The mapping table provides an explicit, durable staging-key-to-primary-key registry in addition to those native unique keys.

After the medicine transaction commits, the ingester marks the corresponding scraper document `ingested` in `status` and `processing_stage` when that column exists. Status synchronization matches a unique source S3 key/URL or document key; missing or ambiguous matches are reported instead of updating multiple rows. Configure valid `SCRAPER_DB_*` credentials before running normalization or ingest. Dry-runs never update scraper status.

Run a one-folder dry-run first. `--bucket` is required for S3 ingestion:

```powershell
.\.venv\Scripts\python.exe -m data_processing_service.ingester.run `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/normalized `
  --region $Region `
  --limit 1 `
  --dry-run
```

To dry-run every normalized folder, omit `--limit 1`. Review the per-document `would_insert` counts and the aggregate `table_counts`. To commit all normalized folders, omit both `--limit` and `--dry-run`:

```powershell
.\.venv\Scripts\python.exe -m data_processing_service.ingester.run `
  --bucket $Bucket `
  --prefix medicine-data-storage/processed_files/normalized `
  --region $Region
```

`skipped_duplicate_document` with zero insert counts is the expected idempotent result for a document already present; it is not a new-row dry-run. A real duplicate rerun reconciles the scraper row to `ingested`. The summary reports document count, per-table insert counts, and scraper status-update failures. A nonzero exit code indicates at least one scraper status could not be synchronized.

## Local Normalizer Test

To run normalization and validation on one local parsed JSON file without S3 writes or database loading:

```powershell
python -m data_processing_service.normalizer.run `
  --input extraction_output/Drug_Safety_Alert_Feb_2026.json `
  --out data_processing_service/normalizer/local_output/nsq_test
```
