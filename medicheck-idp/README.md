# MediCheck IDP Pipeline V2 — Intelligent Document Processing

This system is aligned with MediCheck's Version 2 Intelligent Document Processing (IDP) pipeline. V2 uses separate processing stages, structured taxonomies, explicit decision rules, validated stage contracts, and deliberate/limited LLM usage to improve extraction quality, traceability, and processing efficiency.

![MediCheck IDP Pipeline Architecture](<docs/idp_architecture.png>)

## Proposed Pipeline and Implementation Status

The target pipeline classifies a lightweight view of the extraction before routing content for detailed reconstruction. The stage numbers and flow below match the updated architecture image.

```text
PDF Input
  → Document Profiler
  → Extraction
  → Classification Context Builder
  → Classifier
  → Content Filtering and Routing
  → Reconstruction
  → Parsing
  → Validation
  → Normalization
  → Database Ingestion
```

| Stage | Name | Output | Status |
|---|---|---|---|
| 0 | PDF Input | `00_manifest/document_manifest.json` | Implemented |
| 1 | Document Profiler | `01_profiler/profile.json` | Implemented |
| 2 | Extraction | `02_extraction/index.json`, batches, Markdown and crops | Implemented |
| 3 | Classification Context Builder | `03_classification_context/classification_context.json` | Implemented |
| 4 | Classifier | `04_classifier/classification.json` | Implemented; consumes classification context |
| 5 | Content Filtering and Routing | `processing_manifest.json` | Planned |
| 6 | Reconstruction | `structured_document.json` | Planned; runs only after routing |
| 7 | Parsing | `parsed_records.json` | Existing code; target artifact-flow integration planned |
| 8 | Validation | `validated_records.json` | Existing code; target artifact-flow integration planned |
| 9 | Normalization | `normalized_records.json` | Existing code; target artifact-flow integration planned |
| 10 | Database Ingestion | `ingestion_result.json` | Planned |

### Stage Responsibilities

- **0 — PDF Input (implemented):** `idp.stages.manifest.run()` hashes the source bytes for a stable document ID and writes an idempotent `document_manifest.json` with the file name, byte size, SHA-256, and first UTC upload time.
- **1 — Document Profiler (implemented):** PyMuPDF inspects page text, images, vector drawing items, and layout to route pages as digital, scanned, hybrid, or blank. Sparse vector marks are judged by drawing-item count; repeated nonzero image xrefs are suppressed only as hybrid OCR regions.
- **2 — Extraction (implemented):** PyMuPDF supplies the JSON text/table evidence and RapidOCR handles scanned pages or profiled hybrid regions. Pinned PyMuPDF4LLM produces page Markdown for digital pages and the native portion of hybrid pages with its own OCR and image export disabled. Page references, normalized visible-space bboxes, extraction provenance, and crop references remain in the JSON items.
- **3 — Classification Context Builder (implemented):** Read page Markdown and raw extraction batches to prepare Markdown paragraphs with heading paths, line ranges, and available geometry, plus tables with headers and deterministic first/middle/last samples. Quality metadata reports empty content and failed pages. This artifact is classifier input only—not the source for parsing or ingestion.
- **4 — Classifier:** Apply deterministic taxonomy rules first and use an LLM fallback only when semantic interpretation is needed. Assign configured A–AV and P1–P30 labels and retain confidence/evidence where supported.
- **5 — Content Filtering and Routing:** Use classification results and processing rules to select sections, paragraphs, and tables for detailed reconstruction, and record routing decisions.
- **6 — Reconstruction:** Rebuild only selected content from extraction evidence into a detailed, unified document schema, retaining source references, page numbers, geometry, and provenance.
- **7 — Parsing:** Convert the canonical structured document into domain records using Python, taxonomy-specific rules, and Pydantic models; use an LLM only when appropriate and necessary.
- **8 — Validation:** Check types, required fields, domain rules, and cross-field consistency; retain validation errors and warnings rather than silently changing uncertain values.
- **9 — Normalization:** Standardize values with controlled mappings while preserving originals where traceability is required; do not guess missing or unclear values.
- **10 — Database Ingestion:** Map normalized records to Supabase/PostgreSQL, apply duplicate checks and insert/upsert rules, and record outcomes for audit and retry.

