-- =========================================================
-- Medicine Regulatory Data ETL Pipeline — Database Indexes
-- Secondary and Foreign Key Indexes for Performance Optimization
-- =========================================================

-- Foreign Key Indexes for regulatory_events
CREATE INDEX IF NOT EXISTS idx_events_product_id ON regulatory_events(product_id);
CREATE INDEX IF NOT EXISTS idx_events_batch_id ON regulatory_events(batch_id);
CREATE INDEX IF NOT EXISTS idx_events_manufacturer_id ON regulatory_events(manufacturer_organization_id);
CREATE INDEX IF NOT EXISTS idx_events_reporting_id ON regulatory_events(reporting_organization_id);
CREATE INDEX IF NOT EXISTS idx_events_document_id ON regulatory_events(document_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON regulatory_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_event_date ON regulatory_events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_scope ON regulatory_events(scope);

-- Entity & Application Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_products_normalized ON products(normalized_name);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_name);
CREATE INDEX IF NOT EXISTS idx_batches_batch_number ON batches(batch_number);
CREATE INDEX IF NOT EXISTS idx_batches_product_id ON batches(product_id);
CREATE INDEX IF NOT EXISTS idx_batches_org_id ON batches(organization_id);
CREATE INDEX IF NOT EXISTS idx_orgs_normalized ON organizations(normalized_name);

-- Junction Table Reverse Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_product_orgs_org_id ON product_organizations(organization_id);
CREATE INDEX IF NOT EXISTS idx_product_ing_ing_id ON product_ingredients(ingredient_id);

-- Lineage & Audit Trail Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_raw_source_document_id ON raw_source_records(document_id);

-- GIN Index for Flexible JSONB Attributes
CREATE INDEX IF NOT EXISTS idx_events_additional_data ON regulatory_events USING GIN (additional_data);
