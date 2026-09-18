# Medicine Scanner - Pipeline Audit (First Pass + Second Pass Plan)

Audit date: 2026-09-14. This report describes the files and generated artifacts present at audit time. No code or configuration was changed for this audit.

## Executive Summary

- The download inventory contains 1,672 PDFs (1.43 GB), with no zero-byte or sub-1 KB PDFs.
- The reviewed classification CSV contains 444 Important and 1,228 Unimportant PDFs, and those counts match the PDFs placed in the corresponding important/unimportant folders.
- Content analysis ran on 444 Important PDFs: 291 TEXT, 149 SCANNED, and 4 MIXED, with no `ERROR` rows.
- Parsing produced 395 structured document files, 12,648 records, and 13 empty structured documents (all in NSQ or spurious outputs). Normalization produced 3,703 canonical products, 5,015 canonical batches, and 1,008 canonical product-ingredient links.
- PostgreSQL authentication is now verified with the configured `postgres` user. The database contains 395 documents, 3,682 products, 821 ingredients, 5,015 batches, 12,648 events, and 12,420 provenance links. RapidOCR 3.9.2 is installed and passed a one-file smoke extraction; `pymupdf4llm` remains unavailable.

## PART 1 - CURRENT STATE

### 1.1 Downloads

Collection is implemented by the seven downloader scripts under `cdsco-downloader/`. PDF counts were measured recursively:

| Source folder   |            PDFs |  JSON files |  Empty PDFs | PDFs under 1 KB |
| --------------- | --------------: | ----------: | ----------: | --------------: |
| alerts          |             300 |           1 |           0 |               0 |
| banned_drugs    |               1 |           0 |           0 |               0 |
| fdc             |              79 |           1 |           0 |               0 |
| gazette         |             486 |           1 |           0 |               0 |
| ipc_pvpi        |               1 |           0 |           0 |               0 |
| nsq_json        |               0 |           4 |           0 |               0 |
| public_notices  |             805 |           1 |           0 |               0 |
| **Total** | **1,672** | **8** | **0** |     **0** |

Total PDF size is **1.43 GB**. `priority_lists` and `_analysis` contain no source PDFs.

### 1.2 Priority Classification

The reviewed `Medicine_PDF_Classification.csv` has **1,672 rows**: **444 Important** and **1,228 Unimportant**.

| Source         | Total | Important | Unimportant |
| -------------- | ----: | --------: | ----------: |
| alerts         |   300 |       250 |          50 |
| banned_drugs   |     1 |         1 |           0 |
| fdc            |    79 |        63 |          16 |
| gazette        |   486 |        35 |         451 |
| ipc_pvpi       |     1 |         1 |           0 |
| public_notices |   805 |        94 |         711 |

The CSV classification was applied into `downloads/<source>/important/` and `unimportant/` folders. The observed moved-folder counts match the CSV: 444 Important and 1,228 Unimportant.

The reviewed CSV was the operative artifact: `classify_pdfs.py` placed 444 PDFs in `important/`, and `pdf_analysis.csv` contains 444 rows. A source-plus-filename join confirms **all 444 analysis rows belong to the 444 CSV-Important files**, with zero analysis rows from CSV-Unimportant files. Thus the first pass analyzed exactly the reviewed CSV-selected set.

### 1.3 Content Classification

`cdsco-downloader/analyze_pdfs.py` uses PyMuPDF page sampling and an 80% ratio threshold. It excludes near-empty pages, marks pages with sufficient text as TEXT, image-heavy/no-text pages as SCANNED, and the remainder as MIXED.

| Source          |      Analyzed |          TEXT |       SCANNED |       MIXED | ERROR/EMPTY |
| --------------- | ------------: | ------------: | ------------: | ----------: | ----------: |
| alerts          |           250 |           225 |            22 |           3 |           0 |
| banned_drugs    |             1 |             1 |             0 |           0 |           0 |
| fdc             |            63 |            14 |            49 |           0 |           0 |
| gazette         |            35 |            34 |             1 |           0 |           0 |
| ipc_pvpi        |             1 |             1 |             0 |           0 |           0 |
| public_notices  |            94 |            16 |            77 |           1 |           0 |
| **Total** | **444** | **291** | **149** | **4** | **0** |

