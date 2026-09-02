"""analytics layer: backtests and metrics. Rebuildable.

Source of truth: docs/rebuild/schema_v2/008_analytics.sql

DELIBERATE, DOCUMENTED DEVIATION FROM THE SOURCE DDL
----------------------------------------------------
``clv_mean``       -> ``near_close_lv_mean``
``closing_odds``   -> ``near_close_odds``
``clv``            -> ``line_value``
Same reason as revision 0007: nothing is called a closing line before it has
been shown to be one. Types, constraints and semantics are otherwise identical.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE analytics.backtest_runs (
    id                 BIGSERIAL PRIMARY KEY,
    run_uuid           UUID        NOT NULL DEFAULT gen_random_uuid(),
    name               TEXT        NOT NULL,
    model_version_id   BIGINT      NOT NULL REFERENCES models.model_versions(id),
    calibrator_id      BIGINT      REFERENCES models.calibrators(id),
    competition_ids    BIGINT[]    NOT NULL,
    test_from          DATE        NOT NULL,
    test_to            DATE        NOT NULL,
    protocol           TEXT        NOT NULL CHECK (protocol IN ('walk_forward','holdout')),
    train_window       TEXT        NOT NULL,
    config             JSONB       NOT NULL DEFAULT '{}'::jsonb,
    code_version       TEXT        NOT NULL,
    dataset_hash       TEXT        NOT NULL,
    -- calidad predictiva: SIEMPRE calculable
    n_samples          INTEGER     NOT NULL CHECK (n_samples > 0),
    accuracy_pct       NUMERIC(6,3)  NOT NULL,
    brier_score        NUMERIC(8,6)  NOT NULL,
    logloss            NUMERIC(8,6)  NOT NULL,
    ece                NUMERIC(8,6)  NOT NULL,
    -- rendimiento economico: NULL si no hubo cuotas reales. NUNCA cero.
    odds_source        TEXT,
    n_bets             INTEGER,
    total_stake_units  NUMERIC(14,4),
    total_profit_units NUMERIC(14,4),
    roi_pct            NUMERIC(10,4),
    yield_pct          NUMERIC(10,4),
    near_close_lv_mean NUMERIC(8,6),
    max_drawdown_units NUMERIC(14,4),
    roi_ci_low         NUMERIC(10,4),
    roi_ci_high        NUMERIC(10,4),
    status             TEXT        NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running','completed','failed')),
    started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at        TIMESTAMPTZ,
    CHECK (roi_pct IS NULL OR (total_stake_units IS NOT NULL AND total_stake_units > 0)),
    CHECK (n_bets IS NULL OR odds_source IS NOT NULL)
);
COMMENT ON COLUMN analytics.backtest_runs.accuracy_pct IS
  'Calidad predictiva. NO es rentabilidad. El legacy guardaba accuracy en un campo
   llamado roi_pct, y eso hizo creer durante meses en un ROI del 57%.';
COMMENT ON COLUMN analytics.backtest_runs.roi_pct IS
  'SUM(profit_units)/SUM(stake_units)*100. NULL cuando no hay cuotas reales.';
COMMENT ON COLUMN analytics.backtest_runs.near_close_lv_mean IS
  'Valor medio frente al snapshot mas proximo al cierre disponible. NO se llama
   clv_mean porque no esta demostrado que ese snapshot sea la linea de cierre.';

CREATE TABLE analytics.backtest_samples (
    id              BIGSERIAL PRIMARY KEY,
    backtest_run_id BIGINT       NOT NULL REFERENCES analytics.backtest_runs(id) ON DELETE CASCADE,
    fixture_id      BIGINT       NOT NULL REFERENCES core.fixtures(id),
    market_key      TEXT         NOT NULL,
    selection       TEXT         NOT NULL,
    line            NUMERIC(6,2) NOT NULL DEFAULT 0,
    p_calibrated    NUMERIC(8,6) NOT NULL,
    p_market_fair   NUMERIC(8,6),
    market_odds     NUMERIC(9,3),
    near_close_odds NUMERIC(9,3),
    was_bet         BOOLEAN      NOT NULL DEFAULT false,
    stake_units     NUMERIC(8,4),
    outcome_correct BOOLEAN      NOT NULL,
    p_actual        NUMERIC(8,6) NOT NULL,
    profit_units    NUMERIC(10,4),
    line_value      NUMERIC(8,6)
);
CREATE INDEX ON analytics.backtest_samples (backtest_run_id, market_key);

CREATE TABLE analytics.bankroll_ledger (
    id            BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ NOT NULL,
    pick_id       BIGINT REFERENCES picks.picks(id),
    kind          TEXT NOT NULL CHECK (kind IN ('stake','settlement','adjustment')),
    units_delta   NUMERIC(12,4) NOT NULL,
    units_balance NUMERIC(14,4) NOT NULL,
    note          TEXT
);
COMMENT ON TABLE analytics.bankroll_ledger IS
  'Unidades teoricas. La plataforma NO custodia dinero real.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS analytics.bankroll_ledger;
DROP TABLE IF EXISTS analytics.backtest_samples;
DROP TABLE IF EXISTS analytics.backtest_runs;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
