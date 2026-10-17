"""persistent daily quota, and 'partial' as a first-class run outcome

Two operational guards that the pilot exposed.

1. The daily budget lived in process memory, so every CLI invocation started
   again from zero. Two shells could each spend the whole budget. The counter
   now lives in the database, keyed by day, and is incremented in ONE atomic
   statement whose WHERE clause carries the budget - so a second process that
   would push the total over the line gets no row back and refuses instead.
   It is deliberately separate from raw.ingestion_runs.api_calls: a run
   records its calls when it closes, which is too late to stop a concurrent
   run, and a crashed run never records them at all. The two are reconciled
   and any drift is reported by /health rather than hidden.

2. raw.ingestion_runs had no way to say "some of it worked". A fixtures sync
   with 7 refusals out of 9 requests that still imported 9 fixtures was
   recorded as 'completed', which reads as if nothing had gone wrong.
   'partial' now sits between completed and failed.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE raw.provider_quota (
    provider    TEXT        NOT NULL,
    quota_date  DATE        NOT NULL,
    spent       INTEGER     NOT NULL DEFAULT 0 CHECK (spent >= 0),
    budget      INTEGER     NOT NULL CHECK (budget >= 1),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, quota_date)
);

COMMENT ON TABLE raw.provider_quota IS
  'OUR daily request budget, not the provider''s limit. One row per provider
   per UTC day. Incremented before a request is issued, in a single statement
   that refuses when the increment would exceed budget - which is what makes
   the cap hold across separate processes and CLI invocations.';
COMMENT ON COLUMN raw.provider_quota.spent IS
  'Requests ISSUED today, including ones the provider refused: the request
   left the building, and a budget that under-counts what it sent is a budget
   that gets overspent. Seeded from raw.ingestion_runs when the day''s first
   request creates the row, so history already in the ledger is respected.';
COMMENT ON COLUMN raw.provider_quota.budget IS
  'The cap in force at the last spend. Stored so the row explains itself
   later, when the configured budget may have changed.';

-- 'partial': the run did something durable AND something went wrong. Without
-- it, an operator reading 'completed' has no reason to look at errors.
ALTER TABLE raw.ingestion_runs DROP CONSTRAINT IF EXISTS ingestion_runs_status_check;
ALTER TABLE raw.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check
    CHECK (status IN ('running','completed','partial','failed','aborted'));

COMMENT ON COLUMN raw.ingestion_runs.status IS
  'running  - open, not yet closed.
   completed- finished with zero errors.
   partial  - finished with errors, but rows or payloads were durably written.
   failed   - finished with errors and nothing to show for it.
   aborted  - stopped deliberately (a request cap or the budget), not broken.';

-- The partial-index on "anything not completed" now has one more state to
-- catch, and it is the state an operator most wants to find.
DROP INDEX IF EXISTS raw.ingestion_runs_status_idx;
CREATE INDEX ingestion_runs_unhealthy_idx ON raw.ingestion_runs (status, started_at DESC)
    WHERE status <> 'completed';
"""

DOWNGRADE = """
DROP INDEX IF EXISTS raw.ingestion_runs_unhealthy_idx;
CREATE INDEX ingestion_runs_status_idx ON raw.ingestion_runs (status) WHERE status <> 'completed';

-- A row can only go back to a state the old constraint allowed. 'partial' is
-- closer to failed than to completed: errors happened.
UPDATE raw.ingestion_runs SET status = 'failed' WHERE status = 'partial';

ALTER TABLE raw.ingestion_runs DROP CONSTRAINT IF EXISTS ingestion_runs_status_check;
ALTER TABLE raw.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check
    CHECK (status IN ('running','completed','failed','aborted'));

DROP TABLE IF EXISTS raw.provider_quota;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
