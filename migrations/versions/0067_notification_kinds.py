"""notification kinds: the run watchdog's two messages are kinds the database accepts.

From 5 Oct 2026 05:45 UTC the notifier drafted ``run_recovered`` (a run the watchdog closed) and ``job_failing`` (a
job whose last three runs failed), but audit.notifications' CHECK listed only the five kinds of revision 0021. The
database refused the first such message of every notifier run and the refusal rolled back all the others with it:
no notification at all was recorded from 5 Oct 04:07 UTC until this revision (found in the PostgreSQL log during the
recovery of 6 Oct 2026). The CHECK now lists every kind of fbi.notify.service.KINDS; a test holds the two together.

Revision ID: 0067
Revises: 0066
"""

from __future__ import annotations

from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None

BEFORE = ("shadow_pick", "pick_settled", "first_capture", "capture_failed", "worker_down")
AFTER = (*BEFORE, "run_recovered", "job_failing")


def _in(kinds: tuple[str, ...]) -> str:
    return ", ".join(f"'{k}'" for k in kinds)


def upgrade() -> None:
    op.execute("ALTER TABLE audit.notifications DROP CONSTRAINT IF EXISTS notifications_kind_check")
    op.execute(f"ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN ({_in(AFTER)}))")


def downgrade() -> None:
    # Messages of the two newer kinds stay (history is not deleted): the older CHECK holds for new rows only.
    op.execute("ALTER TABLE audit.notifications DROP CONSTRAINT IF EXISTS notifications_kind_check")
    op.execute(f"ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check "
               f"CHECK (kind IN ({_in(BEFORE)})) NOT VALID")
