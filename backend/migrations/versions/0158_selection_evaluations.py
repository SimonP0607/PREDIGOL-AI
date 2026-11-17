"""The one evaluation after the match of every selection (IA-112, plan piece AD-K01): ``intel.selection_evaluations``, append-only

WHY THIS EXISTS
---------------
After a match, a selection is judged today in five places that do not share a row: the post-mortem by decision (pm-v6), the families'
post-mortem (pm-fam-v1), the review of the match as a whole, the daily review and the review of the chronicle. None of them answers the same questions of
every selection in the shadow, and none can be read back by the validation board (AD-K02) or the private screens (C-03, C-08).

WHAT CHANGES
------------
``intel.selection_evaluations``: one row per selection, layer and version of the evaluation (``eval-sel-v1``), written by code after the
settlement - what was anticipated against what happened (the probability judged, its seal, the market's at the same moment, the result of
``settle-v4``, log loss and Brier of both), the value against the close (odds taken, the closing fair probability, ``clv-v1``, the quality
of the price and the verdict quality x result), how many of the facts the decision cited were held, contradicted or could not be judged, whether the layer would take it (``taken``:
confirmed in the shadow by ``lifecycle-map-v1`` - the population the validation board judges),
whether the official line-up changed the decision, and how it agrees with ``intel.decision_outcomes`` (``parity``). Every detail is in
``detail``; the columns are what the board and the screens filter and count by.

Append-only (``ai.refuse_change()``, as every table of the plan: the static test of IA-059). One row per selection and version: a
selection evaluated twice gives the same row, and the second is not written (``selection_evaluations_once``). Nothing that decides,
publishes or serves a reader reads it; the five writers above keep writing as they did (their retirement is AD-K06).

Downgrade: drops the table (the evaluations are lost; every other table stays as it is).

Revision ID: 0158
Revises: 0157
"""

from __future__ import annotations

from alembic import op

