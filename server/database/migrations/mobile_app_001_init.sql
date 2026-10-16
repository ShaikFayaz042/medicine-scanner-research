CREATE SCHEMA IF NOT EXISTS mobile_app_schema;

CREATE TABLE IF NOT EXISTS mobile_app_schema.users (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(320) NOT NULL,
    password_hash VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_mobile_app_schema_users_email
    ON mobile_app_schema.users (LOWER(email));

CREATE TABLE IF NOT EXISTS mobile_app_schema.scans (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    method VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    medicine_name VARCHAR(255) NOT NULL DEFAULT '',
    salt VARCHAR(255) NOT NULL DEFAULT '',
    batch_number VARCHAR(64) NOT NULL DEFAULT '',
    mfd_date VARCHAR(32) NOT NULL DEFAULT '',
    exp_date VARCHAR(32) NOT NULL DEFAULT '',
    dose VARCHAR(64) NOT NULL DEFAULT '',
    gtin VARCHAR(14) NOT NULL DEFAULT '',
    serial VARCHAR(64) NOT NULL DEFAULT '',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    raw_input TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_mobile_app_schema_scans_user_id
    ON mobile_app_schema.scans (user_id);

CREATE INDEX IF NOT EXISTS ix_mobile_app_schema_scans_created_at
    ON mobile_app_schema.scans (created_at);

CREATE INDEX IF NOT EXISTS ix_mobile_app_schema_scans_user_created
    ON mobile_app_schema.scans (user_id, created_at);

ALTER TABLE mobile_app_schema.scans
    ADD CONSTRAINT fk_mobile_app_schema_scans_user
    FOREIGN KEY (user_id) REFERENCES mobile_app_schema.users (id) ON DELETE CASCADE;
