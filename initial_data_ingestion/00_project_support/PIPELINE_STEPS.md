# Ingestion Pipeline Steps

The pipeline starts from already available source artifacts during local development. Do not run Step 1 unless a fresh source download is explicitly required.

## 1. Download and source ingestion

Entry point: `01_downloads/download_all_sources.py`

Download PDFs from every configured source, call source APIs, and save both PDFs and JSON responses under `01_downloads`. The script skips existing files and does not move or delete source data. Use `--sources` to select sources and `--dry-run` to inspect without writing.

## 2. Light extraction

Entry point: `02_light_extraction/extract_light_pages.py`

Process every PDF but inspect only pages 1, 2, and the last page. The local script uses `pdfplumber` first and RapidOCR as the fallback; the supplied Kaggle notebook remains available for the team workflow. Local output is written under `02_light_extraction/output` with a manifest.

## 3. AI document classification

Inputs are the light-extraction output, filenames, and project requirements. The prompt belongs in `03_ai_classification/prompt.txt`. Save the AI response as `03_ai_classification/classification.txt` with one of these destinations per file: `process_queue`, `junk`, or `manual_review`.

## 4. Classify and copy PDFs

Entry point: `04_classified_documents/classify_documents.py`

Read `classification.txt`, locate the matching PDF in `01_downloads`, and copy it into `04_classified_documents/process_queue`, `junk`, or `manual_review`. This step must not delete the source PDF.

`03_filtered_files` is a legacy name for a copied subset of PDFs selected for further processing. In the current layout, its equivalent is `04_classified_documents/process_queue`; it is not an additional pipeline stage.

## 5. Classify process-queue PDFs by format

Entry point: `05_type_classification/classify_pdf_type.py`

Read only PDFs in `04_classified_documents/process_queue` and copy them into `text`, `scanned`, or `mixed` under this step. Keep the original process-queue files unchanged.

## 6. Raw extraction and OCR handoff

Entry point: `06_raw_extraction/extract_text_files.py`

Extract text from `text` PDFs locally. Zip `scanned` and `mixed` PDFs for the RapidOCR Kaggle notebook. Do not rerun the full OCR handoff on a laptop when pasted Kaggle output already exists.

## 7. Raw extraction output

Retain pasted extraction output under `07_raw_extraction_output`. Keep text output, OCR output, manifests, and any table/block sidecars together so Step 8 has a stable input contract.

## 8. Convert extraction output to JSON

Entry point: `08_json_conversion/convert_raw_extraction_to_json.py`

Convert the raw text, tables, and OCR outputs into one JSON representation per source document. Preserve source filenames, page information, extraction method, and raw content for traceability.

## 9. Normalize

The JSON records become the input to the existing normalization code in `shared`. Validated CSV staging is written under `09_normalization/01_staging`, reports under `09_normalization/04_reports`, and database loading is available through `09_normalization/03_database_load/run.py`.

The detailed normalization design and database contract are maintained in [09_normalization/implementation_plan.md](../09_normalization/implementation_plan.md).

## Current state

The repository already contains downloaded artifacts and prior extraction/classification/JSON outputs. Some later-stage scripts remain placeholders for the missing operational pieces; adding or testing them does not trigger downloads or recomputation.