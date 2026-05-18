CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    name TEXT PRIMARY KEY,
    repo_url TEXT,
    language TEXT,
    last_indexed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS fields (
    fqn TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    producer_service TEXT NOT NULL,
    transport TEXT NOT NULL,
    endpoint_or_topic TEXT NOT NULL,
    field_path TEXT NOT NULL,
    declared_type TEXT NOT NULL,
    nullable BOOLEAN NOT NULL,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    schema_source_path TEXT,
    constraints_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS symbols (
    scip_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    service_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line INTEGER NOT NULL,
    containing_function TEXT,
    visibility TEXT
);

CREATE TABLE IF NOT EXISTS field_usages (
    id BIGSERIAL PRIMARY KEY,
    field_fqn TEXT NOT NULL,
    consumer_service TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line INTEGER NOT NULL,
    expression TEXT NOT NULL,
    surrounding_context TEXT,
    containing_function TEXT,
    scip_symbol_id TEXT,
    UNIQUE (field_fqn, consumer_service, file_path, line)
);

CREATE TABLE IF NOT EXISTS history_signals (
    id BIGSERIAL PRIMARY KEY,
    field_fqn TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    commit_message TEXT NOT NULL,
    author TEXT NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL,
    risk_keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS semantic_profiles (
    field_fqn TEXT PRIMARY KEY,
    unit TEXT,
    domain TEXT,
    invariants_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence DOUBLE PRECISION NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL,
    source_commit_hash TEXT
);

CREATE TABLE IF NOT EXISTS consumer_beliefs (
    id BIGSERIAL PRIMARY KEY,
    consumer_service TEXT NOT NULL,
    field_fqn TEXT NOT NULL,
    assumed_unit TEXT,
    assumed_type TEXT,
    assumed_nullable BOOLEAN,
    assumed_format TEXT,
    inferred_constraints_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    usage_expressions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence DOUBLE PRECISION NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL,
    source_file_hash TEXT,
    UNIQUE (consumer_service, field_fqn)
);

CREATE TABLE IF NOT EXISTS disagreements (
    id BIGSERIAL PRIMARY KEY,
    field_fqn TEXT NOT NULL,
    consumer_service TEXT NOT NULL,
    kind TEXT NOT NULL,
    producer_says TEXT NOT NULL,
    consumer_assumes TEXT NOT NULL,
    severity TEXT NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation TEXT,
    detected_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    fix_pr_url TEXT
);

CREATE TABLE IF NOT EXISTS indexed_files (
    service_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (service_name, file_path)
);

CREATE INDEX IF NOT EXISTS idx_usages_field ON field_usages (field_fqn);
CREATE INDEX IF NOT EXISTS idx_usages_consumer ON field_usages (consumer_service);
CREATE INDEX IF NOT EXISTS idx_beliefs_field ON consumer_beliefs (field_fqn);
CREATE INDEX IF NOT EXISTS idx_disagreements_field ON disagreements (field_fqn);
CREATE INDEX IF NOT EXISTS idx_disagreements_unresolved ON disagreements (resolved_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_history_field ON history_signals (field_fqn);

CREATE UNIQUE INDEX IF NOT EXISTS idx_disagreements_active_unique
    ON disagreements (field_fqn, consumer_service, kind)
    WHERE resolved_at IS NULL;
