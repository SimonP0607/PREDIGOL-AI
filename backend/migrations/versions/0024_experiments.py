"""research registry: every experiment, what it asked, what it used, what it found

A backtest session records how models did; an experiment records why it was
run and everything needed to run it again: the question, the model family and
version, the feature version and names, the training, validation and test
periods, the configuration, the dataset hash, the code version, the seed, the
library versions, the metrics, and the files it left on disk with a sha256
for each. ``scripts.experiment reproduce`` re-runs one from this row and
compares.

``research_status`` is where a model stands: RESEARCH by default, CANDIDATE
when it is worth watching, PRODUCTION only with a passed model gate (out of
sample, temporally validated, calibrated, reproducible, stable, and compared
with the market) recorded in ``gate`` - the schema refuses PRODUCTION
without it. A model that does not beat the market stays in RESEARCH.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE analytics.experiments (
    id                   BIGSERIAL PRIMARY KEY,
    experiment_uuid      UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name                 TEXT        NOT NULL,
    kind                 TEXT        NOT NULL CHECK (kind IN ('backtest', 'calibration', 'feature_study', 'ablation')),
    question             TEXT        NOT NULL,
    model_family         TEXT        NOT NULL,
    model_version_id     BIGINT      REFERENCES models.model_versions(id),
    backtest_session_id  BIGINT      REFERENCES analytics.backtest_sessions(id) ON DELETE SET NULL,
    feature_version      TEXT,
    feature_names        TEXT[]      NOT NULL DEFAULT '{}',
    train_from           DATE,
    train_to             DATE,
    validation_from      DATE,
    validation_to        DATE,
    test_from            DATE,
    test_to              DATE,
    config               JSONB       NOT NULL,
    dataset_hash         TEXT,
    code_version         TEXT        NOT NULL,
    seed                 BIGINT,
    environment          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    metrics              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    artifact_path        TEXT,
    artifact_manifest    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status               TEXT        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    research_status      TEXT        NOT NULL DEFAULT 'RESEARCH'
                         CHECK (research_status IN ('RESEARCH', 'CANDIDATE', 'PRODUCTION', 'RETIRED')),
    gate                 JSONB       NOT NULL DEFAULT '{}'::jsonb,
    reproduced_from      BIGINT      REFERENCES analytics.experiments(id),
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at          TIMESTAMPTZ,
    notes                TEXT,
    CHECK (status = 'running' OR finished_at IS NOT NULL),
    CHECK (test_from IS NULL OR train_to IS NULL OR train_to <= test_to),
    CHECK (validation_to IS NULL OR test_from IS NULL OR validation_to < test_from),
    CONSTRAINT production_needs_passed_gate CHECK (
        research_status <> 'PRODUCTION' OR (gate ? 'passed' AND (gate->>'passed')::boolean)),
    CONSTRAINT completed_has_metrics CHECK (status <> 'completed' OR metrics <> '{}'::jsonb)
);
CREATE INDEX ON analytics.experiments (model_family, started_at DESC);

ALTER TABLE analytics.backtest_comparisons ADD COLUMN details JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN analytics.backtest_comparisons.details IS
  'How the interval was computed (moving-block bootstrap over match days from session 2 on), the ranked probability
   score, a Diebold-Mariano test and the minimum detectable log-loss difference; "evidence": insufficient when the
   sample could not have told the difference.';
COMMENT ON TABLE analytics.experiments IS
  'The research registry. One row per experiment, reproducible from its config, dataset hash, code version and seed.';
COMMENT ON COLUMN analytics.experiments.gate IS
  'Model gate evaluation: {"passed": bool, "checks": {"out_of_sample": .., "temporal_validation": .., "calibrated": ..,
   "reproducible": .., "stable": .., "beats_market": ..}}. PRODUCTION requires passed = true.';
"""

DOWNGRADE = """
ALTER TABLE analytics.backtest_comparisons DROP COLUMN IF EXISTS details;
DROP TABLE IF EXISTS analytics.experiments;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
