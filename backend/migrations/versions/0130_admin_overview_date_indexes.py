"""Two BRIN indexes by date for the admin overview's 24-hour counts (UX-081; Sentry PREDIGOL-BACKEND-5 and -6)

WHY THIS EXISTS
---------------
The owner's overview (``GET /admin/overview``, ``fbi.api.repositories.center.CAPTURES``) counts, in one statement of fourteen
sub-queries, what the last 24 hours brought. The read pool gives a statement 10 s. Measured on the production database on
2026-11-09 (quiet, sub-queries one by one): ``models.predictions WHERE created_at > now() - 24 h`` took 2.9 s and
``picks.pick_candidates WHERE evaluated_at > now() - 24 h`` up to 3.0 s, of about 8 s for the whole statement; with the worker busy it
went over 10 s and Sentry recorded ``QueryCanceled`` (the next try answered 200).

The plan of the first was a parallel sequential scan of the whole table (about 4.75 million rows, 1.4 GB: no index starts with
``created_at``). ``pick_candidates`` (about 2.1 million rows) has only (fixture_id, evaluated_at) and (decision, evaluated_at), which
serve a count by date only when the planner happens to choose an index-only scan of the first one (0.4 s one time, 3 s another).

Both columns are written once, in time order: the planner's own statistics (``pg_stats.correlation``) read 1.000 for each, which is
what a BRIN index needs. A BRIN index keeps the minimum and maximum of a block range, so it is a few kilobytes instead of the
hundred-odd megabytes of a b-tree, costs the writers next to nothing and answers "the last day" by reading the last few ranges -
the same type the odds snapshots already use for ``captured_at`` (revision 0010).

They are built CONCURRENTLY (as revision 0085): the worker writes to both tables all day, and a plain ``CREATE INDEX`` would hold
every one of those writes for as long as the build takes. That statement cannot run inside a transaction, so the revision leaves
alembic's for the builds and comes back (``autocommit_block``). A build that was interrupted leaves an INVALID index of the same name;
the revision drops it first, so running it again is safe. No table is rewritten and no row changes; the rollback drops the indexes.

WHAT THE FIRST PRODUCTION TRY TAUGHT (OPS-003, 2026-11-09)
-----------------------------------------------------------
The first try, with ``lock_timeout = '10s'``, failed on the production server: ``CREATE INDEX CONCURRENTLY`` waits for every
transaction that holds a write lock on the table when it starts and when it finishes, and something kept a write lock on the table for more than 10 s
(the worker's batches, most likely), so it timed out and left an INVALID index. The next tries failed at the cleanup, a plain ``DROP INDEX``: it takes an ACCESS EXCLUSIVE
lock, waits behind the same writers, and while it waits every new writer queues behind IT - the migration was stopping the worker's
writes for the whole timeout. The deploy stopped before touching the services (nothing was lost), but no release could go out.

Now: the leftover is dropped with ``DROP INDEX CONCURRENTLY`` (it waits like the build, and blocks nobody), and the wait is 90 s per
statement instead of 10 s; the deploy script still repeats the revision up to five times, and every repeat starts by dropping what the
last one left.

Revision ID: 0130
Revises: 0129
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0130"
down_revision = "0129"
branch_labels = None
depends_on = None

INDEXES = (
    ("models", "predictions", "predictions_created_at_brin", "created_at"),
    ("picks", "pick_candidates", "pick_candidates_evaluated_at_brin", "evaluated_at"),
)


# How long one statement may wait for the transactions that write to the table (a worker batch can outlast the first try's 10 s).
LOCK_WAIT = "90s"


def _left_invalid(schema: str, name: str) -> bool:
    """True when an index of this name exists and the planner ignores it (a build that was interrupted)."""
    found = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :name AND NOT i.indisvalid)"),
        {"schema": schema, "name": name},
    ).scalar()
    return bool(found)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"SET lock_timeout = '{LOCK_WAIT}'")
        for schema, table, name, column in INDEXES:
            # an index left INVALID by a build that was interrupted is not used and blocks the name; CONCURRENTLY, so that the
            # drop waits like the build does and never makes the worker's writes queue behind an ACCESS EXCLUSIVE request
            if _left_invalid(schema, name):
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {schema}.{table} USING BRIN ({column})")
        op.execute("RESET lock_timeout")
    for schema, table, name, column in INDEXES:
        op.execute(f"COMMENT ON INDEX {schema}.{name} IS "
                   f"'The admin overview counts {table} by {column} over the last 24 hours (UX-081): BRIN, because the column is written in "
                   "time order. Built concurrently (0130).'")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for schema, _table, name, _column in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{name}")
