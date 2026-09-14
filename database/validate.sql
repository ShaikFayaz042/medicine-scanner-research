-- database/validate.sql
-- Post-load integrity checks. Every query MUST return 0 rows.
-- psql -d <db> -f database/validate.sql

SET search_path TO medicine_scanner;

-- 1. Events with missing document
SELECT 'events_orphan_document' AS check_name, e.id AS bad_id
FROM regulatory_events e
LEFT JOIN regulatory_documents d ON d.id = e.document_id
WHERE d.id IS NULL;

-- 2. Events with missing product
SELECT 'events_orphan_product' AS check_name, e.id AS bad_id
FROM regulatory_events e
LEFT JOIN products p ON p.id = e.product_id
WHERE e.product_id IS NOT NULL AND p.id IS NULL;

-- 3. Events with missing batch
SELECT 'events_orphan_batch' AS check_name, e.id AS bad_id
FROM regulatory_events e
LEFT JOIN batches b ON b.id = e.batch_id
WHERE e.batch_id IS NOT NULL AND b.id IS NULL;

-- 4. entity_sources -> products
SELECT 'entity_sources_orphan_product' AS check_name, es.id AS bad_id
FROM entity_sources es
LEFT JOIN products p ON p.id = es.entity_id
WHERE es.entity_table = 'products' AND p.id IS NULL;

-- 5. entity_sources -> manufacturers
SELECT 'entity_sources_orphan_manufacturer' AS check_name, es.id AS bad_id
FROM entity_sources es
LEFT JOIN manufacturers m ON m.id = es.entity_id
WHERE es.entity_table = 'manufacturers' AND m.id IS NULL;

-- 6. entity_sources -> batches
SELECT 'entity_sources_orphan_batch' AS check_name, es.id AS bad_id
FROM entity_sources es
LEFT JOIN batches b ON b.id = es.entity_id
WHERE es.entity_table = 'batches' AND b.id IS NULL;

-- 7. entity_sources -> ingredients
SELECT 'entity_sources_orphan_ingredient' AS check_name, es.id AS bad_id
FROM entity_sources es
LEFT JOIN ingredients i ON i.id = es.entity_id
WHERE es.entity_table = 'ingredients' AND i.id IS NULL;

-- 8. NSQ events missing reason without a documented extraction status
SELECT 'nsq_events_missing_reason_unexplained' AS check_name, e.id AS bad_id
FROM regulatory_events e
WHERE e.event_type = 'QUALITY_FAILURE' AND e.status = 'NOT_OF_STANDARD_QUALITY'
	AND (e.reason IS NULL OR e.reason = '')
	AND COALESCE(e.additional_data->'_validation'->>'reason', '') NOT IN
			('EXTRACTION_MISSING', 'NOT_APPLICABLE');

-- 9. FDC prohibition events missing legal_reference without an extraction status
SELECT 'fdc_prohibition_missing_legal_reference_unexplained' AS check_name, e.id AS bad_id
FROM regulatory_events e
WHERE e.event_type = 'FDC_PROHIBITION'
	AND (e.legal_reference IS NULL OR e.legal_reference = '')
	AND COALESCE(e.additional_data->'_validation'->>'legal_reference', '') NOT IN
			('EXTRACTION_MISSING', 'NOT_APPLICABLE')
	AND COALESCE(e.additional_data->>'review_required', 'false') <> 'true';

-- 10. Every entity_sources.source_record_id must be non-empty
SELECT 'entity_sources_empty_source_record_id' AS check_name, es.id AS bad_id
FROM entity_sources es
WHERE es.source_record_id IS NULL OR es.source_record_id = '';