### Artifact Boundaries and Design Decisions

- All outputs are stored under `data/artifacts/<document_id>/`; stage-prefixed
  directories keep artifacts together and ordered. Stages 05–10 are planned and
  do not create directories or placeholder files yet.
- Implemented outputs:

```text
data/artifacts/<document_id>/
├── 00_manifest/document_manifest.json
├── 01_profiler/profile.json
├── 02_extraction/
│   ├── index.json
│   ├── batches/
│   ├── markdown/
│   └── crops/
├── 03_classification_context/classification_context.json
└── 04_classifier/classification.json
```

- `classification_context.json` is a lightweight classifier input. It is not a reconstructed document and must not be used as the source of truth for parsing or ingestion.
- `structured_document.json` is a planned detailed representation of content selected for processing; it will be the input to parsing and downstream stages.
- Classification precedes detailed reconstruction so irrelevant content does not incur unnecessary reconstruction work.
- Preserve page numbers, bounding boxes, source element IDs, and extraction-method details wherever available. Keep OCR uncertainty explicit; do not invent missing values.

**Implementation boundary:** The local `main.py` entry point runs stages 0–3 in order: manifest, profiler, extractor, then classification context builder. Stage 4 classifier is implemented separately and consumes `classification_context.json`; routing and post-routing reconstruction are not implemented yet. Parsing, validation, normalization, and ingestion remain planned.

**LLM policy:** Prefer deterministic extraction, normalization, and taxonomy matching first. Use an LLM selectively for genuinely ambiguous semantic classification or recovery cases; validate its output against the relevant schema and source evidence. Model confidence or a generated summary must not be treated as proof of legal effect. Preserve evidence quotes, source locations, taxonomy/rule versions, and review flags for auditability.

## Taxonomies and Rules

MediCheck IDP uses YAML files to maintain structured taxonomies, classification rules, and source references.

### Files and Responsibilities

- `rules/taxonomy/tables.yaml` — Defines table archetypes (A–AV, plus the NU fallback), canonical columns, header variants, layouts, and default classifications.
- `rules/taxonomy/paragraphs.yaml` — Defines paragraph archetypes (P1–P30, including P3b and P3c; P4 is merged into P3), their meanings, classifications, and table mappings.
- `rules/usability_rules.yaml` — Defines direct-match eligibility, required evidence, legal-status handling, and record-level decision rules.
- `rules/classification_rules.yaml` — Defines how the classifier recognises archetypes: unit settings, thresholds, table title cues, paragraph patterns, legal-status patterns, label conflicts and LLM settings.
- `rules/cluster_routing.yaml` — Provides exploratory cluster-based routing hints; it does not determine the final classification.
- `rules/taxonomy/meta.yaml` — Stores taxonomy versions, shared field definitions, and design decisions (open and resolved).
- `idp/schemas/taxonomy.py` — Defines Pydantic models used to validate the YAML structures and their cross-file references.

### How They Are Used

1. **Load:** Read the YAML files at application or worker startup.
2. **Validate:** Use Pydantic to validate field types, required properties, and allowed values. Validate cross-file references separately.
3. **Match:** Normalize extracted table headers or paragraph content and compare them against the relevant taxonomy definitions.
4. **Apply rules:** Use `usability_rules.yaml` to evaluate evidence requirements, direct-match readiness, and applicable classification conditions.
5. **Return results:** Produce the assigned archetype, app classification, evidence, reason, and review status as applicable. Preserve the taxonomy version and source references for auditing.

**Principle:** Taxonomies define *what the content is*; rules define *how the system handles it*. Cluster routing assists triage, while source references and metadata support traceability and version control.

## Stage 2: Extraction (`idp/stages/extractor/`)

The target extraction contract retains both readable content and the evidence needed for later processing. Markdown is useful for reading and classification, but is not a replacement for page layout, geometry, or extraction provenance.

