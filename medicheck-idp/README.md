# MediCheck IDP Pipeline V2 — Intelligent Document Processing

This system is aligned with MediCheck's Version 2 Intelligent Document Processing (IDP) pipeline. V2 uses separate processing stages, structured taxonomies, explicit decision rules, validated stage contracts, and deliberate/limited LLM usage to improve extraction quality, traceability, and processing efficiency.

![MediCheck IDP Pipeline Architecture](docs/MediCheck%20IDP%20Pipeline%20Architecture.png)

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

- `config/taxonomy/tables.yaml` — Defines table archetypes (A–AV), canonical columns, header variants, layouts, and default classifications.
- `config/taxonomy/paragraphs.yaml` — Defines paragraph archetypes (P1–P30, including P3b and P3c), their meanings, classifications, and table mappings.
- `config/taxonomy/usability_rules.yaml` — Defines direct-match eligibility, required evidence, legal-status handling, and record-level decision rules.
- `config/taxonomy/cluster_routing.yaml` — Provides exploratory cluster-based routing hints; it does not determine the final classification.
- `config/taxonomy/sources.yaml` — Maintains source document references and corpus metadata for traceability and testing.
- `config/taxonomy/meta.yaml` — Stores taxonomy versions, shared field definitions, and unresolved design decisions.
- `idp/schemas/taxonomy.py` — Defines Pydantic models used to validate the YAML structures.

### How They Are Used

1. **Load:** Read the YAML files at application or worker startup.
2. **Validate:** Use Pydantic to validate field types, required properties, and allowed values. Validate cross-file references separately.
3. **Match:** Normalize extracted table headers or paragraph content and compare them against the relevant taxonomy definitions.
4. **Apply rules:** Use `usability_rules.yaml` to evaluate evidence requirements, direct-match readiness, and applicable classification conditions.
5. **Return results:** Produce the assigned archetype, app classification, evidence, reason, and review status as applicable. Preserve the taxonomy version and source references for auditing.

**Principle:** Taxonomies define *what the content is*; rules define *how the system handles it*. Cluster routing assists triage, while source references and metadata support traceability and version control.

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
