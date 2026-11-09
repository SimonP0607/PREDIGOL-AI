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
the revision drops it first (also CONCURRENTLY), so running it again is safe. No table is rewritten and no row changes; the rollback
drops the indexes.

WHAT THE FIRST PRODUCTION ATTEMPT TAUGHT (2026-11-09; the revision had not been applied anywhere, so it is corrected here)
-------------------------------------------------------------------------------------------------------------------------
``CREATE INDEX CONCURRENTLY`` blocks nobody, but it WAITS for every transaction that already holds a write lock on the table, three
times (before the build, after it, before validating). The worker keeps write transactions open for tens of seconds, and the
``lock_timeout`` of 10 s copied from revision 0085 (a table written far less often) cancelled the build while it waited: ``LockNotAvailable``,
an empty INVALID index left behind. The second try then failed for a second reason: the cleanup was a plain ``DROP INDEX``, which asks for
an ACCESS EXCLUSIVE lock on the table - behind the same writers, and while it waits it holds back every other session on the table. So: the
waits are allowed 5 minutes (they hold nobody back), the whole statement 30, and the cleanup of an INVALID index is ``DROP INDEX
CONCURRENTLY``, which waits the same way and holds nobody back. The deploy kit stopped on its own with the services untouched.

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


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # CONCURRENTLY waits for the writers that are already inside the table (and holds nobody back while it waits): the worker's
        # write transactions last tens of seconds, so the waits get minutes, not the 10 s that suits a table written rarely
        op.execute("SET lock_timeout = '5min'")
        op.execute("SET statement_timeout = '30min'")
        bind = op.get_bind()
        for schema, table, name, column in INDEXES:
            # an index left INVALID by a build that was interrupted is not used and blocks the name; a plain DROP INDEX would need an
            # ACCESS EXCLUSIVE lock on the table, so it goes the same way as the build
            invalid = bind.execute(
                sa.text(
                    "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :name AND NOT i.indisvalid"
                ),
                {"schema": schema, "name": name},
            ).first()
            if invalid is not None:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {schema}.{table} USING BRIN ({column})")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")
    for schema, table, name, column in INDEXES:
        op.execute(f"COMMENT ON INDEX {schema}.{name} IS "
                   f"'The admin overview counts {table} by {column} over the last 24 hours (UX-081): BRIN, because the column is written in "
                   "time order. Built concurrently (0130).'")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for schema, _table, name, _column in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{name}")
