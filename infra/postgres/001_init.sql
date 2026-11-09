CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(200) NOT NULL,
    current_version_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_key TEXT NOT NULL,
    checksum_sha256 VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS timeline_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    parent_version_id UUID NULL REFERENCES timeline_versions(id),
    timeline_json JSONB NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128),
    restored_from_version_id UUID NULL REFERENCES timeline_versions(id),
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_timeline_version_number UNIQUE(project_id, version),
    CONSTRAINT uq_timeline_version_idempotency UNIQUE(project_id, idempotency_key)
);

ALTER TABLE projects
    ADD CONSTRAINT fk_projects_current_version
    FOREIGN KEY (current_version_id) REFERENCES timeline_versions(id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS timeline_asset_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timeline_version_id UUID NOT NULL REFERENCES timeline_versions(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
    CONSTRAINT uq_timeline_asset_reference UNIQUE(timeline_version_id, asset_id)
);

CREATE INDEX IF NOT EXISTS ix_timeline_versions_project_version
    ON timeline_versions(project_id, version DESC);
CREATE INDEX IF NOT EXISTS ix_timeline_versions_content_hash
    ON timeline_versions(project_id, content_hash);
