"""backtest sessions, market-baseline evaluations and model-vs-market comparisons

A backtest is only meaningful next to the market. One invocation of the
protocol is a SESSION: it fixes the competitions, the validation and test
seasons, the configuration and the dataset hash, and everything it produces
hangs off it - one backtest run per model, one evaluation per market
baseline, and one comparison per (run, baseline) on the fixtures both priced,
with a paired-bootstrap interval on the difference. The verdict column cannot
say 'better' unless the whole interval says so.

models.predictions: an interval that was not computed is NULL, not an
interval of width zero. The old NOT NULL forced the second, which states a
certainty nobody has. Backtest predictions carry the session that made them,
so a historical replay can never be mistaken for a live forecast.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE analytics.backtest_sessions (
    id                BIGSERIAL PRIMARY KEY,
    session_uuid      UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name              TEXT        NOT NULL,
    protocol          TEXT        NOT NULL CHECK (protocol IN ('walk_forward', 'holdout')),
    competition_ids   BIGINT[]    NOT NULL,
    validation_season INTEGER,
    test_season       INTEGER     NOT NULL,
    test_from         DATE        NOT NULL,
    test_to           DATE        NOT NULL,
    config            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    selection         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    primary_baseline  TEXT        NOT NULL,
    n_targets         INTEGER     NOT NULL CHECK (n_targets > 0),
    dataset_hash      TEXT        NOT NULL,
    code_version      TEXT        NOT NULL,
    status            TEXT        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    CHECK (test_to >= test_from),
    CHECK (validation_season IS NULL OR validation_season < test_season),
    CHECK (status = 'running' OR finished_at IS NOT NULL)
);
COMMENT ON COLUMN analytics.backtest_sessions.selection IS
  'Hyper-parameter search, scored on the validation season ONLY. The test season is never read to choose anything.';

ALTER TABLE analytics.backtest_runs
    ADD COLUMN session_id BIGINT REFERENCES analytics.backtest_sessions(id) ON DELETE CASCADE,
    ADD COLUMN details    JSONB NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX ON analytics.backtest_runs (session_id);
COMMENT ON COLUMN analytics.backtest_samples.p_actual IS
  '1 if this selection happened, 0 if it did not: the realised outcome, on the probability scale.';

CREATE TABLE analytics.baseline_evaluations (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT       NOT NULL REFERENCES analytics.backtest_sessions(id) ON DELETE CASCADE,
    baseline_key    TEXT         NOT NULL,
    source          TEXT         NOT NULL,
    bookmaker_code  TEXT         NOT NULL,
    price_kind      TEXT         NOT NULL CHECK (price_kind IN ('closing', 'pre_closing', 'snapshot')),
    devig_method    TEXT         NOT NULL CHECK (devig_method IN ('proportional', 'shin', 'power')),
    market_key      TEXT         NOT NULL REFERENCES market.markets(key),
    line            NUMERIC(6,2) NOT NULL DEFAULT 0,
    n_samples       INTEGER      NOT NULL CHECK (n_samples > 0),
    brier_score     NUMERIC(8,6) NOT NULL,
    logloss         NUMERIC(8,6) NOT NULL,
    ece             NUMERIC(8,6) NOT NULL,
    mean_overround  NUMERIC(8,6),
    calibration     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (session_id, baseline_key, market_key, line)
);
COMMENT ON TABLE analytics.baseline_evaluations IS
  'How well the de-vigged market itself predicted the test fixtures: the bar every model has to clear.';

CREATE TABLE analytics.backtest_comparisons (
    id                   BIGSERIAL PRIMARY KEY,
    backtest_run_id      BIGINT       NOT NULL REFERENCES analytics.backtest_runs(id) ON DELETE CASCADE,
    baseline_key         TEXT         NOT NULL,
    market_key           TEXT         NOT NULL REFERENCES market.markets(key),
    line                 NUMERIC(6,2) NOT NULL DEFAULT 0,
    n_common             INTEGER      NOT NULL CHECK (n_common > 0),
    model_logloss        NUMERIC(8,6) NOT NULL,
    baseline_logloss     NUMERIC(8,6) NOT NULL,
    logloss_diff         NUMERIC(9,6) NOT NULL,
    logloss_diff_ci_low  NUMERIC(9,6) NOT NULL,
    logloss_diff_ci_high NUMERIC(9,6) NOT NULL,
    model_brier          NUMERIC(8,6) NOT NULL,
    baseline_brier       NUMERIC(8,6) NOT NULL,
    brier_diff           NUMERIC(9,6) NOT NULL,
    brier_diff_ci_low    NUMERIC(9,6) NOT NULL,
    brier_diff_ci_high   NUMERIC(9,6) NOT NULL,
    verdict              TEXT         NOT NULL CHECK (verdict IN ('worse', 'indistinguishable', 'better')),
    UNIQUE (backtest_run_id, baseline_key, market_key, line),
    CHECK (logloss_diff_ci_low <= logloss_diff AND logloss_diff <= logloss_diff_ci_high),
    CHECK (brier_diff_ci_low <= brier_diff AND brier_diff <= brier_diff_ci_high),
    CHECK (verdict <> 'better' OR logloss_diff_ci_high < 0),
    CHECK (verdict <> 'worse' OR logloss_diff_ci_low > 0),
    CHECK (verdict <> 'indistinguishable' OR (logloss_diff_ci_low <= 0 AND logloss_diff_ci_high >= 0))
);
COMMENT ON COLUMN analytics.backtest_comparisons.logloss_diff IS
  'model minus baseline, per fixture, averaged over the fixtures BOTH priced. Negative means the model scored better.';

ALTER TABLE models.predictions
    ALTER COLUMN p_lo DROP NOT NULL,
    ALTER COLUMN p_hi DROP NOT NULL,
    DROP CONSTRAINT predictions_check,
    ADD CONSTRAINT predictions_interval_check CHECK (
        (p_lo IS NULL AND p_hi IS NULL)
        OR (p_lo IS NOT NULL AND p_hi IS NOT NULL AND p_lo <= p_calibrated AND p_calibrated <= p_hi)),
    ADD COLUMN backtest_session_id BIGINT REFERENCES analytics.backtest_sessions(id) ON DELETE CASCADE;
CREATE INDEX ON models.predictions (backtest_session_id);
COMMENT ON COLUMN models.predictions.backtest_session_id IS
  'Set for predictions made by a historical replay. NULL only for forecasts made before kick-off in real time.';
"""

DOWNGRADE = """
DELETE FROM models.predictions WHERE backtest_session_id IS NOT NULL OR p_lo IS NULL OR p_hi IS NULL;
ALTER TABLE models.predictions
    DROP COLUMN backtest_session_id,
    DROP CONSTRAINT predictions_interval_check,
    ALTER COLUMN p_lo SET NOT NULL,
    ALTER COLUMN p_hi SET NOT NULL,
    ADD CONSTRAINT predictions_check CHECK (p_lo <= p_calibrated AND p_calibrated <= p_hi);
DROP TABLE IF EXISTS analytics.backtest_comparisons;
DROP TABLE IF EXISTS analytics.baseline_evaluations;
DELETE FROM analytics.backtest_runs WHERE session_id IS NOT NULL;
ALTER TABLE analytics.backtest_runs DROP COLUMN details, DROP COLUMN session_id;
DROP TABLE IF EXISTS analytics.backtest_sessions;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
