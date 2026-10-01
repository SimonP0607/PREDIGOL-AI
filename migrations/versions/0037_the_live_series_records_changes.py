"""the live series records changes, and a withdrawal is a change

WHY
---
The capture wrote 108 rows per fixture per instant whether or not anything had
moved. Measured over 36,952 real rows:

    stored today                 36,952
    first quotes                    772
    prices that actually moved    8,786
    keys that stopped being quoted 1,000
    keys that started or returned    482
    ---------------------------------------
    change-only rows             11,040   ->  3.35x fewer

The provider sweeps its whole live book about every 31 s and only ~27% of prices
move per sweep, so nearly three quarters of what was stored was a second copy of
a number already held - at 293 bytes a row, 140 GB a year of it.

WHY THIS IS STILL A COMPLETE SERIES
-----------------------------------
market.live_fixture_states already records EVERY instant the capture observed,
one row per fixture per tick. So the price of a selection at any instant T is
the latest row at or before T, and "was it observed at T" is answerable without
the prices. Nothing is overwritten and nothing is lost: the redundant rows were
not information, they were repetition.

WHY odds_decimal BECOMES NULLABLE
---------------------------------
Carrying the last value forward is only correct while the provider is still
quoting it. Markets appear and vanish between sweeps - one measured cycle
dropped 325 values as a match wound down - and 1,000 of these keys stopped being
quoted at some point. Without recording that, reconstruction would report a
price for a market that no longer existed, which is inventing data.

So NULL means: at this instant the provider stopped offering this selection.
It is not a price of zero and not a suspension - a suspended value still carries
a real price 210 times out of 1,933 and is stored as such. It is the absence of
a quote, recorded explicitly, which is the only honest way to say it.

The existing 36,952 rows keep their redundancy, which is harmless:
reconstruction reads the latest row at or before an instant, and a redundant row
gives the same answer as its predecessor.

What is NOT harmless, and what this docstring originally claimed was fine, is
that the old writer never recorded a withdrawal. Checking the claim instead of
trusting it: the view rebuilt 72,779 rows from 36,952, losing none and inventing
35,827 - prices carried across gaps where the market had actually gone. 0039
recovers those 1,000 withdrawal events from live_fixture_states, after which
stored and rebuilt agree exactly, 36,952 to 36,952.

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE market.live_odds_snapshots
    DROP CONSTRAINT IF EXISTS live_odds_snapshots_odds_decimal_check;

ALTER TABLE market.live_odds_snapshots
    ALTER COLUMN odds_decimal DROP NOT NULL,
    ADD CONSTRAINT live_odds_price_or_withdrawal CHECK (
        odds_decimal IS NULL
        OR (odds_decimal > 1.0 AND odds_decimal < 1000)
    );

COMMENT ON COLUMN market.live_odds_snapshots.odds_decimal IS
  'The price, or NULL meaning the provider stopped offering this selection at '
  'this instant. NULL is not zero and not a suspension: a suspended value keeps '
  'its price and its is_suspended flag. Recording the withdrawal is what makes '
  'carrying the last value forward correct - without it, reconstruction would '
  'report a price for a market that had gone.';

COMMENT ON TABLE market.live_odds_snapshots IS
  'In-play prices, one row per CHANGE of (price, suspended, offered) per '
  'market/selection/line. Append only - a price is never overwritten. '
  'Unchanged re-observations are not repeated: market.live_fixture_states '
  'records every instant observed, so the price at any instant is the latest '
  'row at or before it, and the series is complete without being repetitive. '
  'No bookmaker column: /odds/live was measured to return a single aggregated '
  'price with no bookmaker dimension.';

-- Reconstruct the full-fidelity series: what was on offer at each observed
-- instant, carrying each price forward from the row that last changed it.
CREATE VIEW market.live_odds_at_instant AS
SELECT s.fixture_id,
       o.captured_at,
       s.provider_bet_id,
       s.market_key,
       s.selection,
       s.line,
       s.odds_decimal,
       s.is_suspended,
       s.is_main_line,
       s.captured_at AS priced_at,
       o.captured_at <> s.captured_at AS carried_forward
FROM market.live_fixture_states o
CROSS JOIN LATERAL (
    SELECT DISTINCT ON (x.provider_bet_id, x.selection, x.line)
           x.provider_bet_id, x.market_key, x.selection, x.line,
           x.odds_decimal, x.is_suspended, x.is_main_line, x.captured_at,
           x.fixture_id
    FROM market.live_odds_snapshots x
    WHERE x.fixture_id = o.fixture_id
      AND x.captured_at <= o.captured_at
    ORDER BY x.provider_bet_id, x.selection, x.line, x.captured_at DESC
) s
WHERE s.odds_decimal IS NOT NULL;

COMMENT ON VIEW market.live_odds_at_instant IS
  'The in-play book as it stood at every observed instant, rebuilt from the '
  'change rows. One row per selection on offer, with priced_at saying when that '
  'price was last set and carried_forward marking the instants where it had not '
  'changed. Withdrawn selections drop out, which is why the withdrawal rows '
  'exist. This is what the series would look like if every tick had been stored '
  'in full - it is derived rather than stored, because storing it was the 3.35x.';
"""

DOWNGRADE = """
DROP VIEW IF EXISTS market.live_odds_at_instant;
DELETE FROM market.live_odds_snapshots WHERE odds_decimal IS NULL;
ALTER TABLE market.live_odds_snapshots
    DROP CONSTRAINT IF EXISTS live_odds_price_or_withdrawal,
    ALTER COLUMN odds_decimal SET NOT NULL,
    ADD CONSTRAINT live_odds_snapshots_odds_decimal_check
        CHECK (odds_decimal > 1.0 AND odds_decimal < 1000);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