No content-classification error rows were present. Analysis covers exactly the 444 reviewed CSV-Important files, not all 1,672 downloads.

### 1.4 Extraction

The text extractor uses PyMuPDF, optional `pymupdf-layout`, optional pdfplumber tables, and optional `pymupdf4llm` Markdown. Tesseract OCR renders pages through PyMuPDF, optionally preprocesses images, then uses `pytesseract.image_to_data` and reconstructs lines.

| Output                           |                                   Files | Empty |                                Tiny | Manifest result                              |
| -------------------------------- | --------------------------------------: | ----: | ----------------------------------: | -------------------------------------------- |
| `raw_extraction/text`          | 590 (295`.txt`, 295 `.tables.json`) |     0 | 57 table JSON files under 100 bytes | 43/43 extracted; 0 skipped; 0 errors         |
| `raw_extraction/ocr`           |       2 (1`.txt`, 1 `.blocks.json`) |     0 |                                   0 | RapidOCR smoke test: 1/1 extracted, 0 errors |
| `raw_extraction/ocr_tesseract` | 298 (149`.txt`, 149 `.blocks.json`) |     0 |                                   0 | 149/149 extracted; 0 skipped; 0 errors       |

The 57 tiny text artifacts are empty/minimal **table sidecars**, not empty text files. Exact empty structured outputs are listed in Section 2.2. The 149 SCANNED files were successfully processed by Tesseract. RapidOCR then successfully processed one scanned alert as a smoke test: 1 page, 2,370 characters, 41 blocks, average confidence 0.9738, and 0 errors. The remaining 148 scanned files still need a controlled comparison run.

### 1.5 Type Classification

`type_classification.py` first applies source-specific rules, filename keywords, FDC/Gazette patterns, first-page signals, and finally an `other` fallback. It copies text into type folders and does not move PDFs.

| Type                                |     Documents |
| ----------------------------------- | ------------: |
| nsq_alert                           |            37 |
| spurious_alert                      |            16 |
| drug_alert                          |           167 |
| fdc_prohibited                      |            16 |
| fdc_notification                    |            47 |
| gazette_legal                       |            34 |
| pvpi_safety                         |             1 |
| theft_recall                        |             6 |
| medical_device                      |            18 |
| ivd_alert                           |             4 |
| circular                            |             5 |
| guideline                           |             4 |
| other                               |            37 |
| **Total unique document IDs** | **392** |

Confidence distribution: `<0.70` = 37, `0.70-0.80` = 0, `0.80-0.90` = 12, `0.90-0.95` = 236, `>=0.95` = 107. The overrides artifact reports **1 override entry** (the PowerShell property count displays repeated `1` values because the JSON shape is nested).

There are 392 unique IDs but 395 structured files because 3 IDs intentionally occur in two contexts.

### 1.6 Structured Raw

| Type             |    JSON files |          Records |  Empty files | Parse failures |
| ---------------- | ------------: | ---------------: | -----------: | -------------: |
| circular         |             5 |                5 |            0 |              0 |
| drug_alert       |           167 |            5,030 |            0 |              0 |
| fdc_notification |            47 |            5,087 |            0 |              0 |
| fdc_prohibited   |            16 |            1,157 |            0 |              0 |
| gazette_legal    |            34 |               34 |            0 |              0 |
| guideline        |             4 |                4 |            0 |              0 |
| ivd_alert        |             4 |                4 |            0 |              0 |
| medical_device   |            18 |               18 |            0 |              0 |
| nsq              |            40 |            1,062 |            4 |              0 |
| other            |            37 |               37 |            0 |              0 |
| pvpi_safety      |             1 |              184 |            0 |              0 |
| spurious         |            16 |               20 |            9 |              0 |
| theft_recall     |             6 |                6 |            0 |              0 |
| **Total**  | **395** | **12,648** | **13** |    **0** |

