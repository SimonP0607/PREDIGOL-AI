"""a prediction on a line that can push needs two numbers, not one

WHAT WAS WRONG WITH ONE
-----------------------
``models.predictions`` stored a single probability per (market, selection,
line). For 1X2, Both Teams Score and a half line that is the whole story. For
anything that can return the stake it is ambiguous: 0.45 on "Asian Handicap
Home -1.0" could mean a 45% chance of winning the bet, or a 45% chance given it
is settled at all. The two imply different fair prices and different expected
values, and nothing in the row said which.

Measured over our own stored prices, this is most of the series, not an edge
case:

    AH   quarter lines 4,309 rows   half 2,405   whole 2,127   (66% can push)
    OU   half lines    5,013 rows   quarter 3,410  whole 1,817  (51% can push)

So ``p_push`` is added, defaulting to 0. Every existing row is a market that
cannot push and is therefore correct as it stands - 1X2, BTTS, and Over/Under
2.5, which was the only line the model priced.

WHY THE MARKETS WERE DISABLED, AND WHY THEY NEED NOT BE
-------------------------------------------------------
market.markets had is_model_enabled = false for AH and DC, with 8,841 and 1,444
prices captured against them and no model number to compare. Neither needs
anything fitted: both are exact projections of the score matrix the goal model
already computes. Double Chance is three additions of the 1X2 probabilities;
Asian Handicap is a statement about the goal-difference distribution, which is
the same matrix read along its diagonals. See fbi.models.lines.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE models.predictions
    ADD COLUMN p_push NUMERIC(8,6) NOT NULL DEFAULT 0
        CHECK (p_push >= 0 AND p_push <= 1),
    ADD CONSTRAINT predictions_win_and_push_fit
        CHECK (p_calibrated + p_push <= 1.000001);

COMMENT ON COLUMN models.predictions.p_push IS
  'Probability the bet returns the stake. 0 for every market that cannot push, '
  'which is what every row predating this column is. A whole line pushes '
  'outright; a quarter line is two half-stakes and pushes on one of them, so it '
  'carries half the whole leg''s push probability - the averaged pair reproduces '
  'the split bet''s expected value exactly.';

COMMENT ON COLUMN models.predictions.p_calibrated IS
  'Probability the bet WINS - not conditional on being settled. The fair price '
  'is (1 - p_push) / p_calibrated, which is shorter than 1/p when a push is '
  'possible, because a returned stake is not a loss the price has to cover.';

-- Both are exact functions of the score matrix the goal model already computes.
-- Enabling them does not add a model; it stops discarding 10,285 captured prices.
UPDATE market.markets SET is_model_enabled = true WHERE key IN ('AH', 'DC');
"""

DOWNGRADE = """
UPDATE market.markets SET is_model_enabled = false WHERE key IN ('AH', 'DC');
ALTER TABLE models.predictions
    DROP CONSTRAINT IF EXISTS predictions_win_and_push_fit,
    DROP COLUMN IF EXISTS p_push;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
