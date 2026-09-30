CREATE TABLE IF NOT EXISTS staging_key_map (
    staging_key_map_id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(32) NOT NULL CHECK (
        entity_type IN ('organization', 'ingredient', 'product', 'batch', 'event')
    ),
    staging_key VARCHAR(64) NOT NULL,
    organization_id BIGINT REFERENCES organizations(organization_id),
    ingredient_id BIGINT REFERENCES ingredients(ingredient_id),
    product_id BIGINT REFERENCES products(product_id),
    batch_id BIGINT REFERENCES batches(batch_id),
    event_id BIGINT REFERENCES regulatory_events(event_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entity_type, staging_key),
    UNIQUE (organization_id),
    UNIQUE (ingredient_id),
    UNIQUE (product_id),
    UNIQUE (batch_id),
    UNIQUE (event_id),
    CHECK (
        (entity_type = 'organization' AND organization_id IS NOT NULL AND ingredient_id IS NULL AND product_id IS NULL AND batch_id IS NULL AND event_id IS NULL) OR
        (entity_type = 'ingredient' AND organization_id IS NULL AND ingredient_id IS NOT NULL AND product_id IS NULL AND batch_id IS NULL AND event_id IS NULL) OR
        (entity_type = 'product' AND organization_id IS NULL AND ingredient_id IS NULL AND product_id IS NOT NULL AND batch_id IS NULL AND event_id IS NULL) OR
        (entity_type = 'batch' AND organization_id IS NULL AND ingredient_id IS NULL AND product_id IS NULL AND batch_id IS NOT NULL AND event_id IS NULL) OR
        (entity_type = 'event' AND organization_id IS NULL AND ingredient_id IS NULL AND product_id IS NULL AND batch_id IS NULL AND event_id IS NOT NULL)
    )
);

INSERT INTO staging_key_map (entity_type, staging_key, organization_id)
SELECT 'organization', organization_key, organization_id FROM organizations
ON CONFLICT (entity_type, staging_key) DO NOTHING;

INSERT INTO staging_key_map (entity_type, staging_key, ingredient_id)
SELECT 'ingredient', ingredient_key, ingredient_id FROM ingredients
ON CONFLICT (entity_type, staging_key) DO NOTHING;

INSERT INTO staging_key_map (entity_type, staging_key, product_id)
SELECT 'product', product_key, product_id FROM products
ON CONFLICT (entity_type, staging_key) DO NOTHING;

INSERT INTO staging_key_map (entity_type, staging_key, batch_id)
SELECT 'batch', batch_key, batch_id FROM batches
ON CONFLICT (entity_type, staging_key) DO NOTHING;

INSERT INTO staging_key_map (entity_type, staging_key, event_id)
SELECT 'event', event_key, event_id FROM regulatory_events
ON CONFLICT (entity_type, staging_key) DO NOTHING;