The 13 empty files are:

```text
NSQ: 11941_NSQ_of_Typhoid_Polysaccharide_Vaccine_TYPBAR
NSQ: 12737_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Not_of_Standard_QualitySpuriousAdulteratedMisbranded_for
NSQ: 1457_Sub_Standard_Quality_of_Human_Albumin_IPEP_Albiomin_Solution_for_infusion
NSQ: 470_Notice_regarding_Draft_SOP_for_handling_of_NSQ_samples
SPURIOUS: 10504_Alert_on_falsified_versions_of_Adcetris_Injection_Brentuximab_Vedotin_Manufactured_by_Ms_Takeda_Pharmaceuticals_Company_
SPURIOUS: 10505_WHO_Alert_on_falsified_DEFITELIO_DEFIBROTIDE_80_mgml_concentrate_for_solution_for_infusion_B._No._20G20A_Exp_date_082024
SPURIOUS: 12612_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_February-2025
SPURIOUS: 12667_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_March-_2025
SPURIOUS: 12740_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_April-2025
SPURIOUS: 3256_Spurious_Drugs_--_Reward_Scheme_for_Whistle_Blowers
SPURIOUS: 3257_Report_on_countrywide_survey_for_Spurious_Drugs
SPURIOUS: 8025_Vigil_on_the_activities_of_distribution_sale_of_suspected_spurious_Tocilizumab_400_mg20_ml_Injections_in_India
SPURIOUS: 830_Notice-dated_14.09.2012_Fake_drug_menace_in_India..
```

### 1.7 CSV Exports

| CSV                                                  |  Rows |
| ---------------------------------------------------- | ----: |
| circular.csv                                         |     5 |
| drug_alert.csv                                       | 5,030 |
| fdc_notification.csv                                 | 5,087 |
| fdc_prohibited.csv                                   | 1,157 |
| gazette_legal.csv                                    |    34 |
| guideline.csv                                        |     4 |
| ivd_alert.csv                                        |     4 |
| medical_device.csv                                   |    18 |
| nsq.csv                                              | 1,038 |
| other.csv                                            |    37 |
| pvpi_safety.csv                                      |   184 |
| spurious.csv                                         |    20 |
| theft_recall.csv                                     |     6 |
| `downloads/nsq_json/csv/nsq_full_history.csv`      | 6,406 |
| `downloads/nsq_json/csv/spurious_full_history.csv` |    47 |

The per-type CSVs mirror structured records. NSQ/spurious current exports have 1,058 rows versus 1,062 structured records because empty records have no CSV row; the two full-history exports are separate historical datasets.

### 1.8 Normalization

| Artifact                       |  Lines |
| ------------------------------ | -----: |
| documents                      |    395 |
| events                         | 12,648 |
| products                       |  4,145 |
| manufacturers                  |    526 |
| batches                        |  5,026 |
| ingredients                    |    821 |
| product_ingredients_candidates |  1,018 |
| filtered_products              |    120 |
| entity_sources                 | 12,420 |
| canonical/products             |  3,703 |
| canonical/manufacturers        |    526 |
| canonical/ingredients          |    821 |
| canonical/batches              |  5,015 |
| canonical/product_ingredients  |  1,008 |

The entity review queue contains **1,411 product**, **124 manufacturer**, and **116 ingredient** pairs: **1,651 total**. Automatic merges contain **667 product** pairs. The normalization stages are implemented across `normalization/normalize_*.py`, `resolve_entities.py`, `remap_canonical.py`, and `build_entity_sources.py`.

### 1.9 Database

The PostgreSQL connection was verified with a read-only `SELECT 1` using the configured `postgres` credentials. Current row counts are:

| Table                |   Rows |
| -------------------- | -----: |
| regulatory_documents |    395 |
| manufacturers        |    526 |
| products             |  3,682 |
| ingredients          |    821 |
| product_ingredients  |  1,008 |
| batches              |  5,015 |
| regulatory_events    | 12,648 |
| entity_sources       | 12,420 |

### 1.10 Full Funnel Diagram

