"""PrediGol Intelligence: calibration, the decision layer, outcomes, post-mortems, memory, the daily learning report,
market discovery, data-leakage audits and the runs that produce them (``docs/intelligence/PREDIGOL_INTELLIGENCE.md``)

A new schema ``intel`` beside ``ai`` (context) and ``picks`` (the quantitative shadow picks), so the four layers stay
apart: DATA (core, market, raw) -> MODELS (models, picks shadow, and here the per-market calibrators) -> PREDIGOL
INTELLIGENCE (ai) -> DECISION (here). Nothing here can change a pick, a probability of the models, a rule users see or
publish anything: ``picks_publishing_disabled`` still holds and every decision is SHADOW.

Append-only by trigger (``intel.refuse_change``, the same contract as ``ai.refuse_change``): calibrators and their
evaluations, promotions, decisions, day selections, outcomes, post-mortems, memory snapshots, daily reports, market
registry snapshots and audit checks. A correction is a new row; a past decision is never rewritten after kick-off or
after its result. The owner can lift the guard inside one transaction (``SET LOCAL fbi.intel_maintenance = 'on'``)
for a documented retention task; nothing in the application does. ``intel.runs`` is the one mutable table: a run is
opened, then closed (or marked interrupted by the next worker).

``ai.budget_alerts`` learns the 50 % threshold (the month's US$180 budget alerts at 50 / 70 / 85 / 95 / 100 %).

Revision ID: 0076
Revises: 0075
"""

from __future__ import annotations

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None

APPEND_ONLY = ("calibrators", "calibrator_evaluations", "promotions", "decisions", "day_selections",
               "decision_outcomes", "postmortems", "entity_memory", "daily_reports", "market_registry",
               "audit_checks")

STATES = ("'RECHAZADO', 'INVESTIGACION', 'CAUTELA', 'APROBADO', 'PICK_DEL_DIA', 'CANDIDATO_PARLAY', "
          "'PICK_PREMIUM'")


