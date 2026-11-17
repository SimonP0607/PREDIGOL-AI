"""The tracking of loose selections and the ``parlay-v6`` builder (IA-109 / IA-110, plan pieces AD-E05 and AD-E06): three append-only tables

WHY THIS EXISTS
---------------
A selection decision-v2's kept shadow confirms (IA-093) reaches ``en_juego`` in the cycle of states (IA-068) at kick-off, and nothing settled
it: no layer of decision-v2 has a settlement of its own. And ``picks.parlays`` (revision 0053) is unique on ``(kind, day, source)``: a parlay
of a new rule cannot be kept the same day as ``parlay-v5``'s without touching that key or its rows. Both are new tables here; nothing that
exists is changed.

WHAT CHANGES
------------
- ``intel.selection_settlements``: one row per settlement of a chain of the cycle on ``settle-v4`` - the first (``primera``), a correction
  of the provider's result (``correccion``, naming the row it supersedes) or the firm evaluation once no correction is expected (``firme``:
  the result stands, the price taken, the last de-vigged price before kick-off and the value against it). A row has one successor at most
  (``supersedes_id``), the first has none: a trail, never a rewrite.
- ``intel.parlays_v6``: one row per (writer of the chains, rule, kind, product day) - the parlay built, or ``none`` (no parlay that day, with
  why). A built one carries its legs' combined odds, the joint probability by simulation (with its Monte Carlo error and its pessimistic
  end), the product of the legs, the market's joint, the fair odds, the accumulated margin, the expected value and growth, and the
  dependence it used. Decision 6 of the owner (16-nov-2026) in the schema: 2 to ``max_legs`` legs, ``max_legs`` at most 3.
- ``intel.parlay_v6_legs``: the legs, each a chain of the cycle confirmed in the shadow (the row that confirmed it), with its price, books
  and probabilities.

All three append-only (``intel.refuse_change()``, revision 0076; the static test of IA-059). ``picks.parlays`` and its 0053 key, ``parlay-v5``
and its records, ``settle-v4`` and ``picks.pick_results`` are not touched. Nothing reads these tables but their passes (``FBI_SELECTION_SETTLE``
and ``FBI_PARLAY_V6``, both ``off`` by default) and the owner's private readings.

Downgrade: drops the three tables (their rows go with them; the chains of the cycle keep the moves the tracking appended).

Revision ID: 0157
Revises: 0156
"""

from __future__ import annotations

from alembic import op

revision = "0157"
down_revision = "0156"
branch_labels = None
depends_on = None

RESULTS = ("win", "loss", "push", "void", "half_win", "half_loss")
BASES = ("regulation_90", "not_played", "no_result_72h")
KINDS = ("primera", "correccion", "firme")
PARLAY_KINDS = ("daily", "multiday")
NONE_REASONS = ("sin_candidatos", "un_solo_candidato", "ninguna_combinacion_cumple")
WRITER = "^[a-z][a-z0-9.-]{2,40}$"


