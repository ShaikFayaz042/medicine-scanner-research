-- =========================================================
-- Medicine Regulatory Data ETL Pipeline — V1 Database Schema DDL
-- Absolute Final DDL — Frozen Version with CHECK Constraints & SHA-256 Canonical Keys
-- =========================================================

-- Enable Extension for JSONB GIN Indexes if required
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =========================================================
-- 1. ORGANIZATIONS
-- Handles Manufacturers, Importers, Labs, State FDAs, Applicants
-- =========================================================
CREATE TABLE IF NOT EXISTS organizations (
    organization_id BIGSERIAL PRIMARY KEY,
    organization_key VARCHAR(64) UNIQUE NOT NULL,
    organization_name TEXT NOT NULL,
    normalized_name TEXT,
    address TEXT,
    state VARCHAR(200),
    country VARCHAR(200) DEFAULT 'India',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================
-- 2. INGREDIENTS (APIs / Active Substances)
-- =========================================================
CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id BIGSERIAL PRIMARY KEY,
    ingredient_key VARCHAR(64) UNIQUE NOT NULL,
    ingredient_name TEXT NOT NULL,
    normalized_name TEXT UNIQUE,
    cas_number VARCHAR(100)
);

-- =========================================================
-- 3. PRODUCTS (Master Catalog)
-- =========================================================
CREATE TABLE IF NOT EXISTS products (
    product_id BIGSERIAL PRIMARY KEY,
    product_key VARCHAR(64) UNIQUE NOT NULL,
    product_name TEXT NOT NULL,
    normalized_name TEXT,
    brand_name TEXT,
    dosage_form TEXT,
    strength TEXT,
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

-- =========================================================
-- 4. PRODUCT ↔ INGREDIENT (For FDCs & Multi-ingredient Formulations)
-- =========================================================
CREATE TABLE IF NOT EXISTS product_ingredients (
    product_id BIGINT REFERENCES products(product_id) ON DELETE CASCADE,
    ingredient_id BIGINT REFERENCES ingredients(ingredient_id) ON DELETE CASCADE,
    ingredient_strength TEXT,
    PRIMARY KEY (product_id, ingredient_id)
);

-- =========================================================
-- 5. PRODUCT ↔ ORGANIZATION (Product-Level Entity Relationships)
-- Solves the "Approved Drug without Batch" problem
-- =========================================================
CREATE TABLE IF NOT EXISTS product_organizations (
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

-- =========================================================
-- 6. REGULATORY DOCUMENTS (Header PDF Metadata)
-- =========================================================
CREATE TABLE IF NOT EXISTS regulatory_documents (
    document_id BIGSERIAL PRIMARY KEY,
    source_organization TEXT NOT NULL, -- CDSCO, PvPI, State FDA
    source_document_id TEXT,           -- Stable ID from source if available
    
    filename TEXT NOT NULL,
    document_title TEXT,
    publication_date DATE,
    reporting_period VARCHAR(200),
    
    source_url TEXT NOT NULL,
    file_hash CHAR(64) UNIQUE,                 -- Fallback dedup if source_document_id is NULL
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

-- =========================================================
-- 7. RAW SOURCE RECORDS (Audit Trail & Lineage)
-- =========================================================
CREATE TABLE IF NOT EXISTS raw_source_records (
    raw_source_id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES regulatory_documents(document_id) ON DELETE CASCADE,
    source_record_id TEXT NOT NULL,
    page_number INT,
    source_location TEXT,
    extraction_method VARCHAR(50), -- TEXT / OCR / MIXED
    source_text TEXT,
    raw_json JSONB,
    extraction_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE (document_id, source_record_id)
);

-- =========================================================
-- 8. BATCHES (Identity Only)
-- =========================================================
CREATE TABLE IF NOT EXISTS batches (
    batch_id BIGSERIAL PRIMARY KEY,
    batch_key VARCHAR(64) UNIQUE NOT NULL,
    
    product_id BIGINT REFERENCES products(product_id),
    organization_id BIGINT REFERENCES organizations(organization_id),
    
    batch_number TEXT NOT NULL,
    manufacturing_date DATE,
    expiry_date DATE,
    
    -- Prevent duplicate batch entries for the same product and manufacturer
    UNIQUE (product_id, organization_id, batch_number)
);

-- =========================================================
-- 9. REGULATORY EVENTS (Core Regulatory Action Table)
-- =========================================================
CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(64) UNIQUE NOT NULL,
    
    document_id BIGINT NOT NULL REFERENCES regulatory_documents(document_id),
    source_record_id TEXT NOT NULL,
    
    event_type VARCHAR(100) NOT NULL CHECK (
        event_type IN (
            'BANNED',
            'PROHIBITED',
            'NSQ',
            'SPURIOUS',
            'RECALL',
            'ADR',
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
        scope IN ('BATCH', 'PRODUCT', 'INGREDIENT', 'COMBINATION', 'DOCUMENT')
    ),
    
    product_id BIGINT REFERENCES products(product_id),
    batch_id BIGINT REFERENCES batches(batch_id),
    manufacturer_organization_id BIGINT REFERENCES organizations(organization_id),
    reporting_organization_id BIGINT REFERENCES organizations(organization_id),
    
    status VARCHAR(100),
    
    reason TEXT,
    action TEXT,
    legal_status TEXT,
    additional_data JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE regulatory_events DROP CONSTRAINT IF EXISTS regulatory_events_event_type_check;
ALTER TABLE regulatory_events ADD CONSTRAINT regulatory_events_event_type_check CHECK (
    event_type IN (
        'BANNED', 'PROHIBITED', 'NSQ', 'SPURIOUS', 'ADR', 'RECALL',
        'APPROVAL', 'NOC', 'IMPORT_PERMISSION', 'SAFETY_ADVISORY',
        'SUSPENSION', 'WITHDRAWAL', 'UNDER_INVESTIGATION', 'OTHER'
    )
);

ALTER TABLE regulatory_events DROP CONSTRAINT IF EXISTS regulatory_events_scope_check;
ALTER TABLE regulatory_events ADD CONSTRAINT regulatory_events_scope_check CHECK (
    scope IN ('BATCH', 'PRODUCT', 'INGREDIENT', 'COMBINATION', 'DOCUMENT')
);

ALTER TABLE regulatory_events DROP CONSTRAINT IF EXISTS regulatory_events_status_check;
DROP TABLE IF EXISTS normalization_manifest;