def upgrade() -> None:
    op.execute(f"""
        CREATE SCHEMA IF NOT EXISTS intel;
        COMMENT ON SCHEMA intel IS
          'PrediGol Intelligence: per-market calibration, the decision layer (10 filters, states, score, stake), '
          'outcomes, post-mortems, longitudinal memory, the daily learning report, market discovery, leakage audits. '
          'Shadow only.';

        CREATE OR REPLACE FUNCTION intel.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.intel_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'intel.%: append-only (% refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$;

        -- ── every run of a PrediGol Intelligence job (observability) ─────────────────────
        CREATE TABLE intel.runs (
            id           BIGSERIAL     PRIMARY KEY,
            job          TEXT          NOT NULL CHECK (job IN ('decide', 'nightly', 'weekly', 'calibrate', 'select',
                                       'backfill', 'manual')),
            started_at   TIMESTAMPTZ   NOT NULL,
            finished_at  TIMESTAMPTZ,
            status       TEXT          NOT NULL CHECK (status IN ('running', 'ok', 'partial', 'failed', 'skipped',
                                       'interrupted')),
            duration_ms  INTEGER       CHECK (duration_ms IS NULL OR duration_ms >= 0),
            counts       JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            errors       JSONB         NOT NULL DEFAULT '[]'::jsonb,
            cost_usd     NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            code_version TEXT,
            versions     JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            CHECK ((status = 'running') = (finished_at IS NULL))
        );
        CREATE INDEX intel_runs_job ON intel.runs (job, started_at DESC);

        -- ── CAPA 2: per-market calibration of the model probability ─────────────────────
        CREATE TABLE intel.calibrators (
            id           BIGSERIAL     PRIMARY KEY,
            market_key   TEXT          NOT NULL REFERENCES market.markets(key),
            model_name   TEXT          NOT NULL,
            method       TEXT          NOT NULL CHECK (method IN ('logit2', 'platt', 'identity')),
            version      TEXT          NOT NULL,
            params       JSONB         NOT NULL,
            known_at     TIMESTAMPTZ   NOT NULL,
            fitted_at    TIMESTAMPTZ   NOT NULL,
            train_from   DATE,
            train_to     DATE,
            n_train      INTEGER       NOT NULL CHECK (n_train >= 0),
            train_hash   TEXT          NOT NULL,
            settled_max  TIMESTAMPTZ,
            wf           JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            gate         JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            code_version TEXT,
            UNIQUE (market_key, model_name, method, version, known_at),
            CHECK (fitted_at >= known_at),
            CHECK (settled_max IS NULL OR settled_max < known_at),
            CHECK (train_to IS NULL OR train_from <= train_to)
        );
        COMMENT ON TABLE intel.calibrators IS
          'One fit of a calibrator of the model probability for (market, model): only picks settled before known_at '
          '(settled_max < known_at). wf: the method''s walk-forward evaluation up to known_at; gate: calib-gate-v1 and '
          'edge-gate-v1 at fit time. The role (CHAMPION, CHALLENGER...) is the newest intel.promotions row.';

        CREATE TABLE intel.calibrator_evaluations (
            id             BIGSERIAL     PRIMARY KEY,
            calibrator_id  BIGINT        NOT NULL REFERENCES intel.calibrators(id),
            day            DATE          NOT NULL,
            evaluated_at   TIMESTAMPTZ   NOT NULL,
            n              INTEGER       NOT NULL CHECK (n >= 0),
            logloss_cal    NUMERIC(10,6),
            logloss_raw    NUMERIC(10,6),
            logloss_market NUMERIC(10,6),
            brier_cal      NUMERIC(10,6),
            brier_raw      NUMERIC(10,6),
            brier_market   NUMERIC(10,6),
            ece_cal        NUMERIC(10,6),
            ece_raw        NUMERIC(10,6),
            rule_n         INTEGER,
            rule_clv       NUMERIC(10,6),
            rule_roi       NUMERIC(10,6),
            UNIQUE (calibrator_id, day)
        );
        COMMENT ON TABLE intel.calibrator_evaluations IS
          'Prospective out-of-sample evaluation of a calibrator on one Bogota day of settled selections, all of them '
          'after its known_at.';

        CREATE TABLE intel.promotions (
            id          BIGSERIAL   PRIMARY KEY,
            at          TIMESTAMPTZ NOT NULL,
            entity      TEXT        NOT NULL CHECK (entity IN ('calibrator', 'market_edge', 'selection_rule', 'model')),
            market_key  TEXT,
            model_name  TEXT,
            entity_id   BIGINT,
            from_role   TEXT,
            to_role     TEXT        NOT NULL CHECK (to_role IN ('CHAMPION', 'CHALLENGER', 'RETIRED', 'REJECTED',
                                    'VALIDATED', 'NOT_VALIDATED')),
            gate_version TEXT       NOT NULL,
            criteria    JSONB       NOT NULL,
            reason      TEXT        NOT NULL,
            decided_by  TEXT        NOT NULL CHECK (decided_by IN ('system', 'owner'))
        );
        CREATE INDEX intel_promotions_entity ON intel.promotions (entity, market_key, model_name, at DESC);

        -- ── CAPA 4: every evaluation of a candidate ─────────────────────────────────────
        CREATE TABLE intel.decisions (
            id               BIGSERIAL     PRIMARY KEY,
            decision_version TEXT          NOT NULL,
            known_at         TIMESTAMPTZ   NOT NULL,
            checkpoint       TEXT          NOT NULL,
            fixture_id       BIGINT        NOT NULL REFERENCES core.fixtures(id),
            kickoff_at       TIMESTAMPTZ   NOT NULL,
            market_key       TEXT          NOT NULL,
            selection        TEXT          NOT NULL,
            line             NUMERIC(6,2)  NOT NULL DEFAULT 0,
            pick_id          BIGINT        REFERENCES picks.picks(id),
            model_name       TEXT          NOT NULL,
            model_version_id BIGINT,
            odds             NUMERIC(9,3),
            bookmaker_id     INTEGER,
            price_at         TIMESTAMPTZ,
            n_bookmakers     INTEGER,
            p_model          NUMERIC(8,6)  NOT NULL CHECK (p_model > 0 AND p_model < 1),
            p_low            NUMERIC(8,6),
            p_high           NUMERIC(8,6),
            p_push           NUMERIC(8,6),
            p_cal            NUMERIC(8,6)  CHECK (p_cal IS NULL OR (p_cal > 0 AND p_cal < 1)),
            calibrator_id    BIGINT        REFERENCES intel.calibrators(id),
            calibrator_role  TEXT,
            p_market         NUMERIC(8,6),
            ev_raw           NUMERIC(10,6),
            edge_raw         NUMERIC(10,6),
            ev_cal           NUMERIC(10,6),
            edge_cal         NUMERIC(10,6),
            filters          JSONB         NOT NULL,
            state            TEXT          NOT NULL CHECK (state IN ({STATES})),
            reasons          TEXT[]        NOT NULL DEFAULT '{{}}',
            premium          BOOLEAN       NOT NULL DEFAULT false,
            parlay_eligible  BOOLEAN       NOT NULL DEFAULT false,
            score            NUMERIC(6,2)  CHECK (score IS NULL OR score BETWEEN 0 AND 100),
            score_version    TEXT,
            score_components JSONB,
            stake_units      NUMERIC(6,2)  NOT NULL DEFAULT 0 CHECK (stake_units >= 0 AND stake_units <= 2),
            stake_version    TEXT,
            stake_components JSONB,
            context_status   TEXT          NOT NULL CHECK (context_status IN ('FULL', 'PARTIAL', 'LIMITED', 'PENDING',
                                           'AI_OFF')),
            context          JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            review_id        BIGINT,
            evidence_ids     BIGINT[]      NOT NULL DEFAULT '{{}}',
            input_hash       TEXT          NOT NULL,
            code_version     TEXT,
            created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CHECK (known_at < kickoff_at),
            CHECK (price_at IS NULL OR price_at <= known_at),
            CHECK (state NOT IN ('RECHAZADO', 'INVESTIGACION') OR stake_units = 0)
        );
        CREATE UNIQUE INDEX intel_decisions_once ON intel.decisions
            (fixture_id, market_key, selection, line, decision_version, checkpoint, input_hash);
        CREATE INDEX intel_decisions_selection ON intel.decisions (fixture_id, market_key, selection, line,
                                                                   known_at DESC);
        CREATE INDEX intel_decisions_known ON intel.decisions (known_at);
        CREATE INDEX intel_decisions_state ON intel.decisions (state, known_at DESC) WHERE state <> 'RECHAZADO';
        COMMENT ON TABLE intel.decisions IS
          'Decision layer (decision-v1): one evaluation of a candidate selection at a checkpoint - the price, the model '
          'and calibrated probabilities, the market, the 10 filters, the state, the PrediGol Pick Score and the stake '
          'with their components, the context PrediGol Intelligence had. known_at is the moment of the decision: '
          'everything it used was known then (intel.audit_checks verifies it).';

        CREATE TABLE intel.day_selections (
            id           BIGSERIAL     PRIMARY KEY,
            day          DATE          NOT NULL,
            rule_version TEXT          NOT NULL,
            kind         TEXT          NOT NULL CHECK (kind IN ('pick', 'parlay')),
            rank         SMALLINT      NOT NULL CHECK (rank >= 1),
            decision_ids BIGINT[]      NOT NULL CHECK (cardinality(decision_ids) >= 1),
            selected_at  TIMESTAMPTZ   NOT NULL,
            odds         NUMERIC(10,3) NOT NULL CHECK (odds > 1),
            p_est        NUMERIC(8,6)  NOT NULL CHECK (p_est > 0 AND p_est < 1),
            ev           NUMERIC(10,6) NOT NULL,
            stake_units  NUMERIC(6,2)  NOT NULL CHECK (stake_units >= 0),
            correlation  JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            detail       JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            UNIQUE (day, rule_version, kind, rank)
        );
        COMMENT ON TABLE intel.day_selections IS
          'PICKS DEL DIA (daily-set-v6, shadow) and parlays built only from approved decisions, frozen when chosen.';

        CREATE TABLE intel.decision_outcomes (
            decision_id         BIGINT        PRIMARY KEY REFERENCES intel.decisions(id),
            settled_at          TIMESTAMPTZ   NOT NULL,
            result_status       TEXT          NOT NULL CHECK (result_status IN ('win', 'loss', 'push', 'half_win',
                                              'half_loss', 'void')),
            profit_flat         NUMERIC(10,4) NOT NULL,
            profit_staked       NUMERIC(10,4) NOT NULL,
            close_p_fair        NUMERIC(8,6),
            close_odds          NUMERIC(9,3),
            close_as_of         TIMESTAMPTZ,
            close_minutes_to_ko INTEGER,
            clv                 NUMERIC(10,6),
            version             TEXT          NOT NULL,
            computed_at         TIMESTAMPTZ   NOT NULL
        );
        COMMENT ON COLUMN intel.decision_outcomes.clv IS
          'odds of the decision x de-vigged (Shin) consensus probability of the last pre-match snapshot - 1: the '
          'expected value of the price taken at the closing fair probability.';

        CREATE TABLE intel.postmortems (
            id               BIGSERIAL   PRIMARY KEY,
            decision_id      BIGINT      NOT NULL REFERENCES intel.decisions(id),
            fixture_id       BIGINT      NOT NULL REFERENCES core.fixtures(id),
            created_at       TIMESTAMPTZ NOT NULL,
            version          TEXT        NOT NULL,
            outcome          TEXT        NOT NULL CHECK (outcome IN ('won', 'lost', 'void', 'push', 'half_won',
                                         'half_lost')),
            decision_quality TEXT        NOT NULL CHECK (decision_quality IN ('GOOD', 'NEUTRAL', 'BAD', 'UNKNOWN')),
            verdict          TEXT        NOT NULL CHECK (verdict IN ('MERECIDO', 'VARIANZA', 'SUERTE', 'ERROR', 'NULO',
                                         'SIN_DATOS')),
            causes           JSONB       NOT NULL DEFAULT '[]'::jsonb,
            answers          JSONB       NOT NULL,
            evidence         JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            UNIQUE (decision_id, version)
        );

        CREATE TABLE intel.entity_memory (
            id          BIGSERIAL   PRIMARY KEY,
            entity_type TEXT        NOT NULL CHECK (entity_type IN ('team', 'player', 'coach', 'referee', 'competition',
                                    'market')),
            entity_id   TEXT        NOT NULL,
            entity_name TEXT,
            aspect      TEXT        NOT NULL,
            as_of_day   DATE        NOT NULL,
            built_at    TIMESTAMPTZ NOT NULL,
            version     TEXT        NOT NULL,
            stats       JSONB       NOT NULL,
            delta       JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            sources     JSONB       NOT NULL DEFAULT '[]'::jsonb,
            UNIQUE (entity_type, entity_id, aspect, as_of_day, version)
        );
        CREATE INDEX intel_memory_entity ON intel.entity_memory (entity_type, entity_id, aspect, as_of_day DESC);
        COMMENT ON TABLE intel.entity_memory IS
          'Longitudinal memory: the cumulative state of an entity x aspect (team x market, competition x market, '
          'referee discipline, coach, player availability, market) as of a day, written only when something of it '
          'changed that day. A streak is a signal to investigate, never a rule.';

        CREATE TABLE intel.daily_reports (
            id           BIGSERIAL   PRIMARY KEY,
            day          DATE        NOT NULL,
            revision     SMALLINT    NOT NULL CHECK (revision >= 1),
            built_at     TIMESTAMPTZ NOT NULL,
            version      TEXT        NOT NULL,
            content      JSONB       NOT NULL,
            text         TEXT        NOT NULL,
            content_hash TEXT        NOT NULL,
            UNIQUE (day, revision)
        );

        CREATE TABLE intel.market_registry (
            id              BIGSERIAL   PRIMARY KEY,
            run_id          BIGINT      NOT NULL REFERENCES intel.runs(id),
            provider_bet_id INTEGER     NOT NULL,
            name            TEXT        NOT NULL,
            market_key      TEXT,
            status          TEXT        NOT NULL CHECK (status IN ('ACTIVE', 'RESEARCH', 'CANDIDATE', 'NOT_MODELABLE')),
            criteria        JSONB       NOT NULL,
            metrics         JSONB       NOT NULL,
            proposal        TEXT,
            version         TEXT        NOT NULL,
            built_at        TIMESTAMPTZ NOT NULL,
            UNIQUE (run_id, provider_bet_id)
        );
        COMMENT ON TABLE intel.market_registry IS
          'MARKET DISCOVERY ENGINE (discovery-v1): every pre-match market the provider offers, its ten incorporation '
          'criteria and a status. It proposes research; it never activates a market.';

        CREATE TABLE intel.audit_checks (
            id           BIGSERIAL   PRIMARY KEY,
            day          DATE        NOT NULL,
            checked_at   TIMESTAMPTZ NOT NULL,
            version      TEXT        NOT NULL,
            rule         TEXT        NOT NULL,
            n_checked    INTEGER     NOT NULL CHECK (n_checked >= 0),
            n_violations INTEGER     NOT NULL CHECK (n_violations >= 0),
            examples     JSONB       NOT NULL DEFAULT '[]'::jsonb,
            UNIQUE (day, version, rule, checked_at)
        );
        COMMENT ON TABLE intel.audit_checks IS
          'Data-leakage audit (leak-audit-v1): for each rule, how many decisions of a day were checked and how many '
          'used something not known at their known_at.';

        -- the month's budget also alerts at 50 %
        DO $do$
        DECLARE c text;
        BEGIN
            FOR c IN SELECT conname FROM pg_constraint
                      WHERE conrelid = 'ai.budget_alerts'::regclass AND contype = 'c'
                        AND pg_get_constraintdef(oid) LIKE '%threshold%'
            LOOP
                EXECUTE format('ALTER TABLE ai.budget_alerts DROP CONSTRAINT %I', c);
            END LOOP;
        END
        $do$;
        ALTER TABLE ai.budget_alerts ADD CONSTRAINT budget_alerts_threshold_check
            CHECK (threshold IN (50, 70, 85, 95, 100));
    """)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON intel.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")


def downgrade() -> None:
    op.execute("""
        DELETE FROM ai.budget_alerts WHERE threshold = 50;
        ALTER TABLE ai.budget_alerts DROP CONSTRAINT IF EXISTS budget_alerts_threshold_check;
        ALTER TABLE ai.budget_alerts ADD CONSTRAINT budget_alerts_threshold_check
            CHECK (threshold IN (70, 85, 95, 100));
        DROP SCHEMA IF EXISTS intel CASCADE;
    """)
