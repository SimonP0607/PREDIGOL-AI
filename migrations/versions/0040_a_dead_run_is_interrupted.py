"""a run whose process died is interrupted, not still running

When the machine shut down on 1 Oct the worker went with it, and five ledger
rows stayed 'running' for days: a fixtures sync from 29 Sep, a backfill, a live
capture, a team-identity pass and a pick pipeline. Nothing could ever finish
them, and the health check reported the worker as degraded for as long as they
existed, which was forever.

None of the existing statuses is true of them. 'failed' says an error happened;
'aborted' says a cap stopped the run. What happened is that the process ended,
and what work it did before that is whatever its rows say. So a new status,
'interrupted', which the worker sets at startup on runs that began before the
machine last booted (see fbi.ops.reaper) - those cannot still be running here.

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE raw.ingestion_runs DROP CONSTRAINT ingestion_runs_status_check;
        ALTER TABLE raw.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check
            CHECK (status IN ('running', 'completed', 'partial', 'failed', 'aborted', 'interrupted'));
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE raw.ingestion_runs SET status = 'failed' WHERE status = 'interrupted';
        ALTER TABLE raw.ingestion_runs DROP CONSTRAINT ingestion_runs_status_check;
        ALTER TABLE raw.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check
            CHECK (status IN ('running', 'completed', 'partial', 'failed', 'aborted'));
    """)
