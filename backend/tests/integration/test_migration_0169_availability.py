"""Migration 0169 (PM-02-02) on a scratch database at the revision below it: the four tables of the availability matrix appear, take what
the nightly batch writes, refuse what they must, and the downgrade refuses while a measure exists - it never deletes one - and goes back
clean when they are empty."""

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
SCRATCH = f"{TEST_DB}_m0169"
BELOW = "0168"
TABLES = ("analytics.coverage_cells", "analytics.market_availability", "analytics.coverage_changes",
          "analytics.availability_discrepancies")


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


CELL = ("INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, share, level, "
        "measured_level, rules_version, measured_at) VALUES (%s, 'todas', %s, %s, %s, %s, %s, %s, 'coverage-levels-v1', now())")


def test_0169_adds_the_tables_keeps_every_measure_and_goes_back_clean_when_empty() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not any(exists(c, t) for t in TABLES)
        command.upgrade(_cfg(), "0169")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert all(exists(c, t) for t in TABLES)
            c.execute(CELL, (7, "corners", 120, 119, 0.9917, "A", "A"))
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(CELL, (7, "corners", 121, 120, 0.9917, "A", "A"))
            with pytest.raises(psycopg.errors.CheckViolation):  # more with the datum than finished
                c.execute(CELL, (7, "fouls", 10, 11, 1, "B", "B"))
            with pytest.raises(psycopg.errors.CheckViolation):  # not a level of the rules
                c.execute(CELL, (7, "xg", 10, 1, 0.1, "E", "E"))
            c.execute("INSERT INTO analytics.market_availability (competition_season_id, market_key, window_start, window_days, n_window, "
                      "n_priced, priced_share, median_books, level, measured_level, rules_version, measured_at) "
                      "VALUES (7, '1X2', '2026-10-05', 46, 81, 81, 1, 10, 'A', 'A', 'coverage-levels-v1', now())")
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO analytics.market_availability (competition_season_id, market_key, window_start, window_days, "
                          "n_window, n_priced, level, measured_level, rules_version, measured_at) "
                          "VALUES (7, 'OU', '2026-10-05', 46, 5, 6, 'MI', 'MI', 'coverage-levels-v1', now())")
            row = c.execute("INSERT INTO analytics.coverage_changes (competition_season_id, phase_key, kind, subject, new_level, reason, "
                            "rules_version) VALUES (7, 'todas', 'datum', 'corners', 'A', 'primera_medida', 'coverage-levels-v1') "
                            "RETURNING id").fetchone()
            assert row is not None and row[0] >= 1
            c.execute("INSERT INTO analytics.availability_discrepancies (day, fixture_id, module, subject, shown, matrix, reason, "
                      "observed_at, rules_version) VALUES ('2026-11-21', 1557464, 'mi_parlay', 'corners_over_under.FT.match:9.5', "
                      "true, false, 'sin_cobertura', now(), 'coverage-levels-v1')")
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO analytics.availability_discrepancies (day, fixture_id, module, subject, shown, matrix, reason, "
                          "observed_at, rules_version) VALUES ('2026-11-21', 1557464, 'mi_parlay', 'corners_over_under.FT.match:9.5', "
                          "false, true, 'x', now(), 'coverage-levels-v1')")
        # a measure exists: the downgrade refuses and every table stays
        with pytest.raises(Exception, match="0169 downgrade refused"):
            command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert all(exists(c, t) for t in TABLES)
            for t in TABLES:
                c.execute(f"DELETE FROM {t}")
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not any(exists(c, t) for t in TABLES)
        command.upgrade(_cfg(), "0169")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert all(exists(c, t) for t in TABLES)
