"""worker heartbeat: liveness that does not depend on there being work to do

/health derived the worker's state from the job ledger alone. The ledger only
records ticks that DID something, and on a quiet day - no fixture inside a
capture window - the scheduler runs every 15 minutes and writes nothing. So a
perfectly healthy worker was reported as "last run 400 min ago", and a dead one
looked exactly the same. The two cases must be distinguishable, because the
second one loses odds windows that can never be recovered.

One row per worker process. The worker upserts it on start and on every tick,
whether or not the tick had work. It also records the scheduler lag - the gap
between when a tick was due and when it ran - which is the first number to
look at when a window is missed.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE raw.worker_heartbeats (
    worker_id              TEXT        PRIMARY KEY,
    hostname               TEXT        NOT NULL,
    pid                    INTEGER     NOT NULL,
    code_version           TEXT        NOT NULL,
    started_at             TIMESTAMPTZ NOT NULL,
    last_beat_at           TIMESTAMPTZ NOT NULL,
    last_tick_at           TIMESTAMPTZ,
    last_tick_outcome      TEXT,
    last_tick_duration_ms  INTEGER     CHECK (last_tick_duration_ms IS NULL OR last_tick_duration_ms >= 0),
    scheduler_lag_ms       INTEGER,
    ticks                  BIGINT      NOT NULL DEFAULT 0 CHECK (ticks >= 0),
    tick_interval_s        INTEGER     NOT NULL CHECK (tick_interval_s > 0),
    jobs                   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    stopped_at             TIMESTAMPTZ,
    CONSTRAINT worker_heartbeats_outcome_check CHECK (
        last_tick_outcome IS NULL OR last_tick_outcome IN
        ('nothing_scheduled','nothing_due','captured','plan_rejected','failed'))
);

CREATE INDEX worker_heartbeats_last_beat_idx ON raw.worker_heartbeats (last_beat_at DESC);

COMMENT ON TABLE raw.worker_heartbeats IS
  'Liveness of each worker process, written on every tick whether or not it had
   work. The job ledger says what the worker DID; this says whether it is ALIVE.
   A quiet worker and a dead one look identical in the ledger and different here.';
COMMENT ON COLUMN raw.worker_heartbeats.scheduler_lag_ms IS
  'How late the last tick ran relative to when it was scheduled. A large value
   means the process is starved or was suspended (laptop sleep), and is the first
   thing to check when a capture window is missed.';
COMMENT ON COLUMN raw.worker_heartbeats.jobs IS
  'Next scheduled run of each job, as the scheduler itself reports it.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS raw.worker_heartbeats;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
