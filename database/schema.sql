BEGIN;

CREATE SCHEMA IF NOT EXISTS medicine_scanner;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

SET search_path TO medicine_scanner, public;

-- 1. regulatory_documents
CREATE TABLE IF NOT EXISTS regulatory_documents (
    id                          BIGSERIAL PRIMARY KEY,
    source_org                  VARCHAR(50)  NOT NULL,
    source_category             VARCHAR(50)  NOT NULL,
    document_type               VARCHAR(50)  NOT NULL,
    title                       TEXT,
    publication_date            DATE,
    publication_date_raw        TEXT,
    publication_date_precision  VARCHAR(10),
    document_id                 VARCHAR(100),
    source_url                  TEXT,
    pdf_filename                TEXT,
    file_hash                   CHAR(64),
    raw_text                    TEXT,
    extraction_method           VARCHAR(30),
    extraction_status           VARCHAR(30),
    extraction_confidence       NUMERIC(5,2),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_documents_source_docid_type UNIQUE (source_org, document_id, document_type),
    CONSTRAINT ck_documents_pub_precision
        CHECK (publication_date_precision IS NULL
               OR publication_date_precision IN ('DAY','MONTH','YEAR','UNKNOWN'))
);

-- A PDF can appear under multiple document types, so file_hash is not unique.
DROP INDEX IF EXISTS uq_documents_file_hash_not_null;
CREATE INDEX IF NOT EXISTS idx_documents_file_hash
    ON regulatory_documents(file_hash);

-- Preserve repeated document IDs when the classifier assigns different types.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_documents_source_docid'
          AND conrelid = 'medicine_scanner.regulatory_documents'::regclass
    ) THEN
        ALTER TABLE medicine_scanner.regulatory_documents
            DROP CONSTRAINT uq_documents_source_docid;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_documents_source_docid_type'
              AND conrelid = 'medicine_scanner.regulatory_documents'::regclass
        ) THEN
            ALTER TABLE medicine_scanner.regulatory_documents
                ADD CONSTRAINT uq_documents_source_docid_type
                UNIQUE (source_org, document_id, document_type);
        END IF;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_documents_source_org ON regulatory_documents(source_org);
CREATE INDEX IF NOT EXISTS idx_documents_type       ON regulatory_documents(document_type);
CREATE INDEX IF NOT EXISTS idx_documents_pub_date   ON regulatory_documents(publication_date);

