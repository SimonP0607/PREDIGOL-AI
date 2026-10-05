"""run watchdog: every run names its process, beats while it works and has a deadline; 'stale' exists

On 5 Oct 2026 the System page said DEGRADED: three runs had been 'running' for 11 to 20 hours - two odds
captures open when the worker was restarted for a deploy, and a RAW replay killed by hand. The boot-time
reaper (0040) only closes runs older than the machine's boot, and none of them was.

Every run now records its OWNER - host, pid and the process's start time, so a reused pid is not mistaken
for the original process - a HEARTBEAT (each payload the run indexes, and an explicit beat in long loops),
and a DEADLINE (its job's timeout). The watchdog (``fbi.ops.run_watchdog``), at worker start and every five
minutes, closes:

* a run whose owner process is gone ............................ 'interrupted' (recovered);
* a worker job's run older than the current worker process ...... 'interrupted' (the worker lock means the
  previous worker is gone);
* a run past its deadline ...................................... 'stale' - flagged and alerted; if the job
  closes later, its real outcome replaces 'stale';
* a legacy run with no owner, open for over 12 hours ............ 'stale'.

Only status, finished_at and a reason in last_error change; what the run wrote stays.

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE raw.ingestion_runs
            ADD COLUMN IF NOT EXISTS owner_host    TEXT,
            ADD COLUMN IF NOT EXISTS owner_pid     INTEGER,
            ADD COLUMN IF NOT EXISTS owner_started BIGINT,
            ADD COLUMN IF NOT EXISTS heartbeat_at  TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS deadline_at   TIMESTAMPTZ;
        ALTER TABLE raw.ingestion_runs DROP CONSTRAINT ingestion_runs_status_check;
        ALTER TABLE raw.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check
            CHECK (status IN ('running', 'completed', 'partial', 'failed', 'aborted', 'interrupted', 'stale'));
        CREATE INDEX IF NOT EXISTS ingestion_runs_open ON raw.ingestion_runs (started_at) WHERE status = 'running';
        COMMENT ON COLUMN raw.ingestion_runs.owner_host IS
            'Host of the process that opened the run (fbi.ops.run_watchdog.process_identity).';
        COMMENT ON COLUMN raw.ingestion_runs.owner_pid IS 'PID of the process that opened the run.';
        COMMENT ON COLUMN raw.ingestion_runs.owner_started IS
            'Start time of that process in clock ticks since boot (/proc/<pid>/stat field 22): a reused pid differs.';
        COMMENT ON COLUMN raw.ingestion_runs.heartbeat_at IS 'Last sign of life of the run (a payload indexed, a beat).';
        COMMENT ON COLUMN raw.ingestion_runs.deadline_at IS
            'started_at + the job''s timeout: past it, the watchdog marks a still-running run stale.';
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.provider_minute_usage (
            provider TEXT        NOT NULL,
            minute   TIMESTAMPTZ NOT NULL,
            spent    INTEGER     NOT NULL CHECK (spent >= 0),
            PRIMARY KEY (provider, minute)
        )""")
    op.execute("COMMENT ON TABLE raw.provider_minute_usage IS "
               "'Requests issued per provider per minute, shared by every process: the per-minute limit "
               "(fbi.providers.quota.PersistentMinuteLimiter) holds across the worker''s jobs and CLI scripts.'")


def downgrade() -> None:
    op.execute("""
        UPDATE raw.ingestion_runs SET status = 'interrupted' WHERE status = 'stale';
        ALTER TABLE raw.ingestion_runs DROP CONSTRAINT ingestion_runs_status_check;
        ALTER TABLE raw.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check
            CHECK (status IN ('running', 'completed', 'partial', 'failed', 'aborted', 'interrupted'));
        DROP INDEX IF EXISTS raw.ingestion_runs_open;
        ALTER TABLE raw.ingestion_runs
            DROP COLUMN IF EXISTS owner_host, DROP COLUMN IF EXISTS owner_pid, DROP COLUMN IF EXISTS owner_started,
            DROP COLUMN IF EXISTS heartbeat_at, DROP COLUMN IF EXISTS deadline_at;
        DROP TABLE IF EXISTS raw.provider_minute_usage;
    """)
