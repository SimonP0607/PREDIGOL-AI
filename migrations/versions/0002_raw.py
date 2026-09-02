"""raw layer: traceability of everything that entered the system

Source of truth: docs/rebuild/schema_v2/002_raw.sql

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE raw.ingestion_runs (
    id             BIGSERIAL PRIMARY KEY,
    run_uuid       UUID        NOT NULL DEFAULT gen_random_uuid(),
    job_name       TEXT        NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    status         TEXT        NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','completed','failed','aborted')),
    api_calls      INTEGER     NOT NULL DEFAULT 0,
    rows_written   INTEGER     NOT NULL DEFAULT 0,
    errors         INTEGER     NOT NULL DEFAULT 0,
    params         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    notes          TEXT
);
CREATE INDEX ON raw.ingestion_runs (job_name, started_at DESC);
CREATE INDEX ON raw.ingestion_runs (status) WHERE status <> 'completed';

CREATE TABLE raw.ingestion_payloads (
    hash           TEXT        PRIMARY KEY,
    run_id         BIGINT      NOT NULL REFERENCES raw.ingestion_runs(id),
    provider       TEXT        NOT NULL DEFAULT 'api_football',
    endpoint       TEXT        NOT NULL,
    params         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    fetched_at     TIMESTAMPTZ NOT NULL,
    http_status    INTEGER     NOT NULL,
    results_count  INTEGER     NOT NULL DEFAULT 0,
    file_path      TEXT        NOT NULL,
    bytes          INTEGER     NOT NULL
);
CREATE INDEX ON raw.ingestion_payloads (endpoint, fetched_at DESC);
CREATE INDEX ON raw.ingestion_payloads (run_id);

COMMENT ON TABLE raw.ingestion_payloads IS
  'Indice de los payloads guardados en disco (data/raw/...). El cuerpo NO va en la BD.
   params NUNCA contiene la API key: el capturador la elimina antes de persistir.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS raw.ingestion_payloads;
DROP TABLE IF EXISTS raw.ingestion_runs;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