- Digital PDFs: PyMuPDF produces the page's JSON items, and pinned PyMuPDF4LLM (`1.28.2`) produces Markdown in page chunks. The extractor explicitly selects legacy mode once (`use_layout(False)`); chunks are assigned by the 1-based page number in metadata, not by return order.
- Scanned PDFs: RapidOCR items are sorted and grouped into simple Markdown paragraphs using their visible-page point geometry. PyMuPDF4LLM is not called for scanned pages.
- Hybrid PDFs: PyMuPDF4LLM provides native Markdown, followed by one labelled blockquote per RapidOCR region. OCR region order is retained, but its position relative to native Markdown is not; the blockquotes are not a layout reconstruction.
- PyMuPDF4LLM legacy mode does not invoke its own OCR; its layout/OCR mode is not used. Image export and embedding are disabled. Native table detection explicitly bypasses PyMuPDF's optional layout-table gate so importing or running PyMuPDF4LLM cannot change the JSON table results. JSON items remain the source of truth for detailed extraction; Markdown is a companion artifact, not a replacement.

The extractor executes the profiler's page-level plan and writes a unified `PageExtraction` contract for context building and later reconstruction. Native text keeps its font runs; ruled tables retain cell text and nullable merged cells; scanned pages use RapidOCR, while hybrid pages OCR only the profiled image regions and preserve those crops as image artifacts. Each page also has `02_extraction/markdown/pNNN.md`; crops are stored under `02_extraction/crops/`. The additive `markdown_ref`, `markdown_source`, and `markdown_error` fields record its Markdown outcome. `ExtractionIndex.complete` is false if extraction or Markdown failed.

- Item boxes are normalized to `0..1` in the visible page coordinate system (after page
  rotation). OCR rendering is capped by `ocr_max_px`; configure DPI, table strategy, and OCR
  threads with `ExtractorConfig`.
- Table detection uses `lines_strict` by default to avoid treating text strokes as grid lines.
  Use `lines` for open-border tables; table candidates are not discarded solely because they
  have many columns or a narrow column. Pages hinted as containing a table but yielding none
  carry a warning.
- Each page reports `success`, `skipped`, or `failed`. A page failure is logged and included
  in the extraction index; Markdown failures are separately reported and cannot be hidden
  by a successful item-extraction status. Cached pages are reused only when the PDF hash,
  profiler plan, extractor version, configuration, Markdown artifact, and image crops match.
- PyMuPDF4LLM may emit Markdown pipe tables. The context builder removes these from paragraph
  content because table headers and geometry come from the extraction JSON items.
- All artifacts share the `data/artifacts/<doc_id>/` base. Stage artifacts are written only
  to the numbered directories shown above; the previous unnumbered paths are not read as caches.
  S3 artifact URIs are not supported yet.
- Profiler and extractor logs carry the abbreviated document hash and page identifier;
  extraction also reports per-batch page counts and elapsed time.

Run the complete local pipeline from this project directory:

```powershell
python main.py "data\batches\example.pdf"
```

Add `--force` to re-run each stage instead of reusing its cached artifacts. The command
prints the generated manifest, profile, extraction index, and classification-context paths.

## Stage 3: Classification Context Builder (`idp/stages/classification_context/service.py`)

The builder accepts profile and extraction results from the local orchestrator, or ensures
those artifacts exist when invoked on its own. It then writes a classifier-only
`03_classification_context/classification_context.json` at `data/artifacts/<sha256>/`.
Paragraphs are sourced from page Markdown with heading paths, exact line ranges, source methods,
and page/artifact references. A paragraph bbox is emitted only when every Markdown content line
can be matched unambiguously to extracted text-line geometry; otherwise it is `null`. Tables use
extraction headers, deterministic first/middle/last sample rows, dimensions, and point-space
bboxes. Per-page source references retain geometry for tables and paragraphs. `pages` is an array
in the contract; the builder keeps continuation tables separate and records evidence-backed
continuation links rather than merging their rows. The optional document profile gives page-type
counts. Quality metadata reports empty classifier context, OCR pages without classifiable content,
and failed extraction/Markdown pages; page-number furniture is excluded. Incomplete extraction
can still produce a context artifact for diagnosis, but the classifier rejects an empty context.
The artifact cache key includes the extraction content and builder version. Missing or invalid
referenced artifacts stop the build with an explicit error.

```python
from idp.stages.classification_context import run

context = run(r"data\batches\example.pdf", document_id="source-folder/example.pdf")
```

This artifact is classifier input, not a reconstruction. Markdown text is grouped into section-level chunks (up to 2,000 characters), with headings represented in `section_path` rather than as standalone entries. It contains chunk text with page arrays, optional point-space bboxes, Markdown line ranges, and traceable source references, plus tables with headers and up to three representative rows. Detailed reconstruction is a separate planned stage after content filtering and routing.

