"""Requests by endpoint and lane, the daily summary of the per-minute peaks and the history of the database's size (plan PM, PM-01-02)

WHY THIS EXISTS
---------------
Measured on 19 Nov 2026 (plan PM, note 02): ``raw.provider_quota`` counts OUR requests per day and ``raw.ingestion_runs`` per job,
but nothing counts them per endpoint - the nearest thing, ``raw.ingestion_payloads``, holds one row per DISTINCT answer, 20 to 45 %
of the requests of a day. ``raw.provider_minute_usage`` keeps the per-minute counter only 48 hours (the limiter prunes it), so the
peaks of last week are gone. And no table keeps the size of the database: only a line a day in a file of the storage report. The
lanes of the quota (PM-04-01) and the console (PM-04-05) need the three, measured BEFORE anything changes.

raw.provider_endpoint_usage
---------------------------
One row per provider, UTC day, endpoint, lane and job: how many requests left for that endpoint (every attempt, retries included,
counted where ``raw.provider_quota`` is spent - so the day's sum must match it). The client keeps the counts in memory and adds
them here in one statement at most once a minute (``fbi.providers.quota.EndpointUsageCounter``): no write per request. ``lane`` is
the lane of the quota the job belongs to; until PM-04-01 creates the lanes it is a provisional one derived from the job, or
``sin_carril``. ``job`` is the ``job_type`` of the ledger run that asked (``sin_trabajo`` for a call with no run, ``/status``).
A few dozen rows a day.

raw.provider_minute_daily
-------------------------
One row per provider and UTC day: the minutes with requests, their sum, the busiest minute and the percentiles 50/95/99 of the
requests per minute (over the minutes that had any), written by the limiter's hourly prune before it deletes what is older than
48 hours. ``complete`` says the day was over when it was computed.

audit.db_size_history
---------------------
One row per measure of the storage report (``deploy/vps/bin/storage-report.sh``, four times a day): ``pg_database_size``, the bytes
of each schema and the twelve largest tables. Written by the owner's role only; the API reads it (the console, PM-04-05).

Additive only: three new tables, no change to an existing one, no lock on a busy table. Privileges: ``deploy/vps/db/grants.sql``,
run by the release after every migration - the worker writes the two ``raw`` tables, nobody but the owner writes
``audit.db_size_history``, the API reads the three. Downgrade drops them only while they are empty: it never deletes a measure.

Revision ID: 0168
Revises: 0167
"""

from __future__ import annotations

from alembic import op

revision = "0168"
down_revision = "0167"
branch_labels = None
depends_on = None

TABLES = ("raw.provider_endpoint_usage", "raw.provider_minute_daily", "audit.db_size_history")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE raw.provider_endpoint_usage (
            provider    TEXT         NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 40),
            usage_date  DATE         NOT NULL,
            endpoint    TEXT         NOT NULL CHECK (char_length(endpoint) BETWEEN 1 AND 64),
            lane        TEXT         NOT NULL CHECK (char_length(lane) BETWEEN 1 AND 40),
            job         TEXT         NOT NULL CHECK (char_length(job) BETWEEN 1 AND 64),
            requests    BIGINT       NOT NULL CHECK (requests >= 0),
            first_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, usage_date, endpoint, lane, job)
        );
        COMMENT ON TABLE raw.provider_endpoint_usage IS
          'PM-01-02: requests per UTC day, endpoint, lane and job, counted where raw.provider_quota is spent (every attempt) and '
          'added at most once a minute per process (fbi.providers.quota.EndpointUsageCounter). lane: provisional, derived from the '
          'job until PM-04-01 (sin_carril when unknown); job: the ledger run''s job_type (sin_trabajo without a run).';

        CREATE TABLE raw.provider_minute_daily (
            provider        TEXT          NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 40),
            usage_date      DATE          NOT NULL,
            minutes_active  INTEGER       NOT NULL CHECK (minutes_active BETWEEN 0 AND 1440),
            requests        BIGINT        NOT NULL CHECK (requests >= 0),
            max_per_minute  INTEGER       NOT NULL CHECK (max_per_minute >= 0),
            peak_minute     TIMESTAMPTZ,
            p50             NUMERIC(8,1),
            p95             NUMERIC(8,1),
            p99             NUMERIC(8,1),
            complete        BOOLEAN       NOT NULL DEFAULT false,
            computed_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, usage_date)
        );
        COMMENT ON TABLE raw.provider_minute_daily IS
          'PM-01-02: the day of raw.provider_minute_usage (kept 48 h) summarised before it is pruned - minutes with requests, their '
          'sum, the busiest minute and the percentiles 50/95/99 of requests per active minute. complete: the day was over.';

        CREATE TABLE audit.db_size_history (
            measured_at    TIMESTAMPTZ  NOT NULL PRIMARY KEY,
            database_name  TEXT         NOT NULL,
            db_bytes       BIGINT       NOT NULL CHECK (db_bytes >= 0),
            schema_bytes   JSONB        NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(schema_bytes) = 'object'),
            top_tables     JSONB        NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(top_tables) = 'array'),
            source         TEXT         NOT NULL DEFAULT 'storage-report' CHECK (char_length(source) BETWEEN 1 AND 40)
        );
        COMMENT ON TABLE audit.db_size_history IS
          'PM-01-02: the size of the database at each measure of the storage report (deploy/vps/bin/storage-report.sh): '
          'pg_database_size, bytes per schema, the twelve largest tables. Written by the owner only; read by the console.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a measure: the history cannot be measured again. Empty tables (a test database, a deploy rolled back the same
    # minute) are dropped; anything else stops the downgrade and says which table.
    checks = "\n".join(
        # nested: PL/pgSQL plans the inner query only when it runs, so a table already gone is no error
        f"  IF to_regclass('{t}') IS NOT NULL THEN\n"
        f"    IF EXISTS (SELECT 1 FROM {t}) THEN\n"
        f"      RAISE EXCEPTION '0168 downgrade refused: {t} holds measures (PM-01-02); they are never deleted';\n"
        f"    END IF;\n"
        f"  END IF;"
        for t in TABLES
    )
    op.execute(f"DO $refuse$\nBEGIN\n{checks}\nEND\n$refuse$")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
