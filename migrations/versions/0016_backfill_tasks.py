"""historical backfill: one row per unit of history, so the work can stop and resume

The free plan serves three past seasons through /fixtures?league=&season=,
at one request per competition-season. That is cheap - but it competes with
live odds capture for the same 60 requests a day, and live capture is the one
that cannot be recovered later. So the backfill has to be able to spend a
little, stop, and carry on tomorrow without redoing or losing anything.

Each (provider, kind, league, season) is one task. A task is 'done' once its
payload has been stored and applied; 'refused' when the plan does not serve
it (recorded with the provider's own message, never retried blindly);
'failed' after a transport or parse error, retried on a later run.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE raw.backfill_tasks (
    id                  BIGSERIAL PRIMARY KEY,
    provider            TEXT        NOT NULL DEFAULT 'api_football',
    kind                TEXT        NOT NULL CHECK (kind IN ('fixtures_season')),
    provider_league_id  INTEGER     NOT NULL,
    season              INTEGER     NOT NULL,
    priority            INTEGER     NOT NULL DEFAULT 100,
    status              TEXT        NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','done','refused','failed')),
    attempts            INTEGER     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_run_id         BIGINT      REFERENCES raw.ingestion_runs(id),
    last_payload_hash   TEXT        REFERENCES raw.ingestion_payloads(hash),
    fixtures_seen       INTEGER,
    fixtures_written    INTEGER,
    results_written     INTEGER,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    UNIQUE (provider, kind, provider_league_id, season),
    CONSTRAINT backfill_done_has_payload CHECK (status <> 'done' OR last_payload_hash IS NOT NULL),
    CONSTRAINT backfill_refused_says_why CHECK (status <> 'refused' OR last_error IS NOT NULL)
);

CREATE INDEX backfill_tasks_pending_idx ON raw.backfill_tasks (priority, id) WHERE status IN ('pending','failed');

COMMENT ON TABLE raw.backfill_tasks IS
  'Units of historical ingestion. Resumable: a run takes pending tasks in
   priority order until its request allowance is spent, and the next run
   carries on. Idempotent: applying a task twice rewrites the same rows.';
COMMENT ON COLUMN raw.backfill_tasks.status IS
  'pending - not yet attempted. done - payload stored and applied.
   refused - the provider plan does not serve it (last_error has its message).
   failed - transport or parse error; retried by a later run.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS raw.backfill_tasks;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
