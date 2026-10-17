"""a withdrawal is movement, but it is not a price change

market.live_market_movement compared consecutive rows of the series and called
any difference a move. Now that a withdrawal is a row with a NULL price, that
reads as a price going to NULL - which is true but useless: odds_delta comes out
NULL and a reader cannot tell "the market closed" from "the price moved".

So the view labels the three things separately. A price move has both prices and
an interpretable delta; a withdrawal and a return have neither and say so.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

UPGRADE = """
DROP VIEW IF EXISTS market.live_market_movement;

CREATE VIEW market.live_market_movement AS
WITH ordered AS (
    SELECT
        s.fixture_id,
        s.provider_bet_id,
        s.market_key,
        s.selection,
        s.line,
        s.captured_at,
        s.odds_decimal,
        s.is_suspended,
        s.is_main_line,
        s.elapsed_minute,
        s.score_home,
        s.score_away,
        s.status_long,
        s.payload_hash,
        lag(s.odds_decimal) OVER w  AS previous_odds,
        lag(s.captured_at)  OVER w  AS previous_at,
        lag(s.is_suspended) OVER w  AS previous_suspended,
        lag(s.elapsed_minute) OVER w AS previous_minute,
        lag(s.score_home)   OVER w  AS previous_score_home,
        lag(s.score_away)   OVER w  AS previous_score_away
    FROM market.live_odds_snapshots s
    WINDOW w AS (
        PARTITION BY s.fixture_id, s.provider_bet_id, s.selection, s.line
        ORDER BY s.captured_at
    )
)
SELECT
    fixture_id,
    provider_bet_id,
    market_key,
    selection,
    line,
    is_main_line,
    previous_at,
    captured_at,
    extract(epoch FROM captured_at - previous_at)::numeric(10,3) AS seconds_elapsed,
    previous_odds,
    odds_decimal                        AS odds,
    -- NULL on a withdrawal or a return, because there is no delta between a
    -- price and the absence of one. became_withdrawn says which it was.
    CASE WHEN odds_decimal IS NOT NULL AND previous_odds IS NOT NULL
         THEN odds_decimal - previous_odds END        AS odds_delta,
    CASE WHEN odds_decimal IS NOT NULL AND previous_odds IS NOT NULL
         THEN (1.0 / odds_decimal - 1.0 / previous_odds)::numeric(10,6) END
                                                      AS implied_prob_delta,
    (odds_decimal IS NOT NULL AND previous_odds IS NOT NULL
     AND odds_decimal <> previous_odds)               AS price_moved,
    (odds_decimal IS NULL AND previous_odds IS NOT NULL) AS became_withdrawn,
    (odds_decimal IS NOT NULL AND previous_odds IS NULL) AS became_offered,
    is_suspended,
    previous_suspended,
    (is_suspended AND NOT previous_suspended)  AS became_suspended,
    (previous_suspended AND NOT is_suspended)  AS became_available,
    previous_minute,
    elapsed_minute,
    previous_score_home,
    previous_score_away,
    score_home,
    score_away,
    (score_home IS DISTINCT FROM previous_score_home
     OR score_away IS DISTINCT FROM previous_score_away) AS score_changed,
    status_long,
    payload_hash
FROM ordered
WHERE previous_at IS NOT NULL;

COMMENT ON VIEW market.live_market_movement IS
  'One row per recorded change in the in-play book, with the match state on '
  'both sides of it. Since the series stores only changes, this is now every '
  'row of it bar each key''s first - the filtering that used to be here is done '
  'at write time. price_moved, became_withdrawn, became_offered, '
  'became_suspended and became_available say WHICH kind of change it was; '
  'odds_delta is NULL where there is no delta to take.';
"""

DOWNGRADE = """
DROP VIEW IF EXISTS market.live_market_movement;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
