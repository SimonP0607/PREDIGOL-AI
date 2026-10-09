"""A pre-match pick is a record that cannot change, and how fast each match was settled is measured

PRE-MATCH RECORDS CANNOT CHANGE. What was decided before kick-off - the selection, the price taken
and when, the bookmaker, the probabilities, the fair price, the edge and the expected value, the
model, the calibrator, the rule and the code that produced it - is frozen by a trigger on:

* ``picks.picks``            only ``status``, ``status_changed_at``, ``qualification``, ``published_at``
                             and ``mode`` may change (and ``picks_publishing_disabled`` still holds the
                             last two); a settled pick's result lives in ``picks.pick_results``;
* ``picks.pick_candidates``  nothing may change: every evaluation is a fact;
* ``picks.daily_set_items``  and ``picks.parlay_legs``: only the result (``status``, ``profit_units``,
                             ``settled_at``) - the rank, the price frozen at selection and its time stay.

No code path updates those columns today (checked 9 Oct 2026); the trigger makes it impossible for
any future one, a script or a hand at a psql prompt to rewrite a historical price. Deleting is not
blocked: a downgrade, a test or an owner's audited cleanup must still be able to remove rows.

SETTLEMENT LATENCY. ``picks.settlement_latency`` - one row per match and settling pass - records
how long a match's bets waited after it ended:

* ``last_in_play_at``       the last state we saw in play: the provider had not finished it yet;
* ``observed_finished_at``  the first state we saw it ended (or, for a match never followed live,
                            when its result row was first written);
* ``result_stored_at``      when its result row was first written;
* ``settled_at``            the wall clock of the settlement write;
* ``delay_seconds``         ``settled_at - observed_finished_at``.

The provider publishes no instant at which it declared a match over: it lies between
``last_in_play_at`` and ``observed_finished_at``, and nothing narrower is claimed.
``path`` says who settled it: the live follow the minute it ended, the results repair, or the
pick pipeline's pass (the safety net).

``picks.v_pick_record`` puts one pick's whole record on one row: what was decided before kick-off,
the AI's last pre-match review, the result and the line value against the last pre-match price
(named ``near_close_*`` / ``line_value``, never "closing" or "CLV": that price has not been shown
to BE the closing line - see revision 0007).

Revision ID: 0074
Revises: 0073
"""

from __future__ import annotations

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

PICK_FROZEN = (
    "id", "candidate_id", "fixture_id", "market_key", "selection", "line", "model_version_id", "calibrator_id",
    "feature_set_hash", "data_cutoff_ts", "decision_rule_version", "code_version", "bookmaker_id", "market_odds",
    "odds_captured_at", "p_model", "p_calibrated", "p_calibrated_lo", "p_calibrated_hi", "p_market_fair",
    "fair_odds", "edge", "price_edge", "ev", "ev_adjusted", "kelly_fraction", "stake_units", "selection_reason",
    "created_at", "prediction_id", "odds_payload_hash", "consensus_method", "consensus_as_of", "stake_policy", "p_push",
)
ITEM_FROZEN = (
    "set_id", "rank", "pick_id", "fixture_id", "market_key", "selection", "line", "stage", "selected_at", "odds",
    "bookmaker_id", "price_at", "p_model", "p_low", "p_push", "p_market", "ev", "model_version_id", "inputs",
)
LEG_FROZEN = (
    "parlay_id", "leg_no", "pick_id", "fixture_id", "market_key", "selection", "line", "added_at", "odds",
    "bookmaker_id", "price_at", "p_model", "p_low", "p_push", "p_market", "ev", "inputs",
)


def _frozen(table: str, columns: tuple[str, ...], what: str, key: str) -> str:
    name = table.replace(".", "_") + "_frozen"
    old = ", ".join(f"OLD.{c}" for c in columns)
    new = ", ".join(f"NEW.{c}" for c in columns)
    return f"""
        CREATE FUNCTION picks.{name}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW({new}) IS DISTINCT FROM ROW({old}) THEN
                RAISE EXCEPTION '{what} is a pre-match record and cannot change (%)', {key}
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER {name} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION picks.{name}();
    """


