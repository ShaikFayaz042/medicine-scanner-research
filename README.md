# Medicine Scanner Research

This repository contains the research, extraction, classification, normalization, and database-loading pipeline for medicine safety and regulatory data gathered from CDSCO and IPC/PvPI sources.

The project is organized around two active tracks:

- [initial_data_ingestion](initial_data_ingestion) — the main numbered, stage-based workflow for downloads, extraction, classification, parsing, normalization, and loading
- [data_pipeline_research](data_pipeline_research) — the research sandbox used for experimentation, source review, and pipeline iteration

The older code under `websites/`, `cdsco-downloader/`, `raw_extraction/`, `scripts/`, and `normalization/` remains useful as historical reference material, but the active work is centered in the newer numbered ingestion pipeline.

## Repository structure

```text
.
├── README.md
├── .gitignore
├── .venv/
├── .pytest_cache/
├── requirements.txt
├── automated_scraper/
├── initial_data_ingestion/
│   ├── 00_project_support/
│   ├── 01_downloads/
│   ├── 02_light_extraction/
│   ├── 03_ai_classification/
│   ├── 04_classified_documents/
│   ├── 05_type_classification/
│   ├── 06_raw_extraction/
│   ├── 08_json_conversion/
│   ├── 09_normalization/
│   ├── .gitignore
│   └── README.md
├── data_pipeline_research/
│   ├── .gitignore
│   ├── README.md
│   ├── cdsco-downloader/
│   ├── database/
│   ├── docs/
│   ├── normalization/
│   ├── raw_extraction/
│   ├── structured_raw/
│   ├── tests/
│   ├── type_classification/
│   └── websites/
└── .git/
```

This is the actual top-level layout of the repository. Historical and legacy project material remains under the active ingestion and research subprojects instead of being shown as separate root folders.

## Active workflow

The main working pipeline is in [initial_data_ingestion/README.md](initial_data_ingestion/README.md). It follows a numbered stage layout:

1. `00_project_support` — project docs and flow definitions
2. `01_downloads` — download source PDFs and data
3. `02_light_extraction` — quick page-level extraction for review
4. `03_ai_classification` — AI-assisted classification and output contract
5. `04_classified_documents` — copy/route files into classified groups
6. `05_type_classification` — determine document type and extraction mode
7. `06_raw_extraction` — full extraction and OCR processing
8. `08_json_conversion` — convert extracted output into structured JSON
9. `09_normalization` — normalization, validation, and downstream preparation

This keeps the pipeline readable and makes it easier to rerun only the required stage without mixing legacy research outputs with the active ingestion flow.

## Research sandbox

The [data_pipeline_research](data_pipeline_research) folder is a separate exploration workspace for:

- testing source access methods
- validating extraction logic
- comparing OCR and parsing approaches
- experimenting with document classification and normalization
- preserving intermediate research artifacts without disturbing the active ingestion pipeline

The README in that folder explains the research flow in more detail.

## Setup

Create a virtual environment and install the project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For the extraction pipeline, confirm the required OCR dependencies are available, especially where scanned PDFs are handled.

## Quick start

The recommended working path is:

```powershell
cd Z:\medicine-scanner-research
.\.venv\Scripts\Activate.ps1
```

Then follow the stage-by-stage commands in [initial_data_ingestion/README.md](initial_data_ingestion/README.md).

For a research-oriented walkthrough and experimental notes, use the docs in [data_pipeline_research/README.md](data_pipeline_research/README.md).

## Legacy and reference material

Older supporting artifacts are kept inside the active subprojects rather than as top-level repo folders. Examples include:

- [initial_data_ingestion](initial_data_ingestion) — active numbered pipeline and stage outputs
- [data_pipeline_research](data_pipeline_research) — research sandbox with downloader, parser, extraction, schema, and normalization experiments
- [automated_scraper](automated_scraper) — application layer for monitoring and scraping

These remain useful as references, but the current repository structure is intentionally centered on the two main working directories above.

## Notes

- Source data, extracted content, and intermediate outputs are preserved for auditability.
- Generated outputs are intentionally separated from source scripts through the stage-specific `.gitignore` rules.
- Working from the numbered ingestion flow is preferred over editing legacy experimental scripts unless a specific research task requires it.

## Related documentation

- [initial_data_ingestion/README.md](initial_data_ingestion/README.md)
- [data_pipeline_research/README.md](data_pipeline_research/README.md)
- [docs/PIPELINE_AUDIT.md](docs/PIPELINE_AUDIT.md)
- [docs/pdf-schema-samples.md](docs/pdf-schema-samples.md)
- [websites/README.md](websites/README.md)

## Summary

This project is a research and ingestion pipeline for medicine safety and drug-regulatory data. The active path is the numbered ingestion workflow in [initial_data_ingestion](initial_data_ingestion), while the research sandbox in [data_pipeline_research](data_pipeline_research) keeps exploratory work isolated and traceable.
