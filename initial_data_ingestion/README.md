# Initial Data Ingestion

This folder contains the medicine regulatory PDF/API ingestion workflow. It is organized into nine numbered steps. Existing downloads and generated outputs are preserved; the pipeline is not automatically re-downloaded or recomputed.

Detailed normalization design: [09_normalization/implementation_plan.md](09_normalization/implementation_plan.md)

Detailed stage notes: [00_project_support/PIPELINE_STEPS.md](00_project_support/PIPELINE_STEPS.md)

## Folder layout

```text
01_downloads/                  PDFs, source API JSON, metadata, and downloader script
02_light_extraction/           First, second, and last-page extraction
03_ai_classification/          AI prompt and classification result
04_classified_documents/       process_queue, junk, manual_review
05_type_classification/        text, scanned, mixed PDF groups
06_raw_extraction/             Local text extraction and OCR handoff
07_raw_extraction_output/      Pasted local/Kaggle extraction output
08_json_conversion/            JSON records generated from raw extraction
09_normalization/              Normalization, staging, validation, DB load
00_project_support/            Schemas, configuration, reports, and run guide
shared/                        Reusable normalization modules
tests/                         Eight validation tests and fixtures
archive/                       Preserved legacy intermediate outputs
```

## Important safety rule

Do not run Step 1 on the laptop unless a fresh download is required. The current `01_downloads` folder already contains the source files. Do not run a placeholder script until its implementation has been added.

## Setup

Run these commands from the repository root:

```powershell
cd Z:\medicine-scanner-research\initial_data_ingestion

..\.venv\Scripts\Activate.ps1
python -m pip install -r 00_project_support\requirements.txt
```

If the virtual environment is at the repository root rather than inside this folder, use:

```powershell
cd Z:\medicine-scanner-research
\.venv\Scripts\Activate.ps1
python -m pip install -r initial_data_ingestion\00_project_support\requirements.txt
cd initial_data_ingestion
```

## Step 1: Download PDFs and source JSON

Script: `01_downloads/download_all_sources.py`

This script downloads PDFs from all configured sources, calls the CDSCO JSON APIs, and saves PDFs and JSON responses under `01_downloads`. It never moves or deletes existing files and skips files that already exist.

Run all sources only when a fresh download is explicitly required:

```powershell
python 01_downloads\download_all_sources.py
```

Inspect one source without writing files:

```powershell
python 01_downloads\download_all_sources.py --sources alerts --dry-run
```

Expected outputs:

```text
01_downloads/<source>/*.pdf
01_downloads/<source>/*.json
```

## Step 2: Light extraction

Script: `02_light_extraction/extract_light_pages.py`

For every PDF, extract only page 1, page 2, and the last page. Use `pdfplumber` first and RapidOCR as fallback. The local script and the Kaggle notebook supplied by the team should produce compatible output.

The laptop script is implemented. Run a one-PDF smoke test first:

```powershell
python 02_light_extraction\extract_light_pages.py --limit 1
```

Run all PDFs:

```powershell
python 02_light_extraction\extract_light_pages.py
```

Useful options:

```powershell
# Only selected source folders
python 02_light_extraction\extract_light_pages.py --sources alerts fdc

# Recreate outputs that already exist
python 02_light_extraction\extract_light_pages.py --force

# Use a different input/output location
python 02_light_extraction\extract_light_pages.py `
	--input 01_downloads `
	--output 02_light_extraction/output
```

Output is written as matching `.txt` files under `02_light_extraction/output`, with `_manifest.json` recording status, selected page count, extraction method, and failures. The script uses `pdfplumber` first and loads RapidOCR only when native page text is empty. Do not overwrite the original PDFs.

## Step 3: AI document classification

Files:

```text
03_ai_classification/prompt.txt
03_ai_classification/classification.txt
```

Use the light-extraction output, filenames, and project requirements with the prompt. Save one classification result per PDF in `classification.txt` using exactly one destination:

```text
process_queue
junk
manual_review
```

This step is currently a manual/AI handoff. No automatic AI command is configured yet.

## Step 4: Copy PDFs by classification

Script: `04_classified_documents/classify_documents.py`

Read `03_ai_classification/classification.txt`, find each PDF in `01_downloads`, and copy it into the matching folder:

```text
04_classified_documents/process_queue/
04_classified_documents/junk/
04_classified_documents/manual_review/
```

The source PDF in `01_downloads` remains unchanged. The script validates both AI output files, reports missing or duplicate PDFs, copies files without deleting them, and writes `_classification_manifest.json`. Run it after the required PDFs exist in `01_downloads`:

```powershell
python 04_classified_documents\classify_documents.py
```

Validate without copying:

```powershell
python 04_classified_documents\classify_documents.py --dry-run
```

