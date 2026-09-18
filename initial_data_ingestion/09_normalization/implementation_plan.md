# Medicine Regulatory Data ETL Pipeline — Final Implementation Plan

## 0. Purpose

This document is the frozen implementation plan for converting parsed government-regulatory JSON data into validated, normalized PostgreSQL data.

The pipeline is designed around four principles:

1. **Deterministic identity** — use stable canonical keys, not runtime counters.
2. **Lineage** — every normalized record must remain traceable to its source document and source record.
3. **Staging before database** — JSON is converted into normalized CSV staging tables, validated, and only then loaded into PostgreSQL.
4. **No invented data** — missing or ambiguous information becomes `NEEDS_REVIEW`; the ETL must not invent entities.

This plan covers the ETL/data-normalization system only. It does not redesign the existing scraper architecture.

---

# 1. Frozen Architecture

```text
RAW / PARSED JSON FILES
          |
          v
  Source Lineage Assignment
          |
          v
     Field Extraction
          |
          v
     Canonicalization
          |
          v
     Entity Resolution
          |
          v
   Deterministic Canonical Keys
          |
          v
   -------------------------
   |      STAGING CSVs      |
   |------------------------|
   | regulatory_documents   |
   | raw_source_records     |
   | organizations          |
   | ingredients            |
   | products               |
   | product_ingredients    |
   | product_organizations  |
   | batches                |
   | regulatory_events      |
   | normalization_manifest |
   -------------------------
          |
          v
       VALIDATION
          |
     +----+----+
     |         |
   VALID     REVIEW / FAILED
     |
     v
   PostgreSQL
     |
     v
  Key -> BIGSERIAL ID Resolution
     |
     v
    UPSERT
```

## Bronze → Silver → Gold interpretation

- **Bronze:** source JSON and raw extracted information.
- **Silver:** canonical entities and normalized staging CSVs.
- **Gold:** validated relational PostgreSQL records used by the application.

The `normalization_manifest.csv` acts as the control/lineage layer across all stages.

---

# 2. Target Document Types

The current accepted document types are:

| Doc Type | Type                                          | Main purpose                                      |
| -------- | --------------------------------------------- | ------------------------------------------------- |
| Doc 1    | Banned Drugs                                  | Prohibited drug lists / Section 26A notifications |
| Doc 2    | PvPI Safety Alerts                            | Pharmacovigilance / adverse drug reaction alerts  |
| Doc 3    | NSQ Drugs                                     | State laboratory quality-failure alerts           |
| Doc 4    | Spurious Drugs                                | Counterfeit/fake drug alerts                      |
| Doc 5    | CDSCO Drug Alerts                             | CDSCO central laboratory quality alerts           |
| Doc 6    | Legacy CDSCO Monthly Alerts                   | Historical quality-failure alerts                 |
| Doc 7    | Medical Device & IVD Safety Alerts            | Device safety / recall / regulatory alerts        |
| Doc 8    | Approved New Drugs & Marketing Authorizations | Approval / marketing authorization information    |
| Doc 11   | NOC & Import Permissions / FDC                | CDSCO permission / permitted FDC records          |

A single PDF may contain multiple row-level event types. Therefore:

- `regulatory_documents.document_type` describes the document as a whole.
- `regulatory_events.event_type` describes the specific event represented by a row/record.

For mixed documents, `document_type` may be `MIXED_ALERT` while row-level events can be `NSQ`, `SPURIOUS`, etc.

## Frozen taxonomy rules

The following controlled vocabularies are frozen for the current ETL implementation. Do not introduce ad-hoc values such as `BATCH_OR_PRODUCT` or `MULTI_BATCH`. If a genuinely new concept is discovered later, update the taxonomy and migration deliberately rather than writing a free-form value.

### `scope`

```text
BATCH
PRODUCT
INGREDIENT
COMBINATION
DOCUMENT
```

### `product_category`

```text
DRUG
MEDICAL_DEVICE
IVD_KIT
VACCINE
FDC
COSMETIC
```

### `event_type`

```text
BANNED
PROHIBITED
NSQ
SPURIOUS
ADR
RECALL
APPROVAL
NOC
IMPORT_PERMISSION
SAFETY_ADVISORY
SUSPENSION
WITHDRAWAL
UNDER_INVESTIGATION
OTHER
```

### `document_type`

```text
BANNED_DRUGS
PVPI_ADR
NSQ_STATE
SPURIOUS
NSQ_CDSCO
LEGACY_CDSCO
MEDICAL_DEVICE
APPROVED_DRUGS
NOC_IMPORT_FDC
MIXED_ALERT
UNKNOWN
```

