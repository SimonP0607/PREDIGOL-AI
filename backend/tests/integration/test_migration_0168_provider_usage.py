"""Migration 0168 (PM-01-02) on a scratch database at the revision below it: the three tables appear, take what the code writes, refuse what
they must, and the downgrade refuses while a measure exists - it never deletes one - and goes back clean when they are empty."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0168"
BELOW = "0167"
TABLES = ("raw.provider_endpoint_usage", "raw.provider_minute_daily", "audit.db_size_history")


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                      (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@contextmanager
def scratch() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def exists(conn: psycopg.Connection, table: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()
    return bool(row and row[0])


def test_0168_adds_the_tables_keeps_every_measure_and_goes_back_clean_when_empty() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not any(exists(c, t) for t in TABLES)
        command.upgrade(_cfg(), "0168")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert all(exists(c, t) for t in TABLES)
            c.execute("INSERT INTO raw.provider_endpoint_usage (provider, usage_date, endpoint, lane, job, requests) "
                      "VALUES ('api_football', '2026-11-20', '/fixtures', 'calendario', 'fixtures_sync', 3)")
            # the same key again is the one row the counter adds to
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO raw.provider_endpoint_usage (provider, usage_date, endpoint, lane, job, requests) "
                          "VALUES ('api_football', '2026-11-20', '/fixtures', 'calendario', 'fixtures_sync', 1)")
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO raw.provider_endpoint_usage (provider, usage_date, endpoint, lane, job, requests) "
                          "VALUES ('api_football', '2026-11-20', '/odds', 'cuotas', 'odds_capture', -1)")
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO raw.provider_minute_daily (provider, usage_date, minutes_active, requests, max_per_minute) "
                          "VALUES ('api_football', '2026-11-20', 1441, 1, 1)")
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO audit.db_size_history (measured_at, database_name, db_bytes, schema_bytes) "
                          "VALUES (now(), 'fbi', 1, '[]')")
            c.execute("INSERT INTO audit.db_size_history (measured_at, database_name, db_bytes) VALUES (now(), 'fbi', 36330000000)")
            row = c.execute("SELECT schema_bytes, top_tables, source FROM audit.db_size_history").fetchone()
            assert row == ({}, [], "storage-report")
        # a measure exists: the downgrade refuses and every table stays
        with pytest.raises(Exception, match="0168 downgrade refused"):
            command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert all(exists(c, t) for t in TABLES)
            assert c.execute("SELECT count(*) FROM raw.provider_endpoint_usage").fetchone() == (1,)
            c.execute("DELETE FROM raw.provider_endpoint_usage")
            c.execute("DELETE FROM audit.db_size_history")
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not any(exists(c, t) for t in TABLES)
        command.upgrade(_cfg(), "0168")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert all(exists(c, t) for t in TABLES)
