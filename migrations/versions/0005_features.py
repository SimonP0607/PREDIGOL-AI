"""features layer: feature store with point-in-time correction

Source of truth: docs/rebuild/schema_v2/005_features.sql

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE features.feature_registry (
    name           TEXT PRIMARY KEY,
    feature_group  TEXT NOT NULL,
    entity_type    TEXT NOT NULL CHECK (entity_type IN ('team','league','fixture','player','market')),
    value_type     TEXT NOT NULL CHECK (value_type IN ('numeric','categorical','boolean')),
    description    TEXT NOT NULL,
    window_spec    TEXT,
    depends_on     TEXT[] NOT NULL DEFAULT '{}',
    refresh_policy TEXT NOT NULL DEFAULT 'daily',
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active','blocked','deprecated')),
    blocked_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status <> 'blocked' OR blocked_reason IS NOT NULL)
);
COMMENT ON COLUMN features.feature_registry.status IS
  'blocked = declarada pero no calculable todavia. En el legacy, 8 de 32 dependian
   de ROI/CLV inexistentes y nadie lo marcaba en ningun sitio.';

CREATE TABLE features.feature_values (
    entity_type   TEXT             NOT NULL,
    entity_id     BIGINT           NOT NULL,
    feature_name  TEXT             NOT NULL REFERENCES features.feature_registry(name),
    feature_value DOUBLE PRECISION,
    valid_from    TIMESTAMPTZ      NOT NULL,
    computed_at   TIMESTAMPTZ      NOT NULL DEFAULT now(),
    source_run_id BIGINT           NOT NULL REFERENCES raw.ingestion_runs(id),
    PRIMARY KEY (entity_type, entity_id, feature_name, valid_from)
);
COMMENT ON COLUMN features.feature_values.valid_from IS
  'Instante en que el valor paso a ser CONOCIDO (pitido final, cierre de jornada...),
   no cuando se calculo. Toda lectura filtra valid_from <= data_cutoff_ts.';

CREATE INDEX ON features.feature_values (entity_type, entity_id, valid_from DESC);
CREATE INDEX ON features.feature_values (feature_name, valid_from DESC);
"""

DOWNGRADE = """
DROP TABLE IF EXISTS features.feature_values;
DROP TABLE IF EXISTS features.feature_registry;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
