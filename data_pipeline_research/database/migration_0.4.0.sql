BEGIN;

SET search_path TO medicine_scanner;

-- Check first. If this returns rows, reconcile them manually and rerun.
SELECT source_org, document_id, COUNT(*)
FROM regulatory_documents
WHERE document_id IS NOT NULL
GROUP BY source_org, document_id
HAVING COUNT(*) > 1;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM regulatory_documents
        WHERE document_id IS NOT NULL
        GROUP BY source_org, document_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate (source_org, document_id) values exist; reconcile before migration';
    END IF;
END $$;

ALTER TABLE regulatory_documents
    DROP CONSTRAINT IF EXISTS uq_documents_source_docid;
ALTER TABLE regulatory_documents
    DROP CONSTRAINT IF EXISTS uq_documents_source_docid_type;
ALTER TABLE regulatory_documents
    ADD CONSTRAINT uq_documents_source_docid_type
    UNIQUE (source_org, document_id, document_type);

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

COMMIT;