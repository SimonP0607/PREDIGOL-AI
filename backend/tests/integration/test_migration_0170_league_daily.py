"""Migration 0170 (PM-05-07) on a scratch database at the revision below it: the table of the market's margin and dispersion appears,
takes what the nightly batch writes, refuses what it must, and the downgrade refuses while a measure exists - it never deletes one - and
goes back clean when it is empty."""

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
SCRATCH = f"{TEST_DB}_m0170"
BELOW = "0169"
TABLE = "market.league_daily_stats"


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


def exists(conn: psycopg.Connection) -> bool:
    row = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (TABLE,)).fetchone()
    return bool(row and row[0])


ROW = (f"INSERT INTO {TABLE} (day, competition_id, market_key, line, n_fixtures, n_books, books_median, margin_mean, margin_median, "
       "margin_p10, margin_p90, dispersion_median, dispersion_mean, n_dispersion, source, method_version, measured_at) "
       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'final_prematch', 'league-margin-v1', now())")
GOOD = ("2026-11-15", 7, "1X2", 0, 8, 96, 12, 0.0612, 0.0598, 0.045, 0.081, 0.0121, 0.0133, 8)


def test_0170_adds_the_table_keeps_every_measure_and_goes_back_clean_when_empty() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not exists(c)
        command.upgrade(_cfg(), "0170")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert exists(c)
            c.execute(ROW, GOOD)
            c.execute(ROW, ("2026-11-15", 7, "OU", 2.5, 8, 90, 11, 0.055, 0.054, 0.04, 0.07, None, None, 0))
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(ROW, GOOD)
            with pytest.raises(psycopg.errors.CheckViolation):  # fewer books than matches
                c.execute(ROW, ("2026-11-16", 7, "1X2", 0, 8, 7, 1, 0.06, 0.06, 0.05, 0.07, None, None, 0))
            with pytest.raises(psycopg.errors.CheckViolation):  # a margin of zero is a stale book, never measured
                c.execute(ROW, ("2026-11-16", 7, "1X2", 0, 1, 1, 1, 0, 0, 0, 0, None, None, 0))
            with pytest.raises(psycopg.errors.CheckViolation):  # percentiles out of order
                c.execute(ROW, ("2026-11-16", 7, "1X2", 0, 1, 2, 2, 0.06, 0.06, 0.07, 0.05, None, None, 0))
            with pytest.raises(psycopg.errors.CheckViolation):  # a dispersion with no match to measure it on
                c.execute(ROW, ("2026-11-16", 7, "1X2", 0, 1, 2, 2, 0.06, 0.06, 0.05, 0.07, 0.01, 0.01, 0))
        # a measure exists: the downgrade refuses and the table stays
        with pytest.raises(Exception, match="0170 downgrade refused"):
            command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert exists(c)
            c.execute(f"DELETE FROM {TABLE}")
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not exists(c)
        command.upgrade(_cfg(), "0170")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert exists(c)
