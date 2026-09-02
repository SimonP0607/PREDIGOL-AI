"""audit layer

Source of truth: docs/rebuild/schema_v2/009_audit.sql

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE audit.data_quality_checks (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT      NOT NULL REFERENCES raw.ingestion_runs(id),
    check_name  TEXT        NOT NULL,
    scope       TEXT        NOT NULL,
    severity    TEXT        NOT NULL CHECK (severity IN ('info','warning','error','critical')),
    expected    TEXT,
    actual      TEXT,
    passed      BOOLEAN     NOT NULL,
    details     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON audit.data_quality_checks (checked_at DESC);
CREATE INDEX ON audit.data_quality_checks (passed, severity) WHERE NOT passed;

CREATE TABLE audit.decision_audit (
    id          BIGSERIAL PRIMARY KEY,
    pick_id     BIGINT      REFERENCES picks.picks(id) ON DELETE CASCADE,
    stage       TEXT        NOT NULL,
    input_hash  TEXT        NOT NULL,
    output      JSONB       NOT NULL,
    duration_ms INTEGER,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON audit.decision_audit (pick_id, stage);
"""

DOWNGRADE = """
DROP TABLE IF EXISTS audit.decision_audit;
DROP TABLE IF EXISTS audit.data_quality_checks;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