def upgrade() -> None:
    op.execute(_frozen("picks.picks", PICK_FROZEN, "a pick", "OLD.id"))
    op.execute(_frozen("picks.daily_set_items", ITEM_FROZEN, "a pick of the day",
                       "OLD.set_id || '/' || OLD.rank"))
    op.execute(_frozen("picks.parlay_legs", LEG_FROZEN, "a parlay leg", "OLD.parlay_id || '/' || OLD.leg_no"))
    op.execute("""
        CREATE FUNCTION picks.pick_candidates_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'an evaluated candidate is a fact and cannot change (id %)', OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
        END $$;
        CREATE TRIGGER pick_candidates_frozen BEFORE UPDATE ON picks.pick_candidates
            FOR EACH ROW EXECUTE FUNCTION picks.pick_candidates_frozen();
    """)
    op.execute("""
        CREATE TABLE picks.settlement_latency (
            id                   BIGSERIAL   PRIMARY KEY,
            fixture_id           BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            status_short         TEXT        NOT NULL,
            kickoff_at           TIMESTAMPTZ NOT NULL,
            last_in_play_at      TIMESTAMPTZ,
            observed_finished_at TIMESTAMPTZ,
            result_stored_at     TIMESTAMPTZ,
            settled_at           TIMESTAMPTZ NOT NULL,
            delay_seconds        INTEGER     CHECK (delay_seconds >= 0),
            path                 TEXT        NOT NULL CHECK (path IN ('live_follow', 'results_repair', 'pipeline')),
            picks_settled        INTEGER     NOT NULL DEFAULT 0 CHECK (picks_settled >= 0),
            items_settled        INTEGER     NOT NULL DEFAULT 0 CHECK (items_settled >= 0),
            CHECK (picks_settled + items_settled > 0)
        );
        CREATE INDEX settlement_latency_settled ON picks.settlement_latency (settled_at DESC);
        CREATE INDEX settlement_latency_fixture ON picks.settlement_latency (fixture_id);
        COMMENT ON TABLE picks.settlement_latency IS
          'How long a match''s bets waited after it ended, per settling pass. The provider gives no instant at which
           it declared the match over: it lies between last_in_play_at and observed_finished_at.';
        COMMENT ON COLUMN picks.settlement_latency.items_settled IS
          'Picks of the day, parlay legs, users'' picks and users'' parlay legs settled in the same pass.';
    """)
    op.execute("""
        CREATE VIEW picks.v_pick_record AS
        SELECT p.id AS pick_id, p.fixture_id, f.kickoff_at, p.market_key, p.selection, p.line,
               p.created_at, p.odds_captured_at AS price_taken_at, p.market_odds AS odds_taken, p.bookmaker_id,
               b.name AS bookmaker, p.p_calibrated AS p_model, p.p_market_fair AS p_market, p.fair_odds, p.edge,
               p.ev, p.model_version_id, m.name AS model, v.version AS model_version, p.calibrator_id,
               p.decision_rule_version, p.code_version, p.data_cutoff_ts, p.status,
               (SELECT e.from_status FROM picks.pick_events e
                 WHERE e.pick_id = p.id AND e.to_status = 'settled' ORDER BY e.at LIMIT 1) AS status_before_settlement,
               rv.decision AS ai_decision, rv.reviewed_at AS ai_reviewed_at, rv.engine_version AS ai_engine,
               rv.evidence_ids AS ai_evidence_ids,
               pr.result_status, pr.profit_units, pr.settled_at, pr.rule_version AS settlement_rule,
               pr.review_reason,
               lv.near_close_odds, lv.near_close_captured_at, lv.lv_raw AS line_value,
               lv.lv_devigged AS line_value_devigged, lv.is_validated_close
          FROM picks.picks p
          JOIN core.fixtures f ON f.id = p.fixture_id
          JOIN models.model_versions v ON v.id = p.model_version_id
          JOIN models.model_registry m ON m.id = v.model_id
          LEFT JOIN market.bookmakers b ON b.id = p.bookmaker_id
          LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
          LEFT JOIN picks.pick_line_value lv ON lv.pick_id = p.id
          LEFT JOIN LATERAL (
              SELECT r.decision, r.reviewed_at, r.engine_version, r.evidence_ids FROM ai.pick_reviews r
               WHERE r.fixture_id = p.fixture_id AND r.market_key = p.market_key AND r.selection = p.selection
                 AND r.line = p.line AND r.engine = 'combined' AND r.reviewed_at < f.kickoff_at
               ORDER BY r.reviewed_at DESC, r.id DESC LIMIT 1) rv ON true;
        COMMENT ON VIEW picks.v_pick_record IS
          'One pick''s whole record: what was decided before kick-off (frozen), the AI''s last pre-match review of the
           selection, the result and the line value against the last pre-match price.';
    """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS picks.v_pick_record;
        DROP TABLE IF EXISTS picks.settlement_latency;
        DROP TRIGGER IF EXISTS pick_candidates_frozen ON picks.pick_candidates;
        DROP FUNCTION IF EXISTS picks.pick_candidates_frozen();
        DROP TRIGGER IF EXISTS picks_parlay_legs_frozen ON picks.parlay_legs;
        DROP FUNCTION IF EXISTS picks.picks_parlay_legs_frozen();
        DROP TRIGGER IF EXISTS picks_daily_set_items_frozen ON picks.daily_set_items;
        DROP FUNCTION IF EXISTS picks.picks_daily_set_items_frozen();
        DROP TRIGGER IF EXISTS picks_picks_frozen ON picks.picks;
        DROP FUNCTION IF EXISTS picks.picks_picks_frozen();
    """)
