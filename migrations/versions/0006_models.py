"""models layer: registry, versions, calibrators and predictions

Source of truth: docs/rebuild/schema_v2/006_models.sql

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE models.model_registry (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    family      TEXT NOT NULL CHECK (family IN
                ('baseline','rating','goals','ml','ensemble')),
    description TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE models.model_versions (
    id               BIGSERIAL PRIMARY KEY,
    model_id         BIGINT      NOT NULL REFERENCES models.model_registry(id),
    version          TEXT        NOT NULL,
    hyperparameters  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    feature_names    TEXT[]      NOT NULL DEFAULT '{}',
    train_from       DATE        NOT NULL,
    train_to         DATE        NOT NULL,
    n_train          INTEGER     NOT NULL CHECK (n_train > 0),
    code_version     TEXT        NOT NULL,
    artifact_path    TEXT,
    status           TEXT        NOT NULL DEFAULT 'experimental'
                     CHECK (status IN ('experimental','shadow','champion','retired')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model_id, version),
    CHECK (train_to > train_from)
);
CREATE UNIQUE INDEX one_champion_per_model
    ON models.model_versions (model_id) WHERE status = 'champion';

CREATE TABLE models.calibrators (
    id                BIGSERIAL PRIMARY KEY,
    model_version_id  BIGINT       NOT NULL REFERENCES models.model_versions(id),
    market_key        TEXT         NOT NULL REFERENCES market.markets(key),
    scope             TEXT         NOT NULL CHECK (scope IN ('global','competition_type','competition')),
    competition_id    BIGINT       REFERENCES core.competitions(id),
    method            TEXT         NOT NULL CHECK (method IN
                      ('isotonic','platt','beta','venn_abers')),
    params            JSONB        NOT NULL,
    n_train           INTEGER      NOT NULL CHECK (n_train >= 200),
    train_from        DATE         NOT NULL,
    train_to          DATE         NOT NULL,
    n_val             INTEGER      NOT NULL CHECK (n_val >= 100),
    val_from          DATE         NOT NULL,
    val_to            DATE         NOT NULL,
    val_ece           NUMERIC(8,6) NOT NULL,
    val_mce           NUMERIC(8,6) NOT NULL,
    val_brier         NUMERIC(8,6) NOT NULL,
    val_logloss       NUMERIC(8,6) NOT NULL,
    reliability_weight NUMERIC(6,4) NOT NULL CHECK (reliability_weight BETWEEN 0 AND 1),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (val_from > train_to),
    CHECK (scope <> 'competition' OR competition_id IS NOT NULL)
);
COMMENT ON TABLE models.calibrators IS
  'n_val NOT NULL y CHECK(val_from > train_to) hacen estructuralmente imposible el fallo
   del legacy: 128 de 152 calibradores sin validacion y ECE=0.0 exacto en 134.';

CREATE TABLE models.predictions (
    id               BIGSERIAL PRIMARY KEY,
    fixture_id       BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    model_version_id BIGINT       NOT NULL REFERENCES models.model_versions(id),
    calibrator_id    BIGINT       REFERENCES models.calibrators(id),
    market_key       TEXT         NOT NULL REFERENCES market.markets(key),
    selection        TEXT         NOT NULL,
    line             NUMERIC(6,2) NOT NULL DEFAULT 0,
    p_raw            NUMERIC(8,6) NOT NULL CHECK (p_raw BETWEEN 0 AND 1),
    p_calibrated     NUMERIC(8,6) NOT NULL CHECK (p_calibrated BETWEEN 0 AND 1),
    p_lo             NUMERIC(8,6) NOT NULL,
    p_hi             NUMERIC(8,6) NOT NULL,
    feature_set_hash TEXT         NOT NULL,
    data_cutoff_ts   TIMESTAMPTZ  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (fixture_id, model_version_id, market_key, selection, line, data_cutoff_ts),
    CHECK (p_lo <= p_calibrated AND p_calibrated <= p_hi)
);
CREATE INDEX ON models.predictions (fixture_id, market_key);
"""

DOWNGRADE = """
DROP TABLE IF EXISTS models.predictions;
DROP TABLE IF EXISTS models.calibrators;
DROP INDEX IF EXISTS models.one_champion_per_model;
DROP TABLE IF EXISTS models.model_versions;
DROP TABLE IF EXISTS models.model_registry;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
