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

HOW THEY ARE BUILT, AND WHY NOT CONCURRENTLY (what the first production attempt, 2026-11-09, taught; the revision had not been
applied anywhere, so it is corrected here)
-----------------------------------------------------------------------------------------------------------------------------------
The first version copied revision 0085 and built CONCURRENTLY with a ``lock_timeout`` of 10 s. It failed twice on the production
server, with the services untouched (the deploy kit stops by itself): the build was cancelled while it waited (``LockNotAvailable``,
an empty INVALID index left behind) and the retry could not clean that index up (a plain ``DROP INDEX`` asks for an ACCESS EXCLUSIVE lock
on the table). Looking at the live database showed the reason, and that a longer ``lock_timeout`` would not have been enough:
``CREATE INDEX CONCURRENTLY`` and ``DROP INDEX CONCURRENTLY`` wait for the transactions that hold a lock on the table or an old snapshot
(a read is enough), and the worker keeps sessions "idle in transaction" for ten minutes and more while it reads odds. They hold nobody
back while they wait, but they can wait for as long as the worker's longest transaction.

A BRIN build is a single sequential scan of the table (seconds: the same scan the count does today, which took 3 s with parallel
workers). So the indexes are built plainly: ``CREATE INDEX`` takes a SHARE lock, which holds back the WRITES of that table (not the
reads) for the seconds the scan lasts, and conflicts only with the transactions that are writing to it at that moment. The worker writes
in short bursts, so the revision tries with a short ``lock_timeout`` (a pending request also holds the writers back, so it must not wait
long) and a pause, as many times as it takes to find a gap. A failed plain build leaves nothing behind. No table is rewritten and no row
changes; the rollback drops the indexes.

An INVALID index of the same name (what a CONCURRENTLY build that was interrupted leaves; the first production attempt left one) is not
used and would make ``IF NOT EXISTS`` skip the build, so it is dropped first, CONCURRENTLY (a plain drop would hold every session
of the table back) and with a long wait: nothing is waiting for the migration, the services keep running the previous release.
At the end the revision checks that both indexes are valid, so it can never report success with an unusable one.

Revision ID: 0130
Revises: 0129
"""

from __future__ import annotations

import time

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

revision = "0130"
down_revision = "0129"
branch_labels = None
depends_on = None

INDEXES = (
    ("models", "predictions", "predictions_created_at_brin", "created_at"),
    ("picks", "pick_candidates", "pick_candidates_evaluated_at_brin", "evaluated_at"),
)

LOCK_WAIT = "2s"  # how long one try may hold the table's writers back while it waits for the ones inside to finish
PAUSE = 6  # seconds between two tries
TRIES = 100  # about 13 minutes in all
DROP_WAIT = "20min"  # for the cleanup of an INVALID index: it waits for the worker's longest transaction, and may

_LOCK_NOT_AVAILABLE = "55P03"


def _is_lock_timeout(exc: OperationalError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE


def _state(bind: Connection, schema: str, name: str) -> bool | None:
    """None: no such index; otherwise whether it is valid."""
    row = bind.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :name"
        ),
        {"schema": schema, "name": name},
    ).first()
    return None if row is None else bool(row[0])


def _build(bind: Connection, schema: str, table: str, name: str, column: str) -> None:
    for _ in range(TRIES):
        op.execute(f"SET lock_timeout = '{LOCK_WAIT}'")
        try:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {schema}.{table} USING BRIN ({column})")
            return
        except OperationalError as exc:
            if not _is_lock_timeout(exc):
                raise
        finally:
            op.execute("RESET lock_timeout")
        time.sleep(PAUSE)
    raise RuntimeError(
        f"{schema}.{table} was never free of writers for the {LOCK_WAIT} the index build needs to take its lock, in {TRIES} tries "
        f"({TRIES * PAUSE // 60} minutes): run the deploy again when the worker is quiet"
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        op.execute("SET statement_timeout = '30min'")
        for schema, table, name, column in INDEXES:
            if _state(bind, schema, name) is False:
                op.execute(f"SET lock_timeout = '{DROP_WAIT}'")
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{name}")
                op.execute("RESET lock_timeout")
            _build(bind, schema, table, name, column)
            if _state(bind, schema, name) is not True:
                raise RuntimeError(f"{schema}.{name} is not a valid index after the build")
        op.execute("RESET statement_timeout")
    for schema, table, name, column in INDEXES:
        op.execute(f"COMMENT ON INDEX {schema}.{name} IS "
                   f"'The admin overview counts {table} by {column} over the last 24 hours (UX-081): BRIN, because the column is written in "
                   "time order. Built in one pass, holding back the writers of the table for the scan (0130, corrected by BE-027).'")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for schema, _table, name, _column in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{name}")
