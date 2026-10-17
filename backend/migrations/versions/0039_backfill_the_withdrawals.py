"""backfill the withdrawals the old writer never recorded

I claimed in 0037 that the pre-existing rows and the change-only rows would read
identically through market.live_odds_at_instant, because a redundant row gives
the same answer as its predecessor. The redundant rows were indeed harmless. The
claim was still wrong, and checking it said so:

    rows stored               36,952
    rows rebuilt              72,779
    stored but not rebuilt         0   <- nothing lost, as promised
    rebuilt but not stored    35,827   <- and 35,827 invented

The old writer stored a quote only when the provider offered it, and never
recorded that one had stopped being offered. So for the historical rows there is
nothing to stop the view carrying a price across a gap where the market was
genuinely absent - which is precisely the failure the withdrawal rows exist to
prevent, present in the one place I had asserted it was not.

This recovers those events. They are fully determined by what is already on
record: market.live_fixture_states lists every instant each fixture was
observed, so a key that was quoted at one instant and is absent at the next
observed instant of the same fixture stopped being quoted then. No guessing, no
new requests - the same reconstruction the view does, run once and written down.

The match state on each backfilled row is copied from live_fixture_states for
that fixture and instant, which is where the live writer gets it too, and the
payload_hash is that capture's own - so these rows have the same lineage as any
other.

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

UPGRADE = """
WITH keys AS (
    SELECT DISTINCT fixture_id, provider_bet_id, selection, line, market_key
    FROM market.live_odds_snapshots
),
grid AS (
    SELECT k.fixture_id, k.provider_bet_id, k.selection, k.line, k.market_key,
           o.captured_at,
           s.odds_decimal,
           o.elapsed_minute, o.elapsed_seconds, o.score_home, o.score_away,
           o.status_long, o.is_stopped, o.is_blocked, o.provider_updated_at,
           o.payload_hash
    FROM keys k
    JOIN market.live_fixture_states o ON o.fixture_id = k.fixture_id
    LEFT JOIN market.live_odds_snapshots s
      ON s.fixture_id = k.fixture_id
     AND s.provider_bet_id = k.provider_bet_id
     AND s.selection = k.selection
     AND s.line = k.line
     AND s.captured_at = o.captured_at
),
seq AS (
    SELECT *,
           lag(odds_decimal) OVER w AS prev_odds,
           row_number() OVER w AS n
    FROM grid
    WINDOW w AS (PARTITION BY fixture_id, provider_bet_id, selection, line
                 ORDER BY captured_at)
)
INSERT INTO market.live_odds_snapshots
    (fixture_id, provider_bet_id, market_key, selection, line,
     odds_decimal, is_suspended, is_main_line,
     elapsed_minute, elapsed_seconds, score_home, score_away,
     status_long, is_stopped, is_blocked, provider_updated_at,
     captured_at, payload_hash)
SELECT fixture_id, provider_bet_id, market_key, selection, line,
       NULL, false, NULL,
       elapsed_minute, elapsed_seconds, score_home, score_away,
       status_long, is_stopped, is_blocked, provider_updated_at,
       captured_at, payload_hash
FROM seq
WHERE n > 1 AND prev_odds IS NOT NULL AND odds_decimal IS NULL
ON CONFLICT DO NOTHING;
"""

DOWNGRADE = """
-- Only the backfilled rows: a withdrawal the live writer recorded has a
-- payload_hash from the capture that observed it, and so does this - there is
-- no way to tell them apart, so the downgrade removes all of them and relies on
-- 0037's own downgrade having the same effect.
DELETE FROM market.live_odds_snapshots WHERE odds_decimal IS NULL;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
