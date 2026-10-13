"""Migration 0076 on a live database.

Regression (13 Oct 2026): its first production run waited minutes for ``ai.budget_alerts`` behind the worker's
notifier (a long transaction that had read the table) while it already held the foreign-key locks on ``core.fixtures``
and ``picks.picks`` - and the worker's writes queued behind the migration. Now the one ACCESS EXCLUSIVE lock is taken
first and a wait longer than 10 s fails the migration whole: nothing else is locked meanwhile, nothing is left half
done, and the deploy retries or stops with nothing changed.
"""

from __future__ import annotations

import os
import threading
import time

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0076"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def test_0076_never_waits_for_a_lock_while_holding_others(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0075")
        holder = psycopg.connect(dsn)  # the notifier: a long transaction that has read ai.budget_alerts
        holder.execute("LOCK TABLE ai.budget_alerts IN ACCESS SHARE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                command.upgrade(_cfg(), "0076")
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate)
        worker.start()
        time.sleep(2)  # the migration now waits for its first lock
        with psycopg.connect(dsn) as writer:  # the worker's writes go on meanwhile
            writer.execute("SET lock_timeout = '2s'")
            writer.execute("LOCK TABLE core.fixtures IN ROW EXCLUSIVE MODE")
            writer.execute("LOCK TABLE picks.picks IN ROW EXCLUSIVE MODE")
            writer.execute("LOCK TABLE market.markets IN ROW EXCLUSIVE MODE")
            writer.rollback()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and "lock timeout" in str(failure[0]).lower(), failure
        assert time.monotonic() - started < 30
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0075",)
            assert c.execute("SELECT to_regnamespace('intel')").fetchone() == (None,), "nothing half done"
        command.upgrade(_cfg(), "0076")  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0076",)
            assert c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'intel'").fetchone() == (12,)
            c.execute("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd) "
                      "VALUES ('2032-10-01', 50, now(), 90, 180)")  # the 50 % alert is accepted
            c.rollback()
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
