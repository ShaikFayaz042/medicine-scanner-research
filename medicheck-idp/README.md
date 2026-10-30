# MediCheck IDP Pipeline V2 — Intelligent Document Processing

This system is aligned with MediCheck's Version 2 Intelligent Document Processing (IDP) pipeline. V2 uses separate processing stages, structured taxonomies, explicit decision rules, validated stage contracts, and deliberate/limited LLM usage to improve extraction quality, traceability, and processing efficiency.

![MediCheck IDP Pipeline Architecture](<docs/MediCheck%20IDP%20Pipeline%20Architecture.png>)

## IDP V2: Processing Overview

Source PDF → Profiler → Extractor → Structurer → Classifier → Parser → Validator → Normalizer → Ingestion

- **Profiler:** Inspects document and page characteristics, detects likely content/layout regions, and creates an extraction plan.
- **Extractor:** Uses the planned extraction path—for example, native PDF text extraction for digital pages and OCR for scanned or image-based content.
- **Structurer:** Organizes extracted content into separate table and paragraph records while preserving document/page provenance.
- **Classifier:** Matches headers or paragraph content against the taxonomy libraries, then applies the relevant usability and evidence rules. A document may contain multiple independently classified records.
- **Parser, Validator, and Normalizer:** Convert classified content into structured records, validate required evidence and status fields, and normalize values without losing the original source wording.
- **Ingestion:** Stores approved artifacts and records in their designated storage/database destinations when that stage is enabled.

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

## Stage 4 → 5 contract

The structurer writes one JSON per PDF, validated by `idp/schemas/structured.py` (`StructuredDocument`):

- `document`: id, sha256, page count, and the scraper title (treated as content; file names are never used for classification).
- `pages[].blocks`: headings (with level), paragraphs, list items, captions, running headers/footers, and `table_ref` blocks marking where each table sits; every block has bbox, origin (`text_layer`/`ocr`), confidence and language.
- `tables`: logical tables. A table that continues over several pages is one entry with `segments` per page. Header rows are delivered separately from body rows.

## Stage 5: Classifier (`idp/stages/classifier/`)

```text
StructuredDocument
  └─ units.py       tables: one unit per logical table
                    paragraphs: blocks grouped by heading ("section") or into chunks ("chunk")
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

### LLM fallback

Configured only through the environment (see `.env.example` and `config/settings.py`):

```text
IDP_LLM_PROVIDER=none | bedrock | gemini | package.module:ClassName
IDP_LLM_MODEL=<model or inference-profile id>
```

`idp/models/llm.py` defines the provider interface (`generate_json`) and the registry; `bedrock.py` and `gemini.py` implement it. A new provider is one class plus an environment variable. Providers use schema-constrained output where the model supports it, and otherwise prompt for JSON; the classifier validates every answer the same way. With `none`, escalated units are written as `needs_review`. Answers can be cached (`IDP_LLM_CACHE_DIR`) so re-runs are identical and free.

### Run and test

```bash
python -m idp.stages.classifier --input <file|dir|s3://bucket/prefix> --output <dir|s3://bucket/prefix>
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
│   │   ├── profile.py
│   │   ├── records.py
│   │   ├── structured.py
│   │   └── taxonomy.py
│   ├── stages/
│   │   ├── classifier/
│   │   │   ├── matcher.py
│   │   │   ├── service.py
│   │   │   ├── taxonomy.py
│   │   │   └── usability.py
│   │   ├── extractor/
│   │   │   ├── digital.py
│   │   │   ├── ocr.py
│   │   │   └── service.py
│   │   ├── normalizer/
│   │   │   └── service.py
│   │   ├── parser/
│   │   │   ├── paragraph_parser.py
│   │   │   └── table_parser.py
│   │   ├── profiler/
│   │   │   └── service.py
│   │   ├── structurer/
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
    ├── test_extractor.py
    └── test_profiler.py
```