-- 2. manufacturers
CREATE TABLE IF NOT EXISTS manufacturers (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    normalized_name  TEXT NOT NULL,
    address          TEXT,
    country          VARCHAR(100),
    match_status     VARCHAR(30) NOT NULL DEFAULT 'UNREVIEWED',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_manufacturers_normalized_name
    ON manufacturers(normalized_name);
CREATE INDEX IF NOT EXISTS idx_manufacturers_norm_name ON manufacturers(normalized_name);
CREATE INDEX IF NOT EXISTS idx_manufacturers_trgm
    ON manufacturers USING gin (normalized_name gin_trgm_ops);

-- 3. products
CREATE TABLE IF NOT EXISTS products (
    id                      BIGSERIAL PRIMARY KEY,
    product_name            TEXT NOT NULL,
    product_name_raw        TEXT,
    brand_name              TEXT,
    generic_name            TEXT,
    dosage_form             TEXT,
    route                   TEXT,
    manufacturer_id         BIGINT REFERENCES manufacturers(id),
    marketer_name           TEXT,
    importer_name           TEXT,
    raw_composition         TEXT,
    normalized_search_name  TEXT NOT NULL,
    match_status            VARCHAR(30) NOT NULL DEFAULT 'UNREVIEWED',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_products_norm_name    ON products(normalized_search_name);
CREATE INDEX IF NOT EXISTS idx_products_manufacturer ON products(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_products_name_trgm
    ON products USING gin (normalized_search_name gin_trgm_ops);

-- 4. ingredients
CREATE TABLE IF NOT EXISTS ingredients (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    normalized_name  TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ingredients_norm_name UNIQUE (normalized_name)
);
CREATE INDEX IF NOT EXISTS idx_ingredients_trgm
    ON ingredients USING gin (normalized_name gin_trgm_ops);

-- 5. product_ingredients
CREATE TABLE IF NOT EXISTS product_ingredients (
    product_id     BIGINT NOT NULL REFERENCES products(id),
    ingredient_id  BIGINT NOT NULL REFERENCES ingredients(id),
    strength       NUMERIC(12,4),
    strength_text  TEXT,
    unit           VARCHAR(20),
    basis          VARCHAR(40),
    dosage_form    TEXT,
    sequence_no    INT NOT NULL DEFAULT 1,
    PRIMARY KEY (product_id, ingredient_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS idx_prod_ing_product    ON product_ingredients(product_id);
CREATE INDEX IF NOT EXISTS idx_prod_ing_ingredient ON product_ingredients(ingredient_id);

-- 6. batches
CREATE TABLE IF NOT EXISTS batches (
    id                     BIGSERIAL PRIMARY KEY,
    product_id             BIGINT NOT NULL REFERENCES products(id),
    manufacturer_id        BIGINT REFERENCES manufacturers(id),
    batch_number           TEXT NOT NULL,
    mfg_date               DATE,
    mfg_date_raw           TEXT,
    mfg_date_precision     VARCHAR(10),
    expiry_date            DATE,
    expiry_date_raw        TEXT,
    expiry_date_precision  VARCHAR(10),
    match_status           VARCHAR(30) NOT NULL DEFAULT 'UNREVIEWED',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_batches_mfg_precision
        CHECK (mfg_date_precision IS NULL
               OR mfg_date_precision IN ('DAY','MONTH','YEAR','UNKNOWN')),
    CONSTRAINT ck_batches_exp_precision
        CHECK (expiry_date_precision IS NULL
               OR expiry_date_precision IN ('DAY','MONTH','YEAR','UNKNOWN'))
);
CREATE INDEX IF NOT EXISTS idx_batches_batch_number ON batches(batch_number);
CREATE INDEX IF NOT EXISTS idx_batches_product      ON batches(product_id);

-- 7. regulatory_events  (primary provenance-bearing record)
CREATE TABLE IF NOT EXISTS regulatory_events (
    id                    BIGSERIAL PRIMARY KEY,
    document_id           BIGINT NOT NULL REFERENCES regulatory_documents(id),
    product_id            BIGINT REFERENCES products(id),
    batch_id              BIGINT REFERENCES batches(id),
    scope                 VARCHAR(30) NOT NULL,
    event_type            VARCHAR(50) NOT NULL,
    status                VARCHAR(50),          -- NULL allowed for document-only events
    legal_status          VARCHAR(50),
    reason                TEXT,
    effective_date        DATE,
    investigation_status  VARCHAR(50),
    sample_collected_by   TEXT,
    testing_lab           TEXT,
    legal_reference       TEXT,
    additional_data       JSONB,
    source_record_id      TEXT NOT NULL,
    CONSTRAINT uq_events_source_record_id UNIQUE (source_record_id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_document   ON regulatory_events(document_id);
CREATE INDEX IF NOT EXISTS idx_events_product    ON regulatory_events(product_id);
CREATE INDEX IF NOT EXISTS idx_events_batch      ON regulatory_events(batch_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON regulatory_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_status     ON regulatory_events(status);
CREATE INDEX IF NOT EXISTS idx_events_legal      ON regulatory_events(legal_status);

-- 8. entity_sources (provenance infrastructure, NOT business entity)
CREATE TABLE IF NOT EXISTS entity_sources (
    id                BIGSERIAL PRIMARY KEY,
    entity_table      VARCHAR(50) NOT NULL,
    entity_id         BIGINT      NOT NULL,
    source_record_id  TEXT        NOT NULL,
    document_id       BIGINT      NOT NULL REFERENCES regulatory_documents(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_entity_sources_table
        CHECK (entity_table IN ('products','manufacturers','batches','ingredients')),
    CONSTRAINT uq_entity_sources UNIQUE (entity_table, entity_id, source_record_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_sources_entity
    ON entity_sources(entity_table, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_sources_document
    ON entity_sources(document_id);
CREATE INDEX IF NOT EXISTS idx_entity_sources_source
    ON entity_sources(source_record_id);

-- Explicit document-type vocabulary for strict MVP loads.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_documents_type'
          AND conrelid = 'regulatory_documents'::regclass
    ) THEN
        ALTER TABLE regulatory_documents
            ADD CONSTRAINT ck_documents_type
            CHECK (document_type IN (
                'NSQ_ALERT','SPURIOUS_ALERT','DRUG_ALERT',
                'FDC_PROHIBITED','FDC_NOTIFICATION','GAZETTE_LEGAL',
                'PVPI_SAFETY','THEFT_RECALL','MEDICAL_DEVICE','IVD_ALERT',
                'CIRCULAR','GUIDELINE','OTHER'
            ));
    END IF;
END $$;

-- Fallback deduplication when document_id is unavailable.
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_source_pdf_filename
    ON regulatory_documents(source_org, pdf_filename)
    WHERE document_id IS NULL AND pdf_filename IS NOT NULL;

-- Replace PostgreSQL's NULL-distinct batch uniqueness behavior.
ALTER TABLE batches DROP CONSTRAINT IF EXISTS uq_batches_prod_mfg_bat;
CREATE UNIQUE INDEX IF NOT EXISTS uq_batches_dedup
    ON batches(product_id, COALESCE(manufacturer_id, 0), batch_number);

-- Product identity tuple from normalization/config/entity_resolution.json.
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_dedup
    ON products(
        normalized_search_name,
        COALESCE(manufacturer_id, 0),
        COALESCE(dosage_form, '')
    );

-- Apply event idempotency to databases created before this constraint existed.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_events_source_record_id'
          AND conrelid = 'regulatory_events'::regclass
    ) THEN
        ALTER TABLE regulatory_events
            ADD CONSTRAINT uq_events_source_record_id UNIQUE (source_record_id);
    END IF;
END $$;

COMMIT;