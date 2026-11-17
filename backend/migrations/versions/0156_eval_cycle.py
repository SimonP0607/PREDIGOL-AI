"""The evaluations E1-E4 in the shadow (IA-105..IA-108, plan pieces AD-D06, AD-D07, AD-D08, AD-D03): five append-only tables

WHY THIS EXISTS
---------------
Today a match is studied in three passes (``first``, ``pre``, ``final``) and the last one waits for the line-up only until 50 minutes
before kick-off: 0 of 1.078 final passes of 14 days had it (production, 16 Nov 2026). The official line-up was first seen 19 minutes
before kick-off at the median (IA-105's measurement, 17 Nov 2026). The evaluation cycle ``eval-cycle-v1`` (``fbi.evalcycle``) ties four
evaluations to the football clock instead - E1 (T-24 to T-12 h), E2 (each new fact), E3 (the official line-up, code only, under two
minutes), E4 (T-20 to T-10 min, with the match read again) - and needs a place for what each one did. ``decision-v1`` and the three
passes are not touched: the cycle is a shadow beside them.

WHAT CHANGES
------------
``intel.eval_runs``: one row per evaluation of a match - its step and version, why it ran (the window, a new fact, the official
line-up or its correction) and the key that makes it run once, the moment it read as of, the kick-off then, when what triggered it was
known (E3: the line-up's first sighting) and when it finished (``latency_ms``), the decision-v2 moment it decided in, the match read
again (E4) and the line-up it saw (E3).

``intel.eval_facts``: each new fact (``ai.evidence``) E2 looked at, once per match (a unique key): recalculated or only noted, and why.

``intel.lineup_dependencies`` (AD-D03): computed at E1 for each selection - which players hold it up and its probability if each does not
play (or plays the whole match), from the goal model's own score matrix and the player engine (``player-engine-v1``) with the estimated
starters (``lineup-estimate-v1``). E3 reads this table instead of deliberating.

``intel.eval_verdicts`` (AD-D07): what each evaluation made of each selection - read (E1, E2), confirmed, unchanged, unchanged with a new
figure, withdrawn, still waiting - with the state and reason of the cycle, the figure and price before and after, the line-up's effect and
the previous verdict of the same selection.

``intel.private_alerts`` (AD-D08): the owner's alerts «antes -> ahora» - a withdrawal, no line-up in time, a change of kick-off or of the
match's conditions - each once (``dedupe_key``). They are served only by contract C-05 under ``require_admin``; nothing notifies a reader.

The two tables of decision-v2's kept shadow (revision 0150) named only the triggers ``E1``, ``E4`` and ``mirror``: their CHECK on
``trigger`` is widened to ``E2`` and ``E3`` too. Every row they hold already meets the new rule; nothing else of them changes.

Every new table is append-only (``ai.refuse_change()``), as every table of the plan. Nothing that decides, publishes or serves a reader
reads them.

Downgrade: drops the five tables (the cycle's rows are lost; decision-v1, the passes and decision-v2's own rows stay) and puts the CHECK
of the two decision-v2 tables back as it was, ``NOT VALID`` (their rows are append-only: an E2 or E3 row already written stays).

Revision ID: 0156
Revises: 0155
"""

from __future__ import annotations

from alembic import op

revision = "0156"
down_revision = "0155"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
EVALUATIONS = ("E1", "E2", "E3", "E4")
TRIGGERS = ("E1", "E2", "E3", "E4", "mirror")
TRIGGERS_0150 = ("E1", "E4", "mirror")
CAUSES = ("ventana", "hecho_nuevo", "alineacion_oficial", "correccion_alineacion")
RUN_STATUSES = ("completa", "sin_candidatos", "fallida")
FACT_ACTIONS = ("recalcula", "anota")
GROUPS = ("siempre", "si_dependencia", "no_espera")
DEPENDENCY_STATUSES = ("calculada", "sin_matriz", "sin_estimacion", "no_aplica")
VERDICTS = ("lectura", "confirmada", "sigue_igual", "modificada", "retirada", "pendiente", "descartada")
STATES = ("detectado", "en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "retirada",
          "descartada", "en_juego", "liquidada", "evaluada")