revision = "0158"
down_revision = "0157"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
RESULTS = ("win", "loss", "push", "void", "half_win", "half_loss")
SEALS = ("calibrada", "sin_calibrar")
QUALITIES = ("GOOD", "NEUTRAL", "BAD", "UNKNOWN")
VERDICTS = ("MERECIDO", "SUERTE", "VARIANZA", "ERROR", "NULO", "SIN_DATOS")
FAMILIES = ("core", "corners", "cards", "goals_halves")
SOURCES = ("intel.decisions", "intel.decisions_v2")
PARITY = ("igual", "difiere", "sin_referencia")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.selection_evaluations (
            id                    BIGSERIAL     PRIMARY KEY,
            version               TEXT          NOT NULL CHECK (version ~ '^eval-sel-v[0-9]+$'),
            layer                 TEXT          NOT NULL CHECK (layer ~ '^decision-[a-z0-9.-]{{1,30}}$'),
            decision_source       TEXT          NOT NULL CHECK (decision_source IN ({_in(SOURCES)})),
            decision_id           BIGINT        NOT NULL,
            fixture_id            BIGINT        NOT NULL REFERENCES core.fixtures(id),
            family                TEXT          NOT NULL CHECK (family IN ({_in(FAMILIES)})),
            taken                 BOOLEAN       NOT NULL,
            market_key            TEXT          NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection             TEXT          NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line                  NUMERIC(6,2)  NOT NULL,
            kickoff_at            TIMESTAMPTZ   NOT NULL,
            decided_at            TIMESTAMPTZ   NOT NULL,
            settled_at            TIMESTAMPTZ   NOT NULL,
            result                TEXT          NOT NULL CHECK (result IN ({_in(RESULTS)})),
            p_judged              NUMERIC(8,6)  NOT NULL CHECK (p_judged > 0 AND p_judged < 1),
            seal                  TEXT          NOT NULL CHECK (seal IN ({_in(SEALS)})),
            p_market              NUMERIC(8,6)  CHECK (p_market IS NULL OR (p_market > 0 AND p_market < 1)),
            odds                  NUMERIC(9,3)  CHECK (odds IS NULL OR odds > 1),
            p_close               NUMERIC(8,6)  CHECK (p_close IS NULL OR (p_close > 0 AND p_close < 1)),
            clv                   NUMERIC(10,6),
            hit                   SMALLINT      CHECK (hit IS NULL OR hit IN (0, 1)),
            log_loss              NUMERIC(10,6) CHECK (log_loss IS NULL OR log_loss >= 0),
            brier                 NUMERIC(8,6)  CHECK (brier IS NULL OR (brier >= 0 AND brier <= 1)),
            market_log_loss       NUMERIC(10,6) CHECK (market_log_loss IS NULL OR market_log_loss >= 0),
            market_brier          NUMERIC(8,6)  CHECK (market_brier IS NULL OR (market_brier >= 0 AND market_brier <= 1)),
            price_quality         TEXT          NOT NULL CHECK (price_quality IN ({_in(QUALITIES)})),
            verdict               TEXT          NOT NULL CHECK (verdict IN ({_in(VERDICTS)})),
            evidence_held         INTEGER       NOT NULL CHECK (evidence_held >= 0),
            evidence_contradicted INTEGER       NOT NULL CHECK (evidence_contradicted >= 0),
            evidence_unevaluable  INTEGER       NOT NULL CHECK (evidence_unevaluable >= 0),
            lineup_changed        BOOLEAN,
            parity                TEXT          NOT NULL CHECK (parity IN ({_in(PARITY)})),
            detail                JSONB         NOT NULL,
            input_hash            TEXT          NOT NULL CHECK (input_hash ~ '{SHA256}'),
            code_version          TEXT,
            created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT selection_evaluations_before_kickoff CHECK (decided_at < kickoff_at),
            CONSTRAINT selection_evaluations_after_kickoff CHECK (settled_at >= kickoff_at),
            CONSTRAINT selection_evaluations_scored CHECK ((hit IS NULL) = (log_loss IS NULL) AND (hit IS NULL) = (brier IS NULL)),
            CONSTRAINT selection_evaluations_hit_is_a_full_result CHECK (
                hit IS NULL OR (hit = 1 AND result = 'win') OR (hit = 0 AND result = 'loss')),
            CONSTRAINT selection_evaluations_market_scored CHECK (
                (market_log_loss IS NULL) = (market_brier IS NULL) AND (market_log_loss IS NULL OR hit IS NOT NULL)),
            CONSTRAINT selection_evaluations_clv CHECK ((clv IS NULL) = (p_close IS NULL OR odds IS NULL)),
            CONSTRAINT selection_evaluations_verdict CHECK (
                (verdict = 'NULO') = (result IN ('push', 'void'))
                AND (verdict <> 'SIN_DATOS' OR price_quality = 'UNKNOWN')),
            CONSTRAINT selection_evaluations_once UNIQUE (version, layer, fixture_id, market_key, selection, line),
            CONSTRAINT selection_evaluations_one_per_decision UNIQUE (version, decision_source, decision_id)
        );
        CREATE INDEX selection_evaluations_fixture ON intel.selection_evaluations (fixture_id);
        CREATE INDEX selection_evaluations_board ON intel.selection_evaluations (version, layer, family, market_key, kickoff_at);
        CREATE INDEX selection_evaluations_kickoff ON intel.selection_evaluations (kickoff_at);
        COMMENT ON TABLE intel.selection_evaluations IS
          'IA-112 (AD-K01): the one evaluation after the match of every settled selection in the shadow (eval-sel-v1): anticipated '
          'against happened, value against the close, the facts cited held or contradicted, the effect of the line-up and the '
          'parity with intel.decision_outcomes. Written by code (FBI_SELECTION_EVAL=shadow); append-only; nothing that decides, '
          'publishes or serves a reader reads it.';
    """)
    op.execute("CREATE TRIGGER selection_evaluations_append_only BEFORE UPDATE OR DELETE ON intel.selection_evaluations "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.selection_evaluations")