## Current Classifier (`idp/stages/classifier/`)

```text
ClassificationContext
  └─ units.py       page-level table contexts; paragraphs grouped by heading ("section") or chunks
  └─ matcher.py     tables: header cells vs layout columns (fuzzy, OCR-tolerant) + title/caption cues
                    paragraphs: pattern rules + title/heading cues; legal status
  └─ resolver.py    accept, or escalate on: no rule match | rule conflict | low confidence
  └─ llm_fallback.py  provider-neutral prompt + JSON schema; every model label needs a verbatim quote
  └─ usability.py   app class, priority, gate and record rules from the taxonomy
  └─ service.py     ClassifiedDocument (idp/schemas/classified.py)
```

- Every unit is recorded: `classified`, `needs_review` or `not_a_record`, with its labels (several allowed for paragraphs, one for tables), evidence, rule IDs, rule candidates and any escalation.
- `legal_status` is a separate field (DEC-10). `direct_match_ready` is not decided here; each label lists the `gate_ids` that decide it after parsing.
- Tables whose records need row-level handling (C split, K statuses, mixed products) carry `requires_record_split` and the `record_rule_ids` for the parser.
- Outputs record the taxonomy and rule versions and a hash of all rule files.
- The classifier writes `04_classifier/classification.json` under the document's artifact
  directory; its input path does not control the output location.

### LLM fallback

Configured only through the environment (see `.env.example` and `config/settings.py`):

```text
IDP_LLM_PROVIDER=none | bedrock | gemini | package.module:ClassName
IDP_LLM_MODEL=<model or inference-profile id>
```

`idp/models/llm.py` defines the provider interface (`generate_json`) and the registry; `bedrock.py` and `gemini.py` implement it. A new provider is one class plus an environment variable. Providers use schema-constrained output where the model supports it, and otherwise prompt for JSON; the classifier validates every answer the same way. With `none`, escalated units are written as `needs_review`. Answers can be cached (`IDP_LLM_CACHE_DIR`) so re-runs are identical and free.

### Run and test

```bash
python -m idp.stages.classifier --input <file|dir>
python -m pytest
```

## Current Folder Structure

```text
medicheck-idp/
├── .env.example
├── .gitignore
├── main.py
├── README.md
├── requirements.txt
├── config/
│   └── settings.py
├── data/
│   ├── artifacts/
│   └── batches/
├── idp/
│   ├── models/
│   │   ├── gemini.py
│   │   └── gliner.py
│   ├── schemas/
│   │   ├── classified.py
│   │   ├── common.py
│   │   ├── extraction.py
│   │   ├── manifest.py
│   │   ├── profile.py
│   │   ├── records.py
│   │   ├── classification_context/
│   │   │   ├── __init__.py
│   │   │   └── service.py
│   │   └── taxonomy.py
│   ├── stages/
│   │   ├── manifest.py
│   │   ├── classifier/
│   │   │   ├── matcher.py
│   │   │   ├── service.py
│   │   │   ├── taxonomy.py
│   │   │   └── usability.py
│   │   ├── extractor/
│   │   │   ├── digital.py
│   │   │   ├── geometry.py
│   │   │   ├── markdown.py
│   │   │   ├── ocr.py
│   │   │   └── service.py
│   │   ├── normalizer/
│   │   │   └── service.py
│   │   ├── parser/
│   │   │   ├── paragraph_parser.py
│   │   │   └── table_parser.py
│   │   ├── profiler/
│   │   │   └── service.py
│   │   └── validator/
│   │       └── service.py
│   └── storage/
│       ├── artifacts.py
│       └── db.py
├── rules/
│   ├── build/
│   │   └── taxonomy.json
│   ├── cluster_routing.yaml
│   ├── taxonomy/
│   │   ├── meta.yaml
│   │   ├── paragraphs.yaml
│   │   └── tables.yaml
│   └── usability_rules.yaml
└── tests/
    ├── test_classifier.py
    ├── test_classification_context.py
    ├── test_contracts.py
    ├── test_extractor.py
    ├── test_manifest.py
    └── test_profiler.py
```