PRICE_STATES = ("vigente", "antiguo", "sin_precio")
ALERT_KINDS = ("retirada", "sin_alineacion", "cambio_horario", "cambio_condiciones")
TABLES = ("eval_runs", "eval_facts", "lineup_dependencies", "eval_verdicts", "private_alerts")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in ("decision_v2_moments", "decisions_v2"):
        op.execute(f"""
            ALTER TABLE intel.{table} DROP CONSTRAINT {table}_trigger_check;
            ALTER TABLE intel.{table} ADD CONSTRAINT {table}_trigger_check CHECK (trigger IN ({_in(TRIGGERS)}));
        """)
    op.execute(rf"""
        CREATE TABLE intel.eval_runs (
            id                  BIGSERIAL    PRIMARY KEY,
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            evaluation_version  INTEGER      NOT NULL CHECK (evaluation_version >= 1),
            cause               TEXT         NOT NULL CHECK (cause IN ({_in(CAUSES)})),
            cause_key           TEXT         NOT NULL CHECK (length(cause_key) BETWEEN 3 AND 200),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            trigger_at          TIMESTAMPTZ,
            finished_at         TIMESTAMPTZ  NOT NULL,
            latency_ms          INTEGER      CHECK (latency_ms IS NULL OR latency_ms >= 0),
            status              TEXT         NOT NULL CHECK (status IN ({_in(RUN_STATUSES)})),
            decided             BOOLEAN      NOT NULL,
            decision_moment_id  BIGINT       REFERENCES intel.decision_v2_moments(id),
            conditions          JSONB,
            lineup              JSONB,
            summary             JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            error               TEXT         CHECK (error IS NULL OR error ~ '^[A-Za-z][A-Za-z0-9_]{{0,80}}$'),
            version             TEXT         NOT NULL CHECK (version ~ '^eval-cycle-v[0-9]+$'),
            code_version        TEXT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT eval_runs_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT eval_runs_trigger_known CHECK (trigger_at IS NULL OR trigger_at <= finished_at),
            CONSTRAINT eval_runs_cause CHECK (
                (evaluation IN ('E1', 'E4') AND cause = 'ventana') OR (evaluation = 'E2' AND cause = 'hecho_nuevo')
                OR (evaluation = 'E3' AND cause IN ('alineacion_oficial', 'correccion_alineacion'))),
            CONSTRAINT eval_runs_e3_line_up CHECK (evaluation <> 'E3' OR (lineup IS NOT NULL AND trigger_at IS NOT NULL)),
            CONSTRAINT eval_runs_e4_reread CHECK (evaluation <> 'E4' OR status = 'fallida' OR conditions IS NOT NULL),
            CONSTRAINT eval_runs_failed CHECK ((status = 'fallida') = (error IS NOT NULL))
        );
        CREATE UNIQUE INDEX eval_runs_once ON intel.eval_runs (fixture_id, evaluation, cause_key) WHERE status <> 'fallida';
        CREATE INDEX eval_runs_fixture ON intel.eval_runs (fixture_id, evaluation, id DESC);
        CREATE INDEX eval_runs_kickoff ON intel.eval_runs (kickoff_at);
        COMMENT ON TABLE intel.eval_runs IS
          'IA-105 (AD-D06): each evaluation E1-E4 of a tracked match by eval-cycle-v1, with why it ran (once per cause_key), the moment '
          'it read as of, its latency from what triggered it and the decision-v2 moment it decided in. Shadow only (FBI_EVAL_CYCLE); '
          'append-only; the passes first/pre/final are not touched.';

        CREATE TABLE intel.eval_facts (
            id                  BIGSERIAL    PRIMARY KEY,
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            evidence_id         BIGINT       NOT NULL,
            run_id              BIGINT       NOT NULL REFERENCES intel.eval_runs(id),
            action              TEXT         NOT NULL CHECK (action IN ({_in(FACT_ACTIONS)})),
            reason              TEXT         NOT NULL CHECK (reason ~ '^[a-z][a-z0-9_]{{1,60}}$'),
            retrieved_at        TIMESTAMPTZ  NOT NULL,
            known_at            TIMESTAMPTZ  NOT NULL,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT eval_facts_known CHECK (retrieved_at <= known_at),
            CONSTRAINT eval_facts_once UNIQUE (fixture_id, evidence_id)
        );
        COMMENT ON TABLE intel.eval_facts IS
          'IA-105 (AD-D06): every new fact of a match that E2 looked at, once (a fact never triggers two E2): recalculated when it '
          'touches a variable of the model or a declared dependency, otherwise only noted. Append-only.';

        CREATE TABLE intel.lineup_dependencies (
            id                  BIGSERIAL    PRIMARY KEY,
            run_id              BIGINT       NOT NULL REFERENCES intel.eval_runs(id),
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            decision_id         BIGINT       REFERENCES intel.decisions_v2(id),
            market_key          TEXT         NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection           TEXT         NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line                NUMERIC(6,2) NOT NULL,
            market_group        TEXT         NOT NULL CHECK (market_group IN ({_in(GROUPS)})),
            status              TEXT         NOT NULL CHECK (status IN ({_in(DEPENDENCY_STATUSES)})),
            waits               BOOLEAN      NOT NULL,
            p_base              NUMERIC(7,6) CHECK (p_base IS NULL OR (p_base >= 0 AND p_base <= 1)),
            p_matrix            NUMERIC(7,6) CHECK (p_matrix IS NULL OR (p_matrix >= 0 AND p_matrix <= 1)),
            matrix              JSONB,
            players             JSONB        NOT NULL DEFAULT '[]'::jsonb,
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            version             TEXT         NOT NULL CHECK (version ~ '^lineup-dep-v[0-9]+$'),
            model               TEXT         NOT NULL CHECK (model ~ '^player-engine-v[0-9]+$'),
            estimate_version    TEXT         NOT NULL CHECK (estimate_version ~ '^lineup-estimate-v[0-9]+$'),
            input_hash          TEXT         NOT NULL CHECK (input_hash ~ '{SHA256}'),
            code_version        TEXT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT lineup_dependencies_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT lineup_dependencies_always_waits CHECK (market_group <> 'siempre' OR waits),
            CONSTRAINT lineup_dependencies_never_waits CHECK (market_group <> 'no_espera' OR NOT waits),
            CONSTRAINT lineup_dependencies_once UNIQUE (run_id, market_key, selection, line)
        );
        CREATE INDEX lineup_dependencies_fixture ON intel.lineup_dependencies (fixture_id, market_key, selection, line, id DESC);
        COMMENT ON TABLE intel.lineup_dependencies IS
          'IA-108 (AD-D03): at E1, the players each selection depends on and its probability without each of them (and with each '
          'playing the whole match), from the goal model''s score matrix and player-engine-v1 with lineup-estimate-v1. No model of '
          'language computes any figure. E3 reads it. Shadow only; append-only.';

        CREATE TABLE intel.eval_verdicts (
            id                  BIGSERIAL    PRIMARY KEY,
            run_id              BIGINT       NOT NULL REFERENCES intel.eval_runs(id),
            previous_id         BIGINT       REFERENCES intel.eval_verdicts(id),
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            market_key          TEXT         NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection           TEXT         NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line                NUMERIC(6,2) NOT NULL,
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            evaluation_version  INTEGER      NOT NULL CHECK (evaluation_version >= 1),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            verdict             TEXT         NOT NULL CHECK (verdict IN ({_in(VERDICTS)})),
            state               TEXT         NOT NULL CHECK (state IN ({_in(STATES)})),
            reason              TEXT         NOT NULL CHECK (reason ~ '^[a-z][a-z0-9_]{{1,60}}$'),
            cause               TEXT         NOT NULL CHECK (cause ~ '^[a-z][a-z0-9_]{{1,60}}$'),
            decision_id         BIGINT       REFERENCES intel.decisions_v2(id),
            dependency_id       BIGINT       REFERENCES intel.lineup_dependencies(id),
            p_before            NUMERIC(7,6) CHECK (p_before IS NULL OR (p_before >= 0 AND p_before <= 1)),
            p_after             NUMERIC(7,6) CHECK (p_after IS NULL OR (p_after >= 0 AND p_after <= 1)),
            odds_before         NUMERIC(10,4),
            odds_after          NUMERIC(10,4),
            price_state         TEXT         CHECK (price_state IS NULL OR price_state IN ({_in(PRICE_STATES)})),
            ev_after            NUMERIC(10,6),
            edge_after          NUMERIC(10,6),
            lineup              JSONB,
            detail              JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            version             TEXT         NOT NULL CHECK (version ~ '^eval-verdict-v[0-9]+$'),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT eval_verdicts_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT eval_verdicts_reading CHECK ((verdict = 'lectura') = (evaluation IN ('E1', 'E2'))),
            CONSTRAINT eval_verdicts_previous CHECK (previous_id IS NULL OR previous_id < id),
            CONSTRAINT eval_verdicts_withdrawn CHECK (verdict <> 'retirada' OR state = 'retirada'),
            CONSTRAINT eval_verdicts_confirmed CHECK (verdict <> 'confirmada' OR state = 'confirmada_sombra'),
            CONSTRAINT eval_verdicts_once UNIQUE (run_id, market_key, selection, line)
        );
        CREATE INDEX eval_verdicts_selection ON intel.eval_verdicts (fixture_id, market_key, selection, line, id DESC);
        COMMENT ON TABLE intel.eval_verdicts IS
          'IA-106 (AD-D07): what each evaluation made of each selection (read, confirmed, unchanged, unchanged with a new figure, '
          'withdrawn, still waiting), with the cycle''s state and reason, the figure and the price before and after and the line-up''s '
          'effect. Decided by code only. Shadow only; append-only.';

        CREATE TABLE intel.private_alerts (
            id                  BIGSERIAL    PRIMARY KEY,
            dedupe_key          TEXT         NOT NULL UNIQUE CHECK (length(dedupe_key) BETWEEN 5 AND 300),
            kind                TEXT         NOT NULL CHECK (kind IN ({_in(ALERT_KINDS)})),
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            market_key          TEXT,
            selection           TEXT,
            line                NUMERIC(6,2),
            cause               TEXT         NOT NULL CHECK (cause ~ '^[a-z][a-z0-9_]{{1,60}}$'),
            before              JSONB        NOT NULL,
            after               JSONB        NOT NULL,
            price               JSONB,
            run_id              BIGINT       NOT NULL REFERENCES intel.eval_runs(id),
            verdict_id          BIGINT       REFERENCES intel.eval_verdicts(id),
            decision_id         BIGINT       REFERENCES intel.decisions_v2(id),
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            evaluation_version  INTEGER      NOT NULL CHECK (evaluation_version >= 1),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            version             TEXT         NOT NULL CHECK (version ~ '^alerts-v[0-9]+$'),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT private_alerts_selection CHECK (
                (market_key IS NULL) = (selection IS NULL) AND (market_key IS NULL) = (line IS NULL)),
            CONSTRAINT private_alerts_selection_kinds CHECK (kind NOT IN ('retirada', 'sin_alineacion') OR market_key IS NOT NULL),
            CONSTRAINT private_alerts_changed CHECK (before <> after)
        );
        CREATE INDEX private_alerts_recent ON intel.private_alerts (created_at DESC, id DESC);
        CREATE INDEX private_alerts_fixture ON intel.private_alerts (fixture_id, id DESC);
        COMMENT ON TABLE intel.private_alerts IS
          'IA-107 (AD-D08): the owner''s private alerts «antes -> ahora» of the evaluation cycle (a withdrawal, no line-up in time, a '
          'change of kick-off or conditions), each once. Served only by contract C-05 under require_admin; never a notice to a reader; '
          'no health detail (an absence is a state, a source and a date). Append-only.';
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON intel.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS intel.{table}")
    for table in ("decision_v2_moments", "decisions_v2"):
        op.execute(f"""
            ALTER TABLE intel.{table} DROP CONSTRAINT {table}_trigger_check;
            ALTER TABLE intel.{table} ADD CONSTRAINT {table}_trigger_check CHECK (trigger IN ({_in(TRIGGERS_0150)})) NOT VALID;
        """)
