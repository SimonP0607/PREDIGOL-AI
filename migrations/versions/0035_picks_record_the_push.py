"""a pick on a pushable line must record the push it was reasoned about

Every number a decision used is recorded, so the decision can be re-derived
years later without rerunning anything. A pick on a whole or quarter line was
about to break that: the stored ``p_calibrated`` is the probability the model
and the market were compared ON - conditional on the bet being settled, because
a de-vigged two-way book cannot express a push - while the stored expected value
was computed from the unconditional pair. Without the push probability the two
cannot be reconciled from the row, and the row is the record.

So ``p_push`` joins both tables, defaulting to 0, which is what every market
that cannot push is and what every row written before now was.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE picks.pick_candidates
    ADD COLUMN p_push NUMERIC(8,6) NOT NULL DEFAULT 0
        CHECK (p_push >= 0 AND p_push <= 1);
ALTER TABLE picks.picks
    ADD COLUMN p_push NUMERIC(8,6) NOT NULL DEFAULT 0
        CHECK (p_push >= 0 AND p_push <= 1);

COMMENT ON COLUMN picks.pick_candidates.p_calibrated IS
  'The model probability the comparison was made ON: conditional on the bet '
  'being settled, because market_consensus.p_fair is - two selections de-vigged '
  'to sum to 1 cannot express a push. Multiply by (1 - p_push) for the '
  'unconditional win probability, which is what ev was computed from.';
COMMENT ON COLUMN picks.pick_candidates.p_push IS
  'Probability the bet returns the stake. 0 for every market that cannot push.';
COMMENT ON COLUMN picks.picks.p_calibrated IS
  'As picks.pick_candidates.p_calibrated: conditional on the bet being settled.';
COMMENT ON COLUMN picks.picks.p_push IS
  'Probability the bet returns the stake. 0 for every market that cannot push.';
"""

DOWNGRADE = """
ALTER TABLE picks.picks DROP COLUMN IF EXISTS p_push;
ALTER TABLE picks.pick_candidates DROP COLUMN IF EXISTS p_push;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