The exact definitions and mapping guidance for `event_type` are maintained separately in `event_type_taxonomy.md`.

---

# 3. Final Database Model

## 3.1 Organizations

Represents reusable organizations such as:

- manufacturers
- importers
- applicants
- marketing authorization holders
- reporting laboratories
- regulatory organizations

```sql
CREATE TABLE organizations (
    organization_id BIGSERIAL PRIMARY KEY,
    organization_key VARCHAR(64) UNIQUE NOT NULL,
    organization_name VARCHAR(500) NOT NULL,
    normalized_name VARCHAR(500),
    address TEXT,
    state VARCHAR(100),
    country VARCHAR(100) DEFAULT 'India',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

## 3.2 Ingredients

```sql
CREATE TABLE ingredients (
    ingredient_id BIGSERIAL PRIMARY KEY,
    ingredient_key VARCHAR(64) UNIQUE NOT NULL,
    ingredient_name VARCHAR(500) NOT NULL,
    normalized_name VARCHAR(500) UNIQUE,
    cas_number VARCHAR(100)
);
```

## 3.3 Products

```sql
CREATE TABLE products (
    product_id BIGSERIAL PRIMARY KEY,
    product_key VARCHAR(64) UNIQUE NOT NULL,
    product_name VARCHAR(500) NOT NULL,
    normalized_name VARCHAR(500),
    brand_name VARCHAR(500),
    dosage_form VARCHAR(200),
    strength VARCHAR(200),
    product_category VARCHAR(50) NOT NULL CHECK (
        product_category IN (
            'DRUG',
            'MEDICAL_DEVICE',
            'IVD_KIT',
            'VACCINE',
            'FDC',
            'COSMETIC'
        )
    )
);
```

## 3.4 Product ↔ Ingredient

```sql
CREATE TABLE product_ingredients (
    product_id BIGINT REFERENCES products(product_id) ON DELETE CASCADE,
    ingredient_id BIGINT REFERENCES ingredients(ingredient_id) ON DELETE CASCADE,
    ingredient_strength VARCHAR(200),
    PRIMARY KEY (product_id, ingredient_id)
);
```

## 3.5 Product ↔ Organization

```sql
CREATE TABLE product_organizations (
    product_id BIGINT REFERENCES products(product_id) ON DELETE CASCADE,
    organization_id BIGINT REFERENCES organizations(organization_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (
        role IN (
            'MANUFACTURER',
            'IMPORTER',
            'APPLICANT',
            'MARKETING_AUTHORIZATION_HOLDER'
        )
    ),
    PRIMARY KEY (product_id, organization_id, role)
);
```

## 3.6 Regulatory Documents

```sql
CREATE TABLE regulatory_documents (
    document_id BIGSERIAL PRIMARY KEY,
    source_organization VARCHAR(200) NOT NULL,
    source_document_id VARCHAR(200),

    filename VARCHAR(500) NOT NULL,
    document_title TEXT,
    publication_date DATE,
    reporting_period VARCHAR(100),

    source_url TEXT NOT NULL,
    file_hash CHAR(64) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    document_type VARCHAR(100) CHECK (
        document_type IN (
            'BANNED_DRUGS',
            'PVPI_ADR',
            'NSQ_STATE',
            'SPURIOUS',
            'NSQ_CDSCO',
            'LEGACY_CDSCO',
            'MEDICAL_DEVICE',
            'APPROVED_DRUGS',
            'NOC_IMPORT_FDC',
            'MIXED_ALERT',
            'UNKNOWN'
        )
    ),

    UNIQUE (source_organization, source_document_id)
);
```

`source_document_id` is the preferred source-level deduplication key when the source provides a stable ID. `file_hash` is the fallback identity/deduplication mechanism.

**ID note:** `document_id` is a PostgreSQL `BIGSERIAL` surrogate ID used for internal foreign-key joins. `source_document_id` is the source-provided `VARCHAR` identifier used for source-level identity/deduplication. Lineage joins must use the internal `document_id` together with `source_record_id`; do not confuse the two IDs.

## 3.7 Raw Source Records

```sql
CREATE TABLE raw_source_records (
    raw_source_id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES regulatory_documents(document_id)
        ON DELETE CASCADE,

    source_record_id VARCHAR(200) NOT NULL,
    page_number INT,
    source_location TEXT,
    extraction_method VARCHAR(50), -- TEXT / OCR / MIXED
    source_text TEXT,
    raw_json JSONB,
    extraction_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (document_id, source_record_id)
);
```

## 3.8 Batches

```sql
CREATE TABLE batches (
    batch_id BIGSERIAL PRIMARY KEY,
    batch_key VARCHAR(64) UNIQUE NOT NULL,

    product_id BIGINT REFERENCES products(product_id),
    organization_id BIGINT REFERENCES organizations(organization_id),

    batch_number VARCHAR(200) NOT NULL,
    manufacturing_date DATE,
    expiry_date DATE,

    UNIQUE (product_id, organization_id, batch_number)
);
```

A batch is an identity record. Regulatory state belongs to regulatory events, not to the batch master itself.

## 3.9 Regulatory Events

```sql
CREATE TABLE regulatory_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(64) UNIQUE NOT NULL,

    document_id BIGINT NOT NULL
        REFERENCES regulatory_documents(document_id),

    source_record_id VARCHAR(200) NOT NULL,

    event_type VARCHAR(100) NOT NULL CHECK (
        event_type IN (
            'BANNED',
            'PROHIBITED',
            'NSQ',
            'SPURIOUS',
            'ADR',
            'RECALL',
            'APPROVAL',
            'NOC',
            'IMPORT_PERMISSION',
            'SAFETY_ADVISORY',
            'SUSPENSION',
            'WITHDRAWAL',
            'UNDER_INVESTIGATION',
            'OTHER'
        )
    ),
    event_date DATE,

    scope VARCHAR(50) NOT NULL CHECK (
        scope IN (
            'BATCH',
            'PRODUCT',
            'INGREDIENT',
            'COMBINATION',
            'DOCUMENT'
        )
    ),

    product_id BIGINT REFERENCES products(product_id),
    batch_id BIGINT REFERENCES batches(batch_id),

    manufacturer_organization_id BIGINT
        REFERENCES organizations(organization_id),

    reporting_organization_id BIGINT
        REFERENCES organizations(organization_id),

    status VARCHAR(100),
    reason TEXT,
    action TEXT,
    legal_status TEXT,

    additional_data JSONB
);
```

`additional_data` is deliberately flexible for event-specific fields such as:

- NSQ result
- drawn by / designation
- ADRs
- indications
- notification metadata
- remarks
- device-specific fields

Do not add new relational columns merely to avoid an occasional `NULL`. Add a dedicated column only when repeated real data and query requirements justify it.

---

# 4. Canonical Key Rules

Surrogate PostgreSQL `BIGSERIAL` IDs are assigned **only by the database**. Staging CSVs must never depend on runtime-generated numeric IDs.

All canonical keys are deterministic SHA-256 hashes represented as 64 hexadecimal characters.

## 4.1 SHA-256

```python
def sha_key(*parts):
    raw = "|".join(str(p or "").strip().lower() for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()
```

## 4.2 Text canonicalization

Canonicalization should be conservative.

```python
def canonical(text):
    if not text:
        return ""

    text = text.lower().strip()
    text = re.sub(
        r'\b(pvt|private|ltd|limited|inc|corp|corporation)\b\.?',
        '',
        text
    )
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```

Do not use aggressive transformations that can collapse genuinely different products or organizations.

## 4.3 Organization key

Recommended strict behavior:

```python
def organization_key(name, state=None):
    if state:
        return sha_key("ORG", canonical(name), canonical(state))
    return sha_key("ORG_UNKNOWN_STATE", canonical(name))
```

Rules:

- same canonical name + same known state → deterministic match
- same name with state missing in one record → candidate match/review, not automatic merge
- same name + different states → separate keys unless an approved alias resolves them

## 4.4 Product key

```python
def product_key(
    name,
    strength=None,
    dosage_form=None,
    category="DRUG",
    ingredient_signature=None,
):
    return sha_key(
        "PROD",
        canonical(name),
        canonical(strength or ""),
        canonical(dosage_form or ""),
        canonical(category),
        ingredient_signature or "",
    )
```

Manufacturer is **not** part of product identity.

For FDC / multi-ingredient products, ingredient keys must be sorted before creating the ingredient signature so that `A+B` and `B+A` resolve to the same composition signature.

## 4.5 Ingredient key

```python
def ingredient_key(name):
    return sha_key("ING", canonical(name))
```

## 4.6 Batch key

```python
def batch_key(product_key_value, organization_key_value, batch_number):
    return sha_key(
        "BATCH",
        product_key_value,
        organization_key_value,
        canonical(batch_number),
    )
```

## 4.7 Event key

```python
def event_key(
    source_document_id,
    source_record_id,
    event_type,
    event_date=None,
    event_subtype=None,
):
    return sha_key(
        "EVT",
        source_document_id,
        source_record_id,
        canonical(event_type),
        str(event_date or ""),
        canonical(event_subtype or ""),
    )
```

The optional subtype protects against multiple distinct events being derived from one source row.

---

# 5. Source Lineage

Every parsed JSON row must receive a stable `source_record_id` before normalization.

A source record ID should contain:

```text
<document_id>:P<page>:T<table>:<row_fingerprint>:<occurrence>
```

Example:

```text
12555:P03:T01:8a91c2f3:01
```

## Row fingerprint

A content-based fingerprint should be used rather than relying only on row position.

```python
def row_fingerprint(rec):
    return sha_key(
        rec.get("product_name") or rec.get("drug_name"),
        rec.get("batch_number"),
        rec.get("manufactured_by"),
        rec.get("reason") or rec.get("nsq_result"),
    )
```

For duplicate/identical rows on the same page/table, maintain a per-fingerprint occurrence counter.

Source lineage must allow a path like:

```text
regulatory_event
      ↓
(document_id + source_record_id)
      ↓
raw_source_records
      ↓
regulatory_documents
      ↓
source PDF / page / source location
```

Always use the composite `(document_id, source_record_id)` relationship when joining lineage data. Do not rely on `source_record_id` globally unless a global uniqueness constraint is explicitly established.

---

# 6. Organization Resolution

Manufacturer and reporting organizations are independent roles.

Example:

```text
Manufactured By → ABC Pharma
Reported By     → CDTL Mumbai
```

must produce:

```text
manufacturer_organization_id → ABC Pharma
reporting_organization_id    → CDTL Mumbai
```

Never reuse the manufacturer organization as the reporting organization simply because both are present in the same row.

## People

Person names such as `drawn_by` are not organizations.

Store them in `additional_data`, for example:

```json
{
  "drawn_by": "Drug Inspector Name",
  "drawn_by_designation": "Drug Inspector"
}
```

Only create an organization entity when the source actually identifies an organization/institution/laboratory/authority.

## Aliases

Do not auto-merge fuzzy organization matches.

A future review table may store:

```sql
CREATE TABLE organization_aliases (
    alias_key VARCHAR(64) PRIMARY KEY,
    canonical_key VARCHAR(64) NOT NULL,
    alias_raw TEXT NOT NULL,
    confidence VARCHAR(20) NOT NULL CHECK (
        confidence IN ('AUTO', 'MANUAL', 'REVIEW')
    ),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

Allowed resolution states:

- `AUTO` — exact deterministic match
- `MANUAL` — explicitly reviewed/approved
- `REVIEW` — candidate awaiting human decision

---

# 7. Missing and Ambiguous Data Rules

The ETL must not create fake entities to avoid NULLs.

## Missing product

```text
product_key = NULL
normalization_status = NEEDS_REVIEW
review_reason = missing_product_name
```

## Missing batch

`batch_key = NULL` when no valid batch exists or when the document type is not batch-specific.

If `scope = BATCH`, missing batch information should trigger `NEEDS_REVIEW` or `FAILED` depending on whether the missing value is expected/repairable.

## Missing manufacturer

Do not invent an organization. Keep the organization key NULL and record the reason when required by the document type.

## Ambiguous entity match

Keep the candidate unresolved and send it to the review queue. Do not auto-merge based only on fuzzy similarity.

---

# 8. Staging CSV Layout

The staging layer should contain **canonical keys plus source/raw fields needed for validation and review**.

Recommended files:

```text
staging/
├── regulatory_documents.csv
├── raw_source_records.csv
├── organizations.csv
├── ingredients.csv
├── products.csv
├── product_ingredients.csv
├── product_organizations.csv
├── batches.csv
├── regulatory_events.csv
└── normalization_manifest.csv
```

## Important rule

**No PostgreSQL `BIGSERIAL` IDs are generated in staging.**

Use:

- `organization_key`
- `ingredient_key`
- `product_key`
- `batch_key`
- `event_key`
- `source_record_id`

and resolve them to database surrogate IDs during database loading.

---

# 9. Normalization Manifest

`normalization_manifest.csv` is mandatory.

Minimum columns:

```text
source_record_id
source_document_id
source_file
source_page
source_row
source_document_type

organization_key
product_key
batch_key
event_key

normalization_status
validation_status
review_reason
error_message
```

`normalization_status` is a **frozen controlled vocabulary**. CSV is not a database table, so the ETL validator must reject any value outside this list before DB load:

```python
VALID_NORMALIZATION_STATUSES = {
    'COMPLETE',
    'NEEDS_REVIEW',
    'IGNORED',
    'FAILED',
}
```

Allowed `review_reason` values are also frozen:

```text
missing_product_name
missing_batch_number
nsq_without_batch
ambiguous_organization
ambiguous_product
invalid_date_format
unparseable_row
duplicate_fingerprint
```

The ETL validator must reject unknown `normalization_status` or `review_reason` values rather than silently accepting free-form strings.

`validation_status` is also controlled:

```python
VALID_VALIDATION_STATUSES = {
    'PENDING',
    'VALID',
    'INVALID',
}
```

A CSV file cannot enforce a SQL `CHECK` constraint by itself. Therefore the authoritative constraint for the CSV manifest is implemented in `validate.py`. If the manifest is later materialized into a PostgreSQL staging table, apply the equivalent SQL `CHECK` constraint there.

The fundamental reconciliation rule is:

```text
TOTAL SOURCE RECORDS
=
COMPLETE + NEEDS_REVIEW + IGNORED + FAILED
```

This is a measured invariant, not a claim of zero data loss.

For clarity, the frozen SQL form, if the manifest is ever materialized into a PostgreSQL staging table, is:

```sql
normalization_status VARCHAR(30) NOT NULL CHECK (
    normalization_status IN (
        'COMPLETE',
        'NEEDS_REVIEW',
        'IGNORED',
        'FAILED'
    )
)
```

The current implementation keeps the manifest as CSV, so `validate.py` is the enforcement point.

---

# 10. ETL Modules

```text
etl/
├── __init__.py
├── keys.py
├── extract.py
├── resolve.py
├── stage.py
├── validate.py
├── load_db.py
└── run.py
```

## `keys.py`

Responsibilities:

- `sha_key()`
- `canonical()`
- organization/product/ingredient/batch/event keys
- row fingerprints
- source record ID generation

No database access.

## `extract.py`

Responsibilities:

- read parsed JSON
- identify document type
- map accepted JSON keys to canonical internal field names
- preserve raw values
- extract event-specific attributes

Do not perform fuzzy entity merging here.

## `resolve.py`

Responsibilities:

- deterministic organization resolution
- deterministic product resolution
- ingredient resolution
- batch key creation
- event key creation
- alias lookup
- review queue generation for ambiguous matches
- validate `document_type`, `event_type`, `scope`, and `product_category` against frozen taxonomies

## `stage.py`

Responsibilities:

- generate the normalized CSV files
- generate `normalization_manifest.csv`
- preserve source lineage
- never generate BIGSERIAL IDs

## `validate.py`

Responsibilities:

- reconciliation
- duplicate checks
- orphan checks
- scope consistency
- required-field checks
- lineage checks
- relationship integrity
- mutation isolation test support

## `load_db.py`

Responsibilities:

- load validated CSVs
- resolve canonical keys to database IDs
- perform idempotent inserts/upserts
- use transactions
- never silently discard a foreign-key resolution failure

## `run.py`

Responsibilities:

- orchestrate extraction → resolution → staging → validation
- exit non-zero when validation fails
- provide a concise run summary

Example:

```bash
python -m etl.run --input nsq_test.json --out staging/run1/
```

---

# 11. Database Load Order

Use the dependency order below:

```text
1. regulatory_documents
2. organizations
3. ingredients
4. products
5. product_ingredients
6. product_organizations
7. batches
8. raw_source_records
9. regulatory_events
```

## Key → ID resolution

Before inserting dependent records, resolve:

```text
organization_key → organization_id
ingredient_key   → ingredient_id
product_key      → product_id
batch_key        → batch_id
event_key        → event_id
```

Use the canonical-key `UNIQUE` constraints as the idempotency boundary.

When an insert with `ON CONFLICT DO NOTHING` returns no inserted row ID, perform a `SELECT` by canonical key to retrieve the existing surrogate ID.

All writes for a document should be wrapped in a transaction. If the document load fails, roll back the entire document load rather than leaving a half-loaded document.

---

# 12. Validation Suite

The first real validation target is **one NSQ JSON**.

Create:

```text
tests/
├── test_01_e2e.py
├── test_02_reconciliation.py
├── test_03_duplicates.py
├── test_04_orphans.py
├── test_05_db_load.py
├── test_06_idempotency.py
├── test_07_lineage.py
└── test_08_mutation.py
```

## Test 1 — End-to-End

Pass criteria:

- all expected CSVs are created
- expected non-empty tables are non-empty
- process exits successfully

## Test 2 — Reconciliation

```text
source rows == COMPLETE + NEEDS_REVIEW + IGNORED + FAILED
```

## Test 3 — Duplicate Keys

Verify uniqueness of:

- organization_key
- ingredient_key
- product_key
- batch_key
- event_key

## Test 4 — Orphan Relationships

Validate every foreign-key relationship in staging before DB insertion:

- manufacturer organization key exists
- reporting organization key exists
- product key exists when populated
- batch key exists when populated
- batch references valid product and organization
- product-organization relationships reference valid entities
- product-ingredient relationships reference valid entities

## Test 5 — Database Load

Verify expected row counts and key resolution after loading.

## Test 6 — Idempotency

Run the same staging input/load three times.

Expected result:

```text
Run 1 → insert expected records
Run 2 → no duplicate entities/events
Run 3 → no duplicate entities/events
```

Database counts for existing data must remain unchanged on repeated loads.

## Test 7 — Lineage

For any event, a composite join must recover:

- source event
- source_record_id
- source PDF filename
- source URL
- page number
- source location
- original extracted text

Recommended pattern:

```sql
SELECT
    e.event_key,
    e.event_type,
    e.status,
    e.source_record_id,
    r.source_text,
    r.page_number,
    r.source_location,
    d.filename,
    d.source_url
FROM regulatory_events e
JOIN raw_source_records r
  ON r.document_id = e.document_id
 AND r.source_record_id = e.source_record_id
JOIN regulatory_documents d
  ON d.document_id = r.document_id
WHERE e.event_key = '<EVENT_KEY>';
```

## Test 8 — Mutation Isolation

Use a controlled normalized-record fixture. After the baseline `source_record_id` has already been assigned, mutate only the batch number:

```text
Batch T645 → T646
```

The purpose of this test is to verify key isolation: a batch mutation must not mutate unrelated product, organization, or event identity.

Exact assertions:

```python
assert mutated.batch_key != baseline.batch_key, \
    "Batch key should change"

assert mutated.product_key == baseline.product_key, \
    "Product key should NOT change"

assert mutated.organization_key == baseline.organization_key, \
    "Organization key should NOT change"

assert mutated.event_key == baseline.event_key, \
    "Event key should NOT change when the source record/event identity is held constant"

new_batches = {mutated.batch_key} - {baseline.batch_key}
assert len(new_batches) == 1, \
    "Exactly one new batch key should exist"
```

Also verify that no unrelated entity key changes.

**Important:** this is an isolation test, not a test of source-row identity generation. If the raw source record itself is changed before `source_record_id` generation, and that identifier intentionally contains a content fingerprint, then the source record identity — and consequently the event key — may legitimately change.

---

# 13. Failure and Review Outputs

Create:

```text
reports/
├── needs_review.csv
├── orphan_analysis.csv
├── alias_candidates.csv
├── failed_extractions.csv
└── metrics_summary.md
```

## Per-document-type metrics

Measure, do not claim:

- total source rows
- complete rows
- needs-review rows
- ignored rows
- failed rows
- duplicate canonical keys found
- orphan relationships found
- unique organizations
- unique products
- unique batches
- unique events
- average entities per event

Example summary:

```text
NSQ_ALERT
----------
Source rows:        10,000
Complete:            9,450
Needs review:           42
Ignored:               500
Failed:                  8
Reconciliation:       PASS
Duplicate keys:          0
Orphans:                 0
```

Do not claim `zero duplicates`, `zero data loss`, or `production-ready` unless the relevant measurements/tests support those statements.

---

# 14. Idempotency Rules

Idempotency is required at both staging and database levels.

## Staging

Same input → same canonical keys.

Changing processing order must not change canonical entity identity.

## Database

Use `UNIQUE` canonical-key constraints and conflict handling. Repeated loads must explicitly use conflict-safe inserts.

For `regulatory_documents`, when a stable source document ID exists:

```sql
INSERT INTO regulatory_documents (...)
VALUES (...)
ON CONFLICT (source_organization, source_document_id) DO NOTHING;
```

If `source_document_id` is unavailable/null, use the unique `file_hash` as the fallback conflict target:

```sql
INSERT INTO regulatory_documents (...)
VALUES (...)
ON CONFLICT (file_hash) DO NOTHING;
```

For `raw_source_records`:

```sql
INSERT INTO raw_source_records (...)
VALUES (...)
ON CONFLICT (document_id, source_record_id) DO NOTHING;
```

For canonical entity/event tables, use the corresponding canonical-key conflict target, then perform a `SELECT` fallback when the insert returns no row.

Required unique identity boundaries:

```text
organizations.organization_key
ingredients.ingredient_key
products.product_key
batches.batch_key
regulatory_events.event_key
regulatory_documents(source_organization, source_document_id)
```

Also retain the database-level batch constraint:

```text
UNIQUE(product_id, organization_id, batch_number)
```

and product relationship constraint:

```text
PRIMARY KEY(product_id, organization_id, role)
```

Never overwrite an existing `product_organizations` relationship because a later source record contains another manufacturer. Multiple valid relationships must coexist.

---

# 15. Indexes

`indexes.sql` should contain the initial relational and query indexes. Add indexes only when they support real lookup/foreign-key patterns.

```sql
-- Foreign key indexes
CREATE INDEX idx_events_product_id
    ON regulatory_events(product_id);

CREATE INDEX idx_events_batch_id
    ON regulatory_events(batch_id);

CREATE INDEX idx_events_manufacturer_id
    ON regulatory_events(manufacturer_organization_id);

CREATE INDEX idx_events_reporting_id
    ON regulatory_events(reporting_organization_id);

CREATE INDEX idx_events_document_id
    ON regulatory_events(document_id);

CREATE INDEX idx_events_event_type
    ON regulatory_events(event_type);

CREATE INDEX idx_events_event_date
    ON regulatory_events(event_date);

-- Scanner/application lookup indexes
CREATE INDEX idx_products_normalized
    ON products(normalized_name);

CREATE INDEX idx_batches_batch_number
    ON batches(batch_number);

CREATE INDEX idx_orgs_normalized
    ON organizations(normalized_name);

CREATE INDEX idx_raw_source_document_id
    ON raw_source_records(document_id);

-- Flexible event attributes
CREATE INDEX idx_events_additional_data
    ON regulatory_events USING GIN (additional_data);
```

The canonical-key `UNIQUE` constraints already create indexes, so separate duplicate indexes for those columns are not required.

---

# 16. Data Integrity Rules

These rules are frozen for the POC.

### Rule A — No fabricated entities

Missing product/organization/batch information becomes NULL + review status as appropriate.

### Rule B — Manufacturer ≠ reporting laboratory

Store them as separate organization relationships.

### Rule C — Batch identity ≠ regulatory state

The batch master only stores identity and basic manufacturing dates. NSQ/spurious/prohibition/recall state belongs to regulatory events.

### Rule D — Product identity excludes manufacturer

Manufacturer is modeled as a separate product-organization relationship.

### Rule E — FDC composition is deterministic

Ingredient signatures are sorted before generating a product key.

### Rule F — People are not organizations

Names in `drawn_by`, inspector, officer, etc. remain event-specific data unless the source clearly identifies an organization.

### Rule G — Ambiguous matches go to review

Fuzzy similarity can generate review candidates, but must not auto-merge entities without an approved rule or human confirmation.

### Rule H — Lineage is mandatory

Every normalized event must be traceable to its source document and source record.

---

# 17. First Implementation Milestone

Do not implement all nine document types at once.

Start with **one real NSQ JSON**.

Required sequence:

```text
NSQ JSON
   ↓
ETL core
   ↓
normalized staging CSVs
   ↓
manifest
   ↓
validation
   ↓
PostgreSQL
   ↓
rERUN same input
   ↓
idempotency
   ↓
lineage query
```

The first milestone is complete only when all 8 validation tests pass for the NSQ test file.

---

# 18. Type Expansion Order

After the NSQ pipeline passes:

## Stage 1

- FDC / Banned Drugs
- PvPI / ADR

## Stage 2

- Spurious Drugs
- Medical Device / IVD Safety Alerts
- Approved Drugs / Marketing Authorization
- NOC / Import Permission / FDC
- Legacy CDSCO Alerts
- State Lab NSQ

Each document type must pass the same validation suite before being accepted.

---

# 19. Production Hardening — Later

Production hardening is intentionally postponed until the data-model and ETL behavior are validated on real document types.

Later additions:

### Alias resolution

- manual alias review workflow
- alias candidate queue
- explicit approval of organization merges

### Failure logging

A structured error store should include:

```text
source_record_id
stage
error_message
timestamp
```

### Re-run safety

- full pipeline rerunnable on subsets
- transaction per document
- no partial document writes
- deterministic canonical keys

### Observability

- archived manifests per run
- run metrics
- validation failure alerts
- DB row-count metrics

---

# 20. Repository Structure

Recommended implementation structure:

```text
project/
├── schema.sql
├── indexes.sql
├── requirements.txt
├── event_type_taxonomy.md
├── README.md
│
├── etl/
│   ├── __init__.py
│   ├── keys.py
│   ├── extract.py
│   ├── resolve.py
│   ├── stage.py
│   ├── validate.py
│   ├── load_db.py
│   └── run.py
│
├── tests/
│   ├── test_01_e2e.py
│   ├── test_02_reconciliation.py
│   ├── test_03_duplicates.py
│   ├── test_04_orphans.py
│   ├── test_05_db_load.py
│   ├── test_06_idempotency.py
│   ├── test_07_lineage.py
│   └── test_08_mutation.py
│
├── staging/
├── reports/
└── data/
    └── parsed_json/
```

---

# 21. Python Dependencies

`requirements.txt` should start with this minimal baseline:

```text
pandas>=2.0
psycopg2-binary>=2.9
SQLAlchemy>=2.0
pytest>=7.0
python-dateutil>=2.8
```

Add further packages only when an actual implementation module requires them.

---

# 22. Execution Timeline

| Phase   | Target     | Deliverable                   |
| ------- | ---------- | ----------------------------- |
| Phase 0 | 2–3 hours | Schema + indexes applied      |
| Phase 1 | 1 day      | ETL core package              |
| Phase 2 | 0.5 day    | 8 validation tests            |
| Phase 3 | 0.5 day    | First real NSQ JSON validated |
| Phase 4 | 2 days     | Remaining 9 document types    |
| Phase 5 | 1 day      | Failure/review analysis       |
| Phase 6 | 3 days     | Production hardening          |

This timeline is a working target, not a guaranteed duration.

---

# 23. Frozen Rules — Do Not Violate

```text
✓ Use deterministic canonical keys
✓ Keep full SHA-256 keys in staging/database
✓ Keep source_record_id lineage
✓ Use a normalization manifest
✓ Generate staging CSVs before DB load
✓ Validate before inserting into DB
✓ Keep manufacturer and reporting organization separate
✓ Keep people out of organizations
✓ Treat batches as identity records
✓ Keep regulatory state in regulatory_events
✓ Never invent entities for missing data
✓ Never auto-fuzzy-merge uncertain organizations
✓ Never emit BIGSERIAL IDs in staging CSVs
✓ Never use runtime counters for identity
✓ Never overwrite valid product-organization relationships
✓ Use composite lineage joins
✓ Measure metrics instead of making unsupported zero-error claims
```

```text
✗ Do not redesign the schema for hypothetical future fields
✗ Do not bypass validation because a file is "small"
✗ Do not silently discard failed rows
✗ Do not use JSON hashing as a fake product/batch identity
✗ Do not treat a successful parse as proof that the data is correct
```

---

# 24. Definition of Done

The ETL implementation is considered complete for the current POC when:

```text
[ ] Schema applied successfully
[ ] Canonical key constraints active
[ ] One NSQ JSON processed end-to-end
[ ] All expected staging CSVs generated
[ ] Manifest reconciliation passes
[ ] Duplicate-key validation passes
[ ] Orphan validation passes
[ ] DB load passes
[ ] Same input loaded repeatedly without duplicate entities/events
[ ] Lineage query returns source PDF + page + extracted text
[ ] Mutation isolation test passes
[ ] At least three different document types validated
[ ] All nine document types processed through the same pipeline framework
[ ] NEEDS_REVIEW / FAILED cases are measurable and documented
[ ] Failure logging and alias-review workflow are added before production deployment
```

---

# 25. Immediate Start Command

```bash
mkdir -p etl tests staging reports data/parsed_json

psql -d drug_alerts -f schema.sql
psql -d drug_alerts -f indexes.sql

python -m etl.run --input data/parsed_json/nsq_test.json --out staging/run1/
python -m tests.run_all --staging staging/run1/
```

Then:

```text
1. Fix only actual test failures.
2. Do not redesign the schema for hypothetical cases.
3. Repeat until the single NSQ JSON passes all eight tests.
4. Only then expand to the next document type.
```

---

# 26. Final Mental Model

The ETL should always answer these five questions:

### What did we receive?

`regulatory_documents` + `raw_source_records`

### What entities did we identify?

`organizations` + `ingredients` + `products` + `batches`

### How are those entities related?

`product_ingredients` + `product_organizations`

### What regulatory action occurred?

`regulatory_events`

### Where did every piece of information come from?

`source_record_id` + `document_id` + raw source text/location

If the pipeline can answer all five consistently, the normalization layer is doing its job.
