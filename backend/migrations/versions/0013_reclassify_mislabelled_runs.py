"""reclassify the runs the two-state rule got wrong

Revision 0012 added 'partial' but left history alone, so the run that
discovered the free plan's date horizon - 9 requests, 7 refused, 9 fixtures
imported - is still stored as 'completed'. That row is not merely old-fashioned,
it is wrong: it asserts the run finished without errors while its own
``errors`` column says 7. /health and the quality snapshot read these rows, so
leaving them makes both lie about yesterday.

This is not rewriting what happened. Every input to the decision is already in
the row - errors, rows_written, rows_updated, payloads_stored - and the new
rule is applied to the columns that were recorded at the time. Nothing is
invented and no counter is touched; only the label derived from them changes.

Deliberately narrow: a run is reclassified ONLY when its stored status
contradicts the recorded numbers. 'aborted' is never touched, because it says
something the numbers cannot - that a human or a cap stopped the run on
purpose.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

UPGRADE = """
-- errors AND something durable -> partial (was recorded as completed or failed)
UPDATE raw.ingestion_runs
   SET status = 'partial',
       notes = coalesce(notes || ' | ', '')
               || 'status reclassified by migration 0013 from ' || status
 WHERE status IN ('completed', 'failed')
   AND errors > 0
   AND (rows_written > 0 OR rows_updated > 0 OR payloads_stored > 0);

-- errors and nothing durable -> failed (was recorded as completed)
UPDATE raw.ingestion_runs
   SET status = 'failed',
       notes = coalesce(notes || ' | ', '') || 'status reclassified by migration 0013 from completed'
 WHERE status = 'completed'
   AND errors > 0
   AND rows_written = 0 AND rows_updated = 0 AND payloads_stored = 0;
"""

DOWNGRADE = """
-- 0012's downgrade maps partial -> failed, and that is the honest reverse
-- here too: errors happened, so 'completed' would be the one claim the row
-- cannot support. The note recording the reclassification is left in place -
-- deleting it would erase the fact that the label was ever corrected.
UPDATE raw.ingestion_runs SET status = 'failed' WHERE status = 'partial';
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
