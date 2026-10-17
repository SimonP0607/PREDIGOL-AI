"""the 90-minute score markets settle on, and the shadow-pick lifecycle

REGULATION SCORE. core.fixture_results.goals_* are the provider's `goals`: the
score after extra time, penalties excluded (PSV 3-1 Juventus, 19 Feb 2025,
was 2-1 at 90 minutes; the row says 3 goals with 1 in extra time). 1X2,
Over/Under and BTTS settle on the regulation score, so reg_goals_* are
derived as goals minus extra-time goals, and outcome_1x2, total_goals and
btts are redefined on that basis. Nothing is lost: the final score stays in
goals_*, and ratings that count extra time keep reading it.

PICK LIFECYCLE.

    candidate --(rule)--> shadow --(gates)--> qualified --> published --> settled
         \\--> rejected (with the rule that failed)

picks.pick_candidates holds every evaluated (prediction, price) pair with
its decision; a selected candidate becomes a picks.picks row in status
'shadow'. 'qualified' needs gates that no current model passes (a
validated edge over the market); 'published' is DISABLED by a constraint -
enabling it is a migration and a human decision, not a flag. Every status
change is appended to picks.pick_events.

A pick made from an uncalibrated probability says so (calibrator_id NULL),
and one without an interval says that too (NULL bounds, never zero width).

SETTLEMENT. pick_results records the basis (regulation 90 minutes), the
rule version, the payload the result came from, and - for anything the
rules do not settle unambiguously (abandoned, awarded, postponed, an extra
time result without its breakdown) - the reason it stays pending.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE core.fixture_results
    ADD CONSTRAINT fixture_results_et_within_final CHECK (
        (et_goals_home IS NULL OR et_goals_home <= goals_home)
        AND (et_goals_away IS NULL OR et_goals_away <= goals_away)),
    ADD COLUMN reg_goals_home SMALLINT GENERATED ALWAYS AS (goals_home - COALESCE(et_goals_home, 0)) STORED,
    ADD COLUMN reg_goals_away SMALLINT GENERATED ALWAYS AS (goals_away - COALESCE(et_goals_away, 0)) STORED;
ALTER TABLE core.fixture_results DROP COLUMN outcome_1x2, DROP COLUMN total_goals, DROP COLUMN btts;
ALTER TABLE core.fixture_results
    ADD COLUMN outcome_1x2 TEXT GENERATED ALWAYS AS (
        CASE WHEN goals_home - COALESCE(et_goals_home, 0) > goals_away - COALESCE(et_goals_away, 0) THEN 'Home'
             WHEN goals_home - COALESCE(et_goals_home, 0) = goals_away - COALESCE(et_goals_away, 0) THEN 'Draw'
             ELSE 'Away' END) STORED,
    ADD COLUMN total_goals SMALLINT GENERATED ALWAYS AS (
        goals_home - COALESCE(et_goals_home, 0) + goals_away - COALESCE(et_goals_away, 0)) STORED,
    ADD COLUMN btts BOOLEAN GENERATED ALWAYS AS (
        goals_home - COALESCE(et_goals_home, 0) > 0 AND goals_away - COALESCE(et_goals_away, 0) > 0) STORED;
COMMENT ON COLUMN core.fixture_results.goals_home IS
  'Final score after extra time, penalties excluded (the provider''s goals).';
COMMENT ON COLUMN core.fixture_results.reg_goals_home IS
  'Regulation (90 minutes + stoppage) score: what 1X2, Over/Under and BTTS settle on.';

-- ---------------------------------------------------------------- candidates
ALTER TABLE picks.pick_candidates
    ADD COLUMN decision_rule_version TEXT,
    ADD COLUMN odds_captured_at      TIMESTAMPTZ,
    ADD COLUMN odds_payload_hash     TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN consensus_method      TEXT,
    ADD COLUMN consensus_as_of       TIMESTAMPTZ,
    ADD COLUMN data_cutoff_ts        TIMESTAMPTZ,
    ADD CONSTRAINT pick_candidates_prediction_before_price CHECK (
        data_cutoff_ts IS NULL OR odds_captured_at IS NULL OR data_cutoff_ts <= odds_captured_at);
CREATE UNIQUE INDEX pick_candidates_one_per_price ON picks.pick_candidates
    (prediction_id, market_key, selection, line, odds_captured_at, decision_rule_version);

-- ---------------------------------------------------------------------- picks
ALTER TABLE picks.picks
    ALTER COLUMN calibrator_id DROP NOT NULL,
    ALTER COLUMN ev_adjusted DROP NOT NULL,
    ALTER COLUMN p_calibrated_lo DROP NOT NULL,
    ALTER COLUMN p_calibrated_hi DROP NOT NULL,
    DROP CONSTRAINT picks_check,
    ADD CONSTRAINT picks_interval_check CHECK (
        (p_calibrated_lo IS NULL AND p_calibrated_hi IS NULL)
        OR (p_calibrated_lo IS NOT NULL AND p_calibrated_hi IS NOT NULL
            AND p_calibrated_lo <= p_calibrated AND p_calibrated <= p_calibrated_hi)),
    ADD COLUMN prediction_id     BIGINT REFERENCES models.predictions(id),
    ADD COLUMN odds_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN consensus_method  TEXT,
    ADD COLUMN consensus_as_of   TIMESTAMPTZ,
    ADD COLUMN stake_policy      TEXT NOT NULL DEFAULT 'flat_1u',
    ADD COLUMN qualification     JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN status            TEXT NOT NULL DEFAULT 'shadow'
        CHECK (status IN ('shadow', 'qualified', 'published', 'settled')),
    ADD COLUMN status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD CONSTRAINT picks_publishing_disabled CHECK (status <> 'published' AND published_at IS NULL AND mode = 'shadow');
COMMENT ON CONSTRAINT picks_publishing_disabled ON picks.picks IS
  'Publishing is disabled. Enabling it is a migration and a human decision, never a runtime flag.';
COMMENT ON COLUMN picks.picks.calibrator_id IS 'NULL: the probability is the model''s own, uncalibrated.';
COMMENT ON COLUMN picks.picks.ev_adjusted IS 'EV at the lower bound of the probability interval; NULL without an interval.';

CREATE TABLE picks.pick_events (
    id          BIGSERIAL PRIMARY KEY,
    pick_id     BIGINT      NOT NULL REFERENCES picks.picks(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT        NOT NULL,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason      TEXT        NOT NULL,
    run_id      BIGINT REFERENCES raw.ingestion_runs(id)
);
CREATE INDEX ON picks.pick_events (pick_id, at);
COMMENT ON TABLE picks.pick_events IS 'Append-only history of every pick status change, with why.';

-- ----------------------------------------------------------------- settlement
ALTER TABLE picks.pick_results
    ADD COLUMN settlement_basis    TEXT,
    ADD COLUMN rule_version        TEXT,
    ADD COLUMN result_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN review_reason       TEXT,
    ADD CONSTRAINT pick_results_final_has_basis CHECK (
        result_status = 'pending' OR (settlement_basis IS NOT NULL AND rule_version IS NOT NULL));
COMMENT ON COLUMN picks.pick_results.review_reason IS
  'Why a pick stays pending when the rules do not settle it unambiguously (abandoned, awarded, postponed...).';
"""

