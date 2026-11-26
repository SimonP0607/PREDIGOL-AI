"""raw.backfill_tasks accepts the expansion tiers 10 to 13 (plan PM, PM-03-07, DM-03)

WHY THIS EXISTS
---------------
Migration 0023 gave ``raw.backfill_tasks.tier`` an unnamed column check, ``CHECK (tier BETWEEN 1 AND 9)``, when the nine tiers of the selection
were all there was. The expansion batches of ``config/expansion.yaml`` take the tier 4 + N (PM-03-03..06: batch 6 is tier 10, 7 is 11, 8 is 12,
9 is 13), and the history of their competitions (``python -m scripts.migration seed --tiers 10 --depth 2``, PM-03-07) is refused by that check
(``backfill_tasks_tier_check``) on the first row. The seed runs in one transaction, so nothing was written: the table is as it was.

WHAT CHANGES
------------
The same check, named as it was, now reads ``tier BETWEEN 1 AND 13``. It is wider, never narrower: every row that satisfied the old check
satisfies the new one, and the code that ran before keeps working (it never writes a tier above 9). The new check is added ``NOT VALID`` and
validated at once (a scan that takes a ``SHARE UPDATE EXCLUSIVE`` lock, not one that blocks reads or writes); ``lock_timeout`` is 10 s. No row
is read or written, no table or column is added or dropped. Downgrade puts back the 1 to 9 range, which is refused (the check would fail on its
own validation) while any row of tier 10 or above exists: the history it holds is never deleted by a downgrade.

Revision ID: 0178
Revises: 0177
"""

from __future__ import annotations

from alembic import op

revision = "0178"
down_revision = "0177"
branch_labels = None
depends_on = None

TABLE = "raw.backfill_tasks"
CONSTRAINT = "backfill_tasks_tier_check"


def _swap(upper: int) -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK (tier BETWEEN 1 AND {upper}) NOT VALID")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CONSTRAINT}")


def upgrade() -> None:
    _swap(13)


def downgrade() -> None:
    """The range of 0023. It fails, on purpose, if a task of tier 10 or above exists: a downgrade never deletes history."""
    _swap(9)