```text
1,672 PDFs downloaded (1.43 GB; 0 empty/tiny)
  |
  +-- reviewed priority CSV: 444 Important + 1,228 Unimportant
  |
  +-- content analysis on 444 Important:
  |       291 TEXT + 149 SCANNED + 4 MIXED; 0 ERROR/EMPTY
  |
  +-- extraction artifacts:
  |       43 TEXT-manifest files + 149 Tesseract OCR files; 0 manifest errors
  |       RapidOCR smoke test: 1 file, 2,370 chars, 41 blocks, avg confidence 0.9738
  |
  +-- type classification: 392 unique IDs / 395 structured files
  |       3 duplicate-context files; 13 files have empty records
  |
  +-- structured parsing: 12,648 records
  |
  +-- CSV export: per-type rows mirror records except 4 empty NSQ/spurious records
  |
  +-- normalization: 4,145 raw products -> 3,703 canonical products
  |                  5,026 raw batches -> 5,015 canonical batches
  |
  +-- DB load: verified, 395 documents -> 3,682 products; 12,648 events
```

The simple PDF-to-document subtraction is not a valid coverage metric: 1,228 are intentionally Unimportant, Important PDFs contain 52 duplicate-basename path collisions (444 paths but 392 unique basenames), and structured output also includes context-specific NSQ/spurious records. A path-aware manifest with a stable document ID is required before claiming that every drop-off is accounted for.

### First Pass Flowchart

```text
                         FIRST PASS
                           1,672 PDFs
                              |
                              v
+---------------------------------------------+
| 1. DOWNLOAD                                 |
| 1,672 PDFs downloaded (1.43 GB)             |
| 0 empty PDFs                                |
| 0 PDFs < 1 KB                               |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 2. PRIORITY FILTER                          |
|                                             |
| 1,672 total                                 |
| |-- 444 IMPORTANT      -> PROCESS           |
| `-- 1,228 UNIMPORTANT  -> SKIP              |
+---------------------------------------------+
                              |
                              v
                 Only 444 Important PDFs
                              |
                              v
+---------------------------------------------+
| 3. CONTENT ANALYSIS                         |
|                                             |
| 444 PDFs                                    |
| |-- 291 TEXT                               |
| |-- 149 SCANNED                            |
| |--   4 MIXED                              |
| `--   0 ERROR / EMPTY                      |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 4. EXTRACTION                               |
|                                             |
| TEXT                                        |
| -> 295 .txt + 295 table JSON                |
|                                             |
| SCANNED                                    |
| -> 149 Tesseract OCR outputs                |
|                                             |
| RapidOCR                                   |
| -> 1-file smoke test successful             |
|                                             |
| Extraction manifest errors = 0              |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 5. TYPE CLASSIFICATION                      |
|                                             |
| 392 unique document IDs                     |
| 395 structured files                        |
|                                             |
| Why 395 > 392?                              |
| -> 3 documents intentionally exist in        |
|    two contexts                             |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 6. STRUCTURED PARSING                      |
|                                             |
| 395 JSON files                              |
| -> 12,648 records                           |
|                                             |
| Empty structured files = 13                |
| Parse failures = 0                          |
|                                             |
| Empty:                                      |
| |-- NSQ       = 4                           |
| `-- Spurious  = 9                           |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 7. CSV EXPORT                               |
|                                             |
| Per-type structured records exported        |
| into CSVs                                   |
|                                             |
| Empty structured files contribute no rows   |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 8. NORMALIZATION                            |
|                                             |
| Raw candidates                              |
|                                             |
| Products            4,145                   |
|       |                                     |
|       v                                     |
| Canonical products  3,703                   |
|                                             |
| Batches             5,026                   |
|       |                                     |
|       v                                     |
| Canonical batches   5,015                   |
|                                             |
| Product-ingredient links                    |
| 1,018 -> 1,008                              |
+---------------------------------------------+
                              |
                              v