DOWNGRADE = """
ALTER TABLE picks.pick_results
    DROP CONSTRAINT pick_results_final_has_basis,
    DROP COLUMN review_reason, DROP COLUMN result_payload_hash, DROP COLUMN rule_version,
    DROP COLUMN settlement_basis;
DROP TABLE IF EXISTS picks.pick_events;
DELETE FROM picks.pick_results;
DELETE FROM picks.pick_line_value;
DELETE FROM audit.decision_audit WHERE pick_id IS NOT NULL;
DELETE FROM picks.picks;
ALTER TABLE picks.picks
    DROP CONSTRAINT picks_publishing_disabled,
    DROP COLUMN status_changed_at, DROP COLUMN status, DROP COLUMN qualification, DROP COLUMN stake_policy,
    DROP COLUMN consensus_as_of, DROP COLUMN consensus_method, DROP COLUMN odds_payload_hash,
    DROP COLUMN prediction_id,
    DROP CONSTRAINT picks_interval_check,
    ALTER COLUMN p_calibrated_hi SET NOT NULL,
    ALTER COLUMN p_calibrated_lo SET NOT NULL,
    ALTER COLUMN calibrator_id SET NOT NULL,
    ALTER COLUMN ev_adjusted SET NOT NULL,
    ADD CONSTRAINT picks_check CHECK (p_calibrated_lo <= p_calibrated AND p_calibrated <= p_calibrated_hi);
DROP INDEX IF EXISTS picks.pick_candidates_one_per_price;
ALTER TABLE picks.pick_candidates
    DROP CONSTRAINT pick_candidates_prediction_before_price,
    DROP COLUMN data_cutoff_ts, DROP COLUMN consensus_as_of, DROP COLUMN consensus_method,
    DROP COLUMN odds_payload_hash, DROP COLUMN odds_captured_at, DROP COLUMN decision_rule_version;
ALTER TABLE core.fixture_results DROP COLUMN outcome_1x2, DROP COLUMN total_goals, DROP COLUMN btts;
ALTER TABLE core.fixture_results
    DROP COLUMN reg_goals_home, DROP COLUMN reg_goals_away,
    DROP CONSTRAINT fixture_results_et_within_final;
ALTER TABLE core.fixture_results
    ADD COLUMN outcome_1x2 TEXT GENERATED ALWAYS AS (
        CASE WHEN goals_home > goals_away THEN 'Home' WHEN goals_home = goals_away THEN 'Draw' ELSE 'Away' END) STORED,
    ADD COLUMN total_goals SMALLINT GENERATED ALWAYS AS (goals_home + goals_away) STORED,
    ADD COLUMN btts BOOLEAN GENERATED ALWAYS AS (goals_home > 0 AND goals_away > 0) STORED;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
