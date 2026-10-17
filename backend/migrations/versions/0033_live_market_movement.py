"""live market movement: what changed, when, and what the match was doing

The next stage of the in-play pipeline:

    LIVE FIXTURE -> LIVE ODDS -> RAW PAYLOAD -> NORMALISATION
                 -> LIVE MARKET SNAPSHOT -> **LIVE MARKET MOVEMENT** -> LIVE INTELLIGENCE

A VIEW, not a table. Movement is a difference between two rows of
market.live_odds_snapshots, and that series is append-only, so the difference is
a function of data we already hold. Storing it would create a second copy that
has to agree with the first - and every defect this project has had to repair
has been two copies of a fact with nothing forcing them to agree: the 90-minute
score reconstructed by subtraction instead of read, the fixtures horizon kept in
two places, the lineage check's hand-written relation list. Deriving costs a
window function over an indexed, partitioned table; the alternative costs
correctness.

WHAT A ROW MEANS
----------------
One row per observed price change, for one selection of one market of one
fixture. ``previous_odds`` is the price this one replaced and ``previous_at``
when it was seen, so a row says "this price moved from X to Y between these two
instants, at this minute, at this score".

MEASURED SO THE SHAPE IS RIGHT
------------------------------
The provider sweeps its whole live book about every 31 s and roughly 27% of
prices move per sweep, so consecutive snapshots of the same selection mostly
carry the SAME number. Those are not movement and the view drops them: a reader
asking "when did this price move" must not have to filter out the instants when
it did not. 20.9% of prices never moved at all across a two-minute measurement,
which is exactly why the snapshot series keeps them and this view does not.

A suspension is movement of a different kind and is kept: ``became_suspended``
and ``became_available`` mark the instants a market froze or reopened, measured
at up to 96 values thawing in a single sweep.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

UPGRADE = """
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
    odds_decimal - previous_odds        AS odds_delta,
    -- Implied probability moves linearly in 1/odds, so this is the number a
    -- reader actually wants: 2.00 -> 1.90 is a bigger move than 10.0 -> 9.9.
    (1.0 / odds_decimal - 1.0 / previous_odds)::numeric(10,6)
                                        AS implied_prob_delta,
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
    -- A goal between the two observations. The reason the score rides on every
    -- snapshot row: without it a price jump has no explanation attached.
    (score_home IS DISTINCT FROM previous_score_home
     OR score_away IS DISTINCT FROM previous_score_away) AS score_changed,
    status_long,
    payload_hash
FROM ordered
WHERE previous_at IS NOT NULL
  AND (odds_decimal IS DISTINCT FROM previous_odds
       OR is_suspended IS DISTINCT FROM previous_suspended);

COMMENT ON VIEW market.live_market_movement IS
  'One row per observed in-play price change, with the match state on both sides '
  'of it. Derived from market.live_odds_snapshots rather than stored: movement is '
  'a difference between two rows of an append-only series, and a stored copy '
  'would be a second version of a fact that then has to agree with the first.';
"""

DOWNGRADE = "DROP VIEW IF EXISTS market.live_market_movement;"


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