def _in(words: tuple[str, ...]) -> str:
    return ", ".join("'" + w + "'" for w in words)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.selection_settlements (
            id                  BIGSERIAL     PRIMARY KEY,
            chain_key           TEXT          NOT NULL CHECK (length(chain_key) BETWEEN 10 AND 300),
            writer              TEXT          NOT NULL CHECK (writer ~ '{WRITER}'),
            fixture_id          BIGINT        NOT NULL REFERENCES core.fixtures(id),
            market_key          TEXT          NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection           TEXT          NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line                NUMERIC(6,2)  NOT NULL DEFAULT 0,
            kind                TEXT          NOT NULL CHECK (kind IN ({_in(KINDS)})),
            supersedes_id       BIGINT        REFERENCES intel.selection_settlements(id),
            result              TEXT          NOT NULL CHECK (result IN ({_in(RESULTS)})),
            profit_units        NUMERIC(12,4),
            basis               TEXT          CHECK (basis IS NULL OR basis IN ({_in(BASES)})),
            review_reason       TEXT,
            rule_version        TEXT          NOT NULL CHECK (rule_version ~ '^settle-v[0-9]+$'),
            status_short        TEXT,
            reg_goals_home      INTEGER,
            reg_goals_away      INTEGER,
            taken_kickoff       TIMESTAMPTZ,
            result_payload_hash TEXT,
            odds_taken          NUMERIC(10,4) CHECK (odds_taken IS NULL OR odds_taken > 1),
            price_source        TEXT          CHECK (price_source IS NULL OR price_source ~ '^[a-z_]+\.[a-z0-9_]+$'),
            price_source_id     BIGINT,
            close_p_fair        NUMERIC(7,6)  CHECK (close_p_fair IS NULL OR (close_p_fair >= 0 AND close_p_fair <= 1)),
            close_odds          NUMERIC(10,4),
            close_at            TIMESTAMPTZ,
            line_value          NUMERIC(10,6),
            known_at            TIMESTAMPTZ   NOT NULL,
            recorded_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            tracker_version     TEXT          NOT NULL CHECK (tracker_version ~ '^selection-settle-v[0-9]+$'),
            CONSTRAINT selection_settlements_chain_key CHECK (
                chain_key = writer || '|' || fixture_id::text || '|' || market_key || '|' || selection || '|' || line::text),
            CONSTRAINT selection_settlements_first CHECK ((kind = 'primera') = (supersedes_id IS NULL)),
            CONSTRAINT selection_settlements_firm_only CHECK (
                kind = 'firme' OR (close_p_fair IS NULL AND close_odds IS NULL AND close_at IS NULL AND line_value IS NULL)),
            CONSTRAINT selection_settlements_earlier CHECK (supersedes_id IS NULL OR supersedes_id < id)
        );
        CREATE UNIQUE INDEX intel_selection_settlements_one_successor
            ON intel.selection_settlements (chain_key, COALESCE(supersedes_id, 0));
        CREATE INDEX intel_selection_settlements_fixture ON intel.selection_settlements (fixture_id);
        CREATE INDEX intel_selection_settlements_known ON intel.selection_settlements (known_at);
        COMMENT ON TABLE intel.selection_settlements IS
          'IA-109 (AD-E05): the settlements of the chains of the cycle of states on settle-v4 - the first, a correction of the provider''s '
          'result (naming the row it supersedes) or the firm evaluation with the value against the last price before kick-off. One '
          'successor per row. picks.pick_results is not touched. Append-only.';

        CREATE TABLE intel.parlays_v6 (
            id                  BIGSERIAL     PRIMARY KEY,
            writer              TEXT          NOT NULL CHECK (writer ~ '{WRITER}'),
            rule_version        TEXT          NOT NULL CHECK (rule_version ~ '^parlay-v6(\.[0-9]+)?$'),
            kind                TEXT          NOT NULL CHECK (kind IN ({_in(PARLAY_KINDS)})),
            day                 DATE          NOT NULL,
            outcome             TEXT          NOT NULL CHECK (outcome IN ('built', 'none')),
            none_reason         TEXT          CHECK (none_reason IS NULL OR none_reason IN ({_in(NONE_REASONS)})),
            max_legs            INTEGER       NOT NULL CHECK (max_legs BETWEEN 2 AND 3),
            n_legs              INTEGER       NOT NULL CHECK (n_legs = 0 OR n_legs BETWEEN 2 AND 3),
            n_candidates        INTEGER       NOT NULL CHECK (n_candidates >= 0),
            window_from         TIMESTAMPTZ   NOT NULL,
            window_to           TIMESTAMPTZ   NOT NULL CHECK (window_to > window_from),
            combined_odds       NUMERIC(12,4),
            p_joint             NUMERIC(9,8)  CHECK (p_joint IS NULL OR (p_joint >= 0 AND p_joint <= 1)),
            p_joint_se          NUMERIC(9,8),
            p_joint_low         NUMERIC(9,8)  CHECK (p_joint_low IS NULL OR (p_joint_low >= 0 AND p_joint_low <= 1)),
            p_product           NUMERIC(9,8),
            p_market_joint      NUMERIC(9,8),
            fair_odds           NUMERIC(14,4),
            accumulated_margin  NUMERIC(9,6),
            expected_value      NUMERIC(12,6),
            expected_value_low  NUMERIC(12,6),
            expected_log_growth NUMERIC(14,10),
            simulations         INTEGER       CHECK (simulations IS NULL OR simulations >= 1000),
            seed                BIGINT,
            dependence          JSONB         NOT NULL DEFAULT '[]'::jsonb,
            inputs              JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            known_at            TIMESTAMPTZ   NOT NULL,
            recorded_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            code_version        TEXT,
            CONSTRAINT parlays_v6_once UNIQUE (writer, rule_version, kind, day),
            CONSTRAINT parlays_v6_legs_fit CHECK (n_legs <= max_legs),
            CONSTRAINT parlays_v6_outcome CHECK (
                (outcome = 'built' AND n_legs >= 2 AND none_reason IS NULL AND combined_odds > 1 AND p_joint IS NOT NULL
                 AND p_joint_low IS NOT NULL AND p_joint_low <= p_joint)
                OR (outcome = 'none' AND n_legs = 0 AND none_reason IS NOT NULL AND combined_odds IS NULL AND p_joint IS NULL))
        );
        CREATE INDEX intel_parlays_v6_day ON intel.parlays_v6 (day, kind);
        COMMENT ON TABLE intel.parlays_v6 IS
          'IA-110 (AD-E06): parlay-v6 in the shadow - one row per writer, rule, kind and product day: the parlay built (2 to 3 legs, each '
          'confirmed in the shadow by itself; joint probability by simulation; margin accumulated) or none, with why. picks.parlays and '
          'parlay-v5 are not touched. Append-only.';

        CREATE TABLE intel.parlay_v6_legs (
            id                  BIGSERIAL     PRIMARY KEY,
            parlay_id           BIGINT        NOT NULL REFERENCES intel.parlays_v6(id),
            leg_no              INTEGER       NOT NULL CHECK (leg_no BETWEEN 1 AND 3),
            chain_key           TEXT          NOT NULL CHECK (length(chain_key) BETWEEN 10 AND 300),
            confirmed_id        BIGINT        NOT NULL,
            confirmed_at        TIMESTAMPTZ   NOT NULL,
            fixture_id          BIGINT        NOT NULL REFERENCES core.fixtures(id),
            kickoff_at          TIMESTAMPTZ   NOT NULL,
            market_key          TEXT          NOT NULL,
            selection           TEXT          NOT NULL,
            line                NUMERIC(6,2)  NOT NULL DEFAULT 0,
            odds                NUMERIC(10,4) NOT NULL CHECK (odds > 1),
            n_bookmakers        INTEGER       NOT NULL CHECK (n_bookmakers >= 3),
            p_model             NUMERIC(7,6)  NOT NULL CHECK (p_model > 0 AND p_model < 1),
            p_low               NUMERIC(7,6)  NOT NULL CHECK (p_low > 0 AND p_low <= p_model),
            p_market            NUMERIC(7,6),
            price_at            TIMESTAMPTZ,
            source              TEXT          NOT NULL CHECK (source ~ '^[a-z_]+\.[a-z0-9_]+$'),
            source_id           BIGINT        NOT NULL,
            inputs              JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            CONSTRAINT parlay_v6_legs_no UNIQUE (parlay_id, leg_no),
            CONSTRAINT parlay_v6_legs_once UNIQUE (parlay_id, chain_key),
            CONSTRAINT parlay_v6_legs_confirmed_before CHECK (confirmed_at < kickoff_at)
        );
        COMMENT ON TABLE intel.parlay_v6_legs IS
          'IA-110 (AD-E06): the legs of parlay-v6, each a chain of the cycle confirmed in the shadow (confirmed_id: the row of '
          'intel.selection_lifecycle that confirmed it). Append-only.';
    """)
    for table in ("selection_settlements", "parlays_v6", "parlay_v6_legs"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON intel.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.parlay_v6_legs")
    op.execute("DROP TABLE IF EXISTS intel.parlays_v6")
    op.execute("DROP TABLE IF EXISTS intel.selection_settlements")
