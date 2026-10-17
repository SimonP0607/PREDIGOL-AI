"""research V2: every run labelled, every model a role, nothing overwritten

GATE F-G re-runs the research on the validated history (feature version fv2.1.0). The
runs made before it are kept as they were and labelled ``LEGACY_RESEARCH_RUN``: their
metrics are what the old inputs gave, and negative results are not deleted. Each new
experiment carries:

* ``run_label`` - ``RESEARCH_V2`` for the rebuild, ``LEGACY_RESEARCH_RUN`` for everything
  before it;
* ``role`` - where it stands against the market (every completed V2 forecast has one; an
  audit, which judges picks rather than a forecast, has none):
    CHAMPION    the best forecast available (today the de-vigged market itself);
    CHALLENGER  beats the champion out of sample, or adds information to it in a blend
                whose interval excludes zero - waiting for an explicit promotion, never
                promoted automatically;
    RESEARCH    the evidence cannot tell yet;
    REJECTED    worse than the champion with sufficient evidence and adds nothing to it
                (kept, visible: a losing model is a result);
* ``data_as_of`` - the newest result the run read, so a reader knows how current it is.

New experiment kinds: ``market`` (a market baseline evaluated as a forecast),
``prospective`` (forecasts stored before kick-off, judged after) and ``audit`` (the
shadow picks' returns decomposed).

Revision ID: 0054
Revises: 0053
"""

from __future__ import annotations

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE analytics.experiments
            ADD COLUMN IF NOT EXISTS run_label TEXT NOT NULL DEFAULT 'RESEARCH_V2'
                CHECK (run_label IN ('LEGACY_RESEARCH_RUN', 'RESEARCH_V2')),
            ADD COLUMN IF NOT EXISTS role TEXT
                CHECK (role IS NULL OR role IN ('CHAMPION', 'CHALLENGER', 'RESEARCH', 'REJECTED')),
            ADD COLUMN IF NOT EXISTS role_reason TEXT,
            ADD COLUMN IF NOT EXISTS segment TEXT,
            ADD COLUMN IF NOT EXISTS data_as_of TIMESTAMPTZ;
        UPDATE analytics.experiments SET run_label = 'LEGACY_RESEARCH_RUN';
        ALTER TABLE analytics.experiments DROP CONSTRAINT IF EXISTS experiments_kind_check;
        ALTER TABLE analytics.experiments ADD CONSTRAINT experiments_kind_check
            CHECK (kind IN ('backtest', 'calibration', 'feature_study', 'ablation', 'market', 'prospective',
                            'audit'));
        ALTER TABLE analytics.experiments ADD CONSTRAINT v2_has_a_role
            CHECK (run_label <> 'RESEARCH_V2' OR status <> 'completed' OR kind = 'audit' OR role IS NOT NULL);
        CREATE INDEX IF NOT EXISTS experiments_label_role ON analytics.experiments (run_label, role);

        ALTER TABLE analytics.backtest_sessions
            ADD COLUMN IF NOT EXISTS run_label TEXT NOT NULL DEFAULT 'RESEARCH_V2'
                CHECK (run_label IN ('LEGACY_RESEARCH_RUN', 'RESEARCH_V2'));
        UPDATE analytics.backtest_sessions SET run_label = 'LEGACY_RESEARCH_RUN';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE analytics.backtest_sessions DROP COLUMN IF EXISTS run_label;
        DROP INDEX IF EXISTS analytics.experiments_label_role;
        ALTER TABLE analytics.experiments DROP CONSTRAINT IF EXISTS v2_has_a_role;
        ALTER TABLE analytics.experiments DROP CONSTRAINT IF EXISTS experiments_kind_check;
        ALTER TABLE analytics.experiments ADD CONSTRAINT experiments_kind_check
            CHECK (kind IN ('backtest', 'calibration', 'feature_study', 'ablation'));
        ALTER TABLE analytics.experiments
            DROP COLUMN IF EXISTS data_as_of, DROP COLUMN IF EXISTS segment, DROP COLUMN IF EXISTS role_reason,
            DROP COLUMN IF EXISTS role, DROP COLUMN IF EXISTS run_label;
    """)
