"""job ledger: make raw.ingestion_runs answer "what did the system do at 03:00?"

Adds to raw.ingestion_runs the columns a run needs to be reconstructed after
the fact: when it was scheduled for, which attempt it was, how many payloads
it stored, how many rows it normalised, inserted and updated, and the last
error text. Existing columns keep their meaning; rows_written stays as the
insert counter's historical name and rows_inserted is a generated alias so
old and new readers agree.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE raw.ingestion_runs
    ADD COLUMN job_type        TEXT        NOT NULL DEFAULT 'unspecified',
    ADD COLUMN scheduled_for   TIMESTAMPTZ,
    ADD COLUMN attempt         INTEGER     NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    ADD COLUMN payloads_stored INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN rows_normalized INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN rows_updated    INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN last_error      TEXT,
    ADD COLUMN duration_ms     INTEGER GENERATED ALWAYS AS (
        CASE WHEN finished_at IS NULL THEN NULL
             ELSE (EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000)::INTEGER END) STORED;

COMMENT ON COLUMN raw.ingestion_runs.rows_written IS
  'Rows INSERTED. Kept under its original name; rows_updated is separate so an
   idempotent rerun that inserts nothing is visibly different from a failed one.';
COMMENT ON COLUMN raw.ingestion_runs.scheduled_for IS
  'The instant the scheduler intended. started_at is when it actually began;
   the gap between the two is scheduler lag and is worth watching.';
COMMENT ON COLUMN raw.ingestion_runs.attempt IS
  '1 for a first run, n for the n-th retry of the same scheduled_for/job_type.';

CREATE INDEX ON raw.ingestion_runs (job_type, scheduled_for DESC);
CREATE INDEX ON raw.ingestion_runs (started_at DESC);
"""

DOWNGRADE = """
ALTER TABLE raw.ingestion_runs
    DROP COLUMN IF EXISTS duration_ms,
    DROP COLUMN IF EXISTS last_error,
    DROP COLUMN IF EXISTS rows_updated,
    DROP COLUMN IF EXISTS rows_normalized,
    DROP COLUMN IF EXISTS payloads_stored,
    DROP COLUMN IF EXISTS attempt,
    DROP COLUMN IF EXISTS scheduled_for,
    DROP COLUMN IF EXISTS job_type;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