The script uses `03_ai_classification/classification.json` and `classification.txt` by default. Use `--downloads <path>` only when the source PDFs are stored elsewhere.

## Step 5: Classify process-queue PDF type

Script: `05_type_classification/classify_pdf_type.py`

Read only PDFs from `04_classified_documents/process_queue` and copy them into:

```text
05_type_classification/text/
05_type_classification/scanned/
05_type_classification/mixed/
```

The script is implemented. Run it from the repository root:

```powershell
Set-Location 'Z:\medicine-scanner-research'
.\.venv\Scripts\python.exe initial_data_ingestion\05_type_classification\classify_pdf_type.py
```

Preview without copying:

```powershell
Set-Location 'Z:\medicine-scanner-research'
.\.venv\Scripts\python.exe initial_data_ingestion\05_type_classification\classify_pdf_type.py --dry-run
```

Do not move or delete the original process-queue files.

The existing classification summary is retained in `00_project_support/pdf_type_classification.json`.

## Step 6: Raw extraction and Kaggle OCR handoff

Script: `06_raw_extraction/extract_text_files.py`

Process the three groups as follows:

```text
text     -> extract locally on the laptop
scanned  -> zip and process with RapidOCR in Kaggle
mixed    -> zip and process with RapidOCR in Kaggle, preserving text pages
```

The script is implemented. Run it from the repository root:

```powershell
Set-Location 'Z:\medicine-scanner-research'
.\.venv\Scripts\python.exe initial_data_ingestion\06_raw_extraction\extract_text_files.py
```

Preview without writing outputs:

```powershell
Set-Location 'Z:\medicine-scanner-research'
.\.venv\Scripts\python.exe initial_data_ingestion\06_raw_extraction\extract_text_files.py --dry-run
```

Do not rerun the full Kaggle extraction when the required output has already been pasted into Step 7.

## Step 7: Preserve raw extraction output

Place the local extraction output and pasted Kaggle output under:

```text
07_raw_extraction_output/
```

Keep text files, OCR files, table/block sidecars, manifests, and source categories together. This folder is the stable input contract for Step 8.

## Step 8: Convert raw extraction to JSON

The conversion uses the two parser files in `08_json_conversion/`:

```text
08_json_conversion/new_parsing.py
08_json_conversion/special_alerts_parser.py
```

Run it from the repository root:

```powershell
cd Z:\medicine-scanner-research
.\.venv\Scripts\python.exe initial_data_ingestion\08_json_conversion\new_parsing.py --input initial_data_ingestion\07_raw_extraction_output --output initial_data_ingestion\08_json_conversion\output
```

This script walks the raw extraction output and writes parsed JSON documents back under:

```text
initial_data_ingestion/08_json_conversion/output/
```

The special-alert parser is imported by `new_parsing.py` and does not need a separate hardcoded repo path.

## Step 9: Normalize, validate, and load

The existing normalization modules are in `shared`. Normalized CSVs and reports are grouped under:

```text
09_normalization/
├── 01_staging/
├── 02_validation/
├── 03_database_load/
└── 04_reports/
```

### Run the validation suite

This uses the test fixture and does not download PDFs:

```powershell
python -m tests.run_all
```

Expected result:

```text
Summary: 8 PASSED, 0 FAILED out of 8 tests
```

### Run batch normalization

After Step 8 has produced JSON files:

```powershell
python 00_project_support\run.py
```

The default paths are:

```text
Input:   08_json_conversion/output
Staging: 09_normalization/01_staging/batch_run
Reports: 09_normalization/04_reports
```

To select paths explicitly:

```powershell
python 00_project_support\run.py `
	--input 08_json_conversion/output `
	--staging 09_normalization/01_staging/batch_run `
	--reports 09_normalization/04_reports
```

### Load validated staging into PostgreSQL

Only load a staging directory after validation has passed:

```powershell
python 09_normalization\03_database_load\run.py `
	--staging 09_normalization/01_staging/batch_run `
	--db-uri "postgresql://user:password@host:5432/database"
```

The database schema and indexes are available in `00_project_support/schema.sql` and `00_project_support/indexes.sql`. Never commit real database credentials.

## Data integrity rules

- Original PDFs remain in `01_downloads`.
- Step 4 and Step 5 copy files; they do not delete source files.
- `classification.txt` is the input for Step 4.
- `process_queue` is the current equivalent of the old `03_filtered_files` folder.
- Raw extraction must preserve page and source lineage.
- JSON conversion must preserve raw values and extraction method.
- Normalization uses deterministic SHA-256 canonical keys.
- Validate staging before database loading.
- Missing or ambiguous data becomes review/failed output; do not invent entities.

## Existing artifacts

Older intermediate outputs are preserved under `archive/legacy_stages`. Existing generated outputs remain available under the numbered stages and are not treated as fresh runs automatically.