+---------------------------------------------+
| 9. DATABASE LOAD                            |
|                                             |
| PostgreSQL                                  |
|                                             |
| Documents          395                      |
| Manufacturers      526                      |
| Products         3,682                      |
| Ingredients       821                       |
| Batches         5,015                       |
| Events         12,648                       |
| Provenance      12,420                      |
+---------------------------------------------+
```

## PART 2 - SECOND PASS PLAN

### 2.1 Gap Analysis

The brief's basename check reports `downloaded=1672`, `processed=395`, `unprocessed=1228`. This count numerically matches the Unimportant CSV count and is therefore consistent with intentional priority filtering, but it is not proof of one-to-one processing because 52 duplicate basename paths exist among Important PDFs. The full unprocessed list was not written because the audit was required to avoid modifying files beyond this report.

Second-pass action: update `cdsco-downloader/lists_pdfs.py` or create a manifest utility that keys records by source plus relative path, SHA-256, and stable document ID. Expected output: one reconciliation CSV with every downloaded PDF, priority, content status, extraction status, type, parser status, and final record count.

### 2.2 Failure Inventory

Priority order for remediation:

1. Re-run the 13 empty NSQ/spurious files listed in Section 1.6 through `scripts/parse_nsq.py` and `scripts/parse_spurious.py`. Expected output: non-empty records where source content supports them, or an explicit `no_extractable_records` reason and validation flag.
2. Inspect the 57 tiny `raw_extraction/text/**.tables.json` sidecars. They are not text extraction failures; validate whether each source has a real table before treating it as a parser defect.
3. Resolve the 52 duplicate-basename collisions using source/path identity before reprocessing. Expected output: no accidental overwrite and a collision report.
4. Preserve the reviewed CSV as the documented first-pass priority source and record its provenance alongside the folder moves. Expected output: an auditable 1,672-row priority manifest with the CSV decision for every downloaded PDF.

There were no zero-byte PDFs, no extraction manifest errors, no OCR output files under 10 bytes, and no malformed structured JSON files in this audit.

### 2.3 OCR Engine Readiness

Observed in `.venv/Scripts/python.exe`:

| Component              | Result                                                   |
| ---------------------- | -------------------------------------------------------- |
| Tesseract              | Available, version 5.5.3.20260724                        |
| PyMuPDF                | Available, version 1.28.2                                |
| `rapidocr`           | Available, version 3.9.2; ONNXRuntime engine initialized |
| `pymupdf4llm` import | Failed: module not found                                 |

RapidOCR is installed and the controlled command `raw_extraction/extract_ocr.py --limit 1 --workers 1` succeeded. Its manifest reports 1 file, 1 page, 2,370 chars, 41 blocks, average confidence 0.9738, and 0 errors. Next run it in batches over the remaining 148 SCANNED files, compare against Tesseract, and retain Tesseract as fallback until measured quality wins. Install `pymupdf4llm` separately only if Markdown extraction is required.

### 2.4 Parser Inventory

Existing parsers:

- `scripts/parse_drug_alert.py`: drug-alert records.
- `scripts/parse_fdc.py`: FDC notifications and prohibited FDC records.
- `scripts/parse_nsq.py`: NSQ records.
- `scripts/parse_spurious.py`: spurious records.
- `scripts/parse_prose.py`: Gazette, PvPI, theft/recall, medical device, IVD, circular, guideline, and other prose documents.

Type classification has 13 types, but parser coverage is concentrated in these five scripts. The immediate parser gap is not an absent type handler; it is low-confidence or empty extraction for NSQ/spurious and quality validation for irregular tables. Improve `parse_nsq.py` and `parse_spurious.py` around alternate headers, merged cells, and OCR punctuation. Add fixture tests under a new parser test location using the 13 empty documents and representative 57 tiny-table cases. Expected output: deterministic records, row-level provenance, and regression counts.

### 2.5 Remediation Plan

| Work item                | Files/scripts                                                        | Expected output                                                                   |
| ------------------------ | -------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Stable coverage manifest | `cdsco-downloader/lists_pdfs.py`, new audit/reconciliation utility | All 1,672 PDF paths mapped without basename collisions                            |
| Reprocess empty records  | `scripts/parse_nsq.py`, `scripts/parse_spurious.py`              | 13 files classified as recovered or explicitly unextractable                      |
| RapidOCR comparison      | `raw_extraction/extract_ocr.py`, `requirements.txt`              | 1-file smoke test passed; process remaining 148 SCANNED files and compare quality |
| Hybrid MIXED extraction  | `raw_extraction/extract_text.py`, `extract_ocr.py`               | 4 MIXED files combine text and OCR by page                                        |
| Table parser hardening   | `scripts/parse_fdc.py`, `parse_nsq.py`, `parse_spurious.py`    | Correct columns, dates, products, batches, and source row references              |
| Validation fixtures      | `scripts/validate_records.py`, parser tests                        | Counts and schema checks fail loudly on regressions                               |
| DB verification          | `database/load.py`, environment credentials/configuration          | Authentication and read-only table-count query verified                           |

### 2.6 AI Layer Placement

| Stage                  | Current                              | Concrete AI upgrade                                                                                                    |
| ---------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| Download               | Deterministic downloader scripts     | No AI; use checksums, retries, and change detection                                                                    |
| Priority               | Filename rules plus reviewed CSV     | Cheap Claude API/OpenAI classifier only for rule/CSV disagreements; preserve human decision                            |
| Content classification | PyMuPDF heuristic                    | Vision model such as GPT-4.1 vision or Claude vision for ambiguous MIXED/layout cases                                  |
| Scanned extraction     | Tesseract plus RapidOCR smoke test   | RapidOCR comparison, then Qwen2-VL local VLM or Claude/GPT vision for low-confidence complex pages                     |
| Type classification    | Rule-based, 37 below 0.70 confidence | LLM fallback for confidence`<0.80`, returning type plus evidence and calibrated confidence                           |
| Table parsing          | Regex/table heuristics               | Structured LLM extraction for irregular FDC/NSQ/spurious tables, constrained by JSON Schema and source snippets        |
| Prose parsing          | Keyword and regex extraction         | NER pass using Claude/OpenAI structured output for product, batch, manufacturer, date, action, and notification number |
| Normalization          | RapidFuzz/rules plus review queue    | AI candidate scoring for 1,651 review pairs; auto-accept only high-margin matches and retain evidence                  |
| Validation             | SQL and deterministic checks         | Anomaly detection for unusual dates, quantities, duplicate IDs, and entity merges; humans approve material anomalies   |

Cursor/Claude Code/Antigravity are best used as development operators around these deterministic jobs: generate parser fixtures, run regression batches, inspect failed manifests, and propose patches. They should not silently write production records. Every AI result should be schema-validated, versioned with prompt/model metadata, and routed to a review queue when confidence or margin is low.

### 2.7 Roadmap

1. **Milestone 2A - Reprocess failed extraction and empty records:** run RapidOCR over the remaining 148 scanned files, compare 149 scanned files, and repair the 13 NSQ/spurious empty outputs. Output: clean manifests and an explicit failure inventory.
2. **Milestone 2B - Coverage and classifier reconciliation:** add stable path/hash IDs, reconcile reviewed versus rule priority, and route low-confidence type assignments. Output: one auditable 1,672-row status manifest.
3. **Milestone 2C - Parser quality:** harden FDC/NSQ/spurious/table handling and add regression fixtures for all current empty and tiny-table cases. Output: repeatable parser counts and source-row provenance.
4. **Milestone 2D - AI-assisted entity review:** score the 1,651 review pairs, auto-accept only validated high-confidence matches, and expose the remainder for human review. Output: versioned merge decisions with evidence.
5. **Milestone 2E - Continuous ingestion:** add source change detection, checksum-based idempotency, incremental parsing, and DB reconciliation reports. Output: scheduled runs with alerts for new or changed documents.
6. **Milestone 2F - Production deployment:** authenticate and verify PostgreSQL loads, pin OCR/model dependencies, add monitoring, backups, data-quality gates, and rollbackable dataset versions. Output: a reproducible production pipeline with measurable SLA and audit trail.
