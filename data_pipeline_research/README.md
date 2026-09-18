# Data Pipeline Research

This folder contains the research-oriented version of the medicine data ingestion and normalization pipeline used to explore, validate, and iterate on the CDSCO and IPC/PvPI extraction workflow.

It is intended as a clean experimental area for:

- reviewing source download patterns
- testing PDF extraction and OCR approaches
- classifying documents by type and relevance
- converting extracted data into structured records
- normalizing entities and building downstream database-ready outputs

This research pipeline mirrors the broader repository workflow, but keeps the work isolated from the main project code and legacy outputs.

## Purpose

The goal of this pipeline is to transform regulatory and public-health source material into a structured, searchable dataset, while preserving provenance and raw extraction artifacts.

The flow is:

1. Download source material
2. Inventory PDFs and classify them
3. Extract text and OCR output
4. Classify document type
5. Parse records into structured JSON
6. Normalize entities and events
7. Validate and load into a database-friendly format

## Repository layout

```text
data_pipeline_research/
├── README.md
├── .gitignore
├── cdsco-downloader/
│   └── source downloaders and PDF analysis scripts
├── database/
│   └── schema and loader scripts
├── docs/
│   └── pipeline design and schema notes
├── normalization/
│   └── entity resolution and normalized output generation
├── raw_extraction/
│   └── OCR and text extraction outputs
├── structured_raw/
│   └── parsed, validated source records
├── tests/
│   └── pipeline and parsing validation checks
├── type_classification/
│   └── document-type classification outputs
├── websites/
│   └── source research and extraction experiments
└── downloads/
    └── generated raw files, API responses, and PDFs
```

## Main stages

### 1. Downloads

The `cdsco-downloader/` folder contains the scripts that fetch source documents and API payloads for the research pipeline.

Typical workflow:

```powershell
python cdsco-downloader/01_download_cdsco_alerts.py
python cdsco-downloader/02_download_cdsco_fdc.py
python cdsco-downloader/03_download_cdsco_public_notices.py
python cdsco-downloader/04_download_cdsco_gazette.py
python cdsco-downloader/05_download_cdsco_banned_drugs.py
python cdsco-downloader/06_download_ipc_pvpi.py
python cdsco-downloader/07_fetch_cdsco_nsq_json.py
```

These scripts write downloaded files and metadata into the research `downloads/` area.

### 2. PDF inventory and classification

Once files are downloaded, the pipeline inventories PDFs and classifies them by importance and extraction mode.

Common steps:

```powershell
python cdsco-downloader/lists_pdfs.py
python cdsco-downloader/classify_pdfs.py Medicine_PDF_Classification.csv
python cdsco-downloader/analyze_pdfs.py
```

This stage produces:

- PDF manifests
- priority lists
- important/unimportant classification output
- text/scanned/mixed analysis

### 3. Light extraction and raw extraction

The raw extraction workflow reads PDFs and produces page-level text, OCR, and structured extraction artifacts.

Typical runs:

```powershell
python raw_extraction/extract_text.py
python raw_extraction/extract_ocr.py
python raw_extraction/extract_ocr_tesseract.py
python raw_extraction/analyze_extraction.py
```

Outputs are stored under `raw_extraction/` and are used downstream by type classification and parsing.

### 4. Type classification

The `type_classification/` folder stores the classification outputs that assign source files to categories such as:

- NSQ
- spurious
- alert
- FDC
- public notice
- Gazette
- PvPI
- circular
- guideline

The classification step is the bridge between raw extracted content and structured record parsing.

### 5. Structured parsing

Parsed data is written into `structured_raw/` as normalized and source-aware JSON objects. This is where the raw document content is translated into machine-readable record structure.

### 6. Normalization and database-ready outputs

The `normalization/` directory handles:

- document metadata normalization
- event normalization
- manufacturer/product/ingredient/entity mapping
- canonical remapping and provenance
- final validation of entity linkage

Important scripts may include patterns such as:

```powershell
python normalization/normalize_documents.py
python normalization/normalize_events.py
python normalization/resolve_entities.py
python normalization/remap_canonical.py
python normalization/build_entity_sources.py
```

### 7. Database loading and validation

The `database/` folder contains the schema and loader logic used to move normalized content into a PostgreSQL-friendly structure.

Typical usage:

```powershell
python database/load.py --dry-run
python database/load.py
```

Validation may be done through SQL files in the same folder.

## Setup

Create a project environment and install dependencies from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If OCR or scanned-PDF handling is required, ensure the relevant system dependencies are installed as needed for Tesseract/RapidOCR-based processing.

## Typical research run

From the repository root or this research folder, use a staged approach similar to the following:

```powershell
# 1. Download source files
python cdsco-downloader/01_download_cdsco_alerts.py
python cdsco-downloader/02_download_cdsco_fdc.py
python cdsco-downloader/03_download_cdsco_public_notices.py
python cdsco-downloader/04_download_cdsco_gazette.py
python cdsco-downloader/05_download_cdsco_banned_drugs.py
python cdsco-downloader/06_download_ipc_pvpi.py
python cdsco-downloader/07_fetch_cdsco_nsq_json.py

# 2. Build PDF inventory
python cdsco-downloader/lists_pdfs.py

# 3. Classify and analyze PDFs
python cdsco-downloader/classify_pdfs.py Medicine_PDF_Classification.csv
python cdsco-downloader/analyze_pdfs.py

# 4. Extract content
python raw_extraction/extract_text.py
python raw_extraction/extract_ocr.py
python raw_extraction/extract_ocr_tesseract.py

# 5. Run type classification and parse records
# use the project-specific parsing scripts for the relevant document types

# 6. Normalize and validate
python normalization/normalize_documents.py
python normalization/normalize_events.py
python normalization/resolve_entities.py
python normalization/remap_canonical.py
```

## Notes

- This folder is research-first and may contain exploratory scripts, intermediate artifacts, and staged outputs.
- The data should be treated as source material and evidence, not as final production records unless explicitly validated.
- Preserve the original sources, extracted text, and metadata, because these are important for auditability and later reconciliation.
- The workflow should avoid overwriting the frozen or canonical outputs used elsewhere in the repository without intention and review.

## Related documentation

- Root project README
- `docs/PIPELINE_AUDIT.md`
- `docs/pdf-schema-samples.md`
- `websites/README.md`

## Summary

`data_pipeline_research` is the experimental sandbox for understanding the full medicine data collection and enrichment process. It is designed to test the assumptions behind the larger repository pipeline, validate extraction logic, and refine the downstream normalization and database workflow before final production use.
