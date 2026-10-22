"""The forecast spec in force is a promotion, not "whatever backtest finished last" (plan F0, defect 2)

WHY THIS EXISTS
---------------
``fbi.predictions.forecast`` read the hyper-parameters it forecasts with - the time decay ``xi`` and the shrinkage
``penalty`` of each goal model, the training window, the competitions the feature models train on - from the LATEST
COMPLETED row of ``analytics.backtest_sessions``. The weekly ``research_v2`` job stores a completed session whenever the
model code or the dataset version changes, or the last one is four weeks old, and ``scripts.run_backtest --apply`` stores
one every time somebody runs it. So production's parameters could change in any week with no decision, no record of the
change and no way back, and a research run was, without anyone saying so, a release.

WHAT IT IS
----------
``analytics.promoted_forecast_spec`` is an append-only history of promotions. The newest row is the spec in force and the
only thing the forecast reads. A row carries the backtest session the spec came from (the foreign key refuses to delete a
session that was ever promoted), a COPY of the spec (editing a session afterwards cannot move production), who promoted
it, the reason, the row it replaced and the evidence read at the time. Rolling back is promoting an earlier session again;
the history is never rewritten. ``python -m scripts.promote_forecast_spec`` shows what a promotion would change (dry run
by default) and applies it on request. Nothing promotes by itself: ``research_v2`` keeps writing sessions, and a session
is research until a person promotes it.

THE SEED
--------
Deploying must not change what production forecasts with. The row inserted here is built from the session the forecast was
ALREADY reading (the latest completed one, by the rule ``current_spec`` used) with the same extraction, and is marked
``promoted_by = 'system'``, ``evidence.seed = true``. On a database with no completed session nothing is inserted and the
forecast says it has no spec, as it did with no session.

ALSO IN THIS REVISION (documentation only, plan F0 defect 7)
-------------------------------------------------------------
``COMMENT ON COLUMN ai.pick_postmortems.clv``: the column has always held the PRICE MOVE against the same bookmaker's
closing price, not the closing-line value; the rows are history and keep their name. The comment says so where a person
reading the schema will see it.

Additive only. The downgrade drops the table (a promotion history is a record of decisions; export it first if the
revision is being undone on a database that has had promotions) and the trigger function, and restores the column comment
to none.

Revision ID: 0079
Revises: 0078
"""

from __future__ import annotations

from alembic import op

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None

SPEC_VERSION = "spec-v1"

SEED_SQL = f"""
INSERT INTO analytics.promoted_forecast_spec (session_id, promoted_by, reason, spec, evidence)
SELECT s.id, 'system',
       'Seeded by migration 0079 with the session the forecast was already reading (the latest completed backtest '
       'session): nothing changes in what production forecasts with. From now on the spec changes only by promotion.',
       jsonb_build_object(
           'version', '{SPEC_VERSION}',
           'competition_ids', to_jsonb(s.competition_ids),
           'history_days', COALESCE(s.config -> 'history_days', to_jsonb(730)),
           'goal', COALESCE((SELECT jsonb_object_agg(e.key, jsonb_build_object('xi', e.value -> 'chosen' -> 'xi',
                                                                              'penalty', e.value -> 'chosen' -> 'penalty'))
                               FROM jsonb_each(s.selection) AS e
                              WHERE e.key IN ('poisson', 'dixon_coles')), '{{}}'::jsonb)),
       jsonb_build_object('seed', true, 'session', s.name, 'finished_at', s.finished_at,
                          'dataset_hash', s.dataset_hash, 'code_version', s.code_version,
                          'n_targets', s.n_targets, 'validation_season', s.validation_season,
                          'test_season', s.test_season,
                          'changes', jsonb_build_array('seeded from the session already in use'))
  FROM analytics.backtest_sessions s
 WHERE s.status = 'completed'
 ORDER BY s.finished_at DESC NULLS LAST, s.id DESC
 LIMIT 1
"""
"""The rule of ``fbi.predictions.forecast.current_spec`` before this revision (latest completed, by finish time then id)
and its extraction (goal models poisson and dixon_coles, ``selection[kind].chosen.xi/penalty``, ``config.history_days``
with 730 as the default), copied value for value: the JSON numbers are not cast, so no float changes on the way."""


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new; the foreign
    # key takes a short lock on analytics.backtest_sessions.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE OR REPLACE FUNCTION analytics.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.analytics_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'analytics.%: append-only (% refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$""")
    op.execute(f"""
        CREATE TABLE analytics.promoted_forecast_spec (
            id          BIGSERIAL   PRIMARY KEY,
            session_id  BIGINT      NOT NULL REFERENCES analytics.backtest_sessions(id) ON DELETE RESTRICT,
            promoted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            promoted_by TEXT        NOT NULL CHECK (promoted_by IN ('owner', 'system')),
            reason      TEXT        NOT NULL CHECK (length(btrim(reason)) >= 10),
            spec        JSONB       NOT NULL CHECK (
                            jsonb_typeof(spec) = 'object'
                            AND spec ->> 'version' = '{SPEC_VERSION}'
                            AND jsonb_typeof(spec -> 'competition_ids') = 'array'
                            AND jsonb_typeof(spec -> 'history_days') = 'number'
                            AND jsonb_typeof(spec -> 'goal') = 'object'),
            previous_id BIGINT      REFERENCES analytics.promoted_forecast_spec(id),
            evidence    JSONB       NOT NULL DEFAULT '{{}}'::jsonb
        )""")
    op.execute("""
        COMMENT ON TABLE analytics.promoted_forecast_spec IS
        'The hyper-parameters the real-time forecast uses, as a history of explicit promotions: the newest row is the spec
         in force (fbi.predictions.spec.current_spec). spec is a copy of what the backtest session chose (xi and penalty of
         each goal model, training window, competitions of the feature models), so editing a session cannot move
         production. A newer backtest or a research_v2 run changes nothing here; only a promotion does
         (python -m scripts.promote_forecast_spec). Append-only: a rollback is a new promotion of an earlier session.
         The first row, promoted_by system, is the session production was already using when this table was created
         (plan F0, defect 2).'""")
    op.execute("CREATE TRIGGER promoted_forecast_spec_append_only BEFORE UPDATE OR DELETE "
               "ON analytics.promoted_forecast_spec FOR EACH ROW EXECUTE FUNCTION analytics.refuse_change()")
    op.execute(SEED_SQL)
    op.execute("""
        COMMENT ON COLUMN ai.pick_postmortems.clv IS
        'The PRICE MOVE (odds / the same bookmaker''s closing odds - 1), not the closing-line value, in every row since
         pm-v1: the name is kept because the rows are history. The CLV of a row is derived from its odds and the closing
         probability stored beside it (fbi.ai.pick_postmortem.stored_clv; fbi.market.closing_value, clv-v1). Plan F0,
         defect 7.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("COMMENT ON COLUMN ai.pick_postmortems.clv IS NULL")
    op.execute("DROP TABLE IF EXISTS analytics.promoted_forecast_spec")
    op.execute("DROP FUNCTION IF EXISTS analytics.refuse_change()")
