"""Migration 0147 (IA-082): ``intel.scenario_readings`` - added on top of the revision below and nothing else changes; a season is read
as it was known (a result recorded after the moment is not counted, a fixture created after it is not on the calendar), a reading is
written once per set of inputs, the table refuses UPDATE and DELETE, and going back drops it. Run on a scratch database at the revision
below it, the way production does."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fbi.competitions import scenario_store as store
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0147"
BELOW = "0146"
AT = datetime(2026, 2, 1, 12, tzinfo=UTC)
TEAMS = list(range(9201, 9221))


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                      (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default FROM "
                     "information_schema.columns WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', 'intel', "
                     "'picks', 'raw', 'audit', 'customer', 'analytics') ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "intel" and r[1] == "scenario_readings")]


def _seed(c: psycopg.Connection[Any]) -> None:
    """The Premier League 2025 with 20 clubs: round 1 played (one result recorded only after AT), round 2 to play, and one fixture
    created after AT."""
    c.execute("INSERT INTO core.competitions (id, provider_league_id, name, country, type, entity_scope, competition_type) "
              "VALUES (9001, 39, 'Premier League', 'England', 'league', 'club', 'domestic_league')")
    c.execute("INSERT INTO core.competition_seasons (id, competition_id, season) VALUES (9101, 9001, 2025)")
    for t in TEAMS:
        c.execute("INSERT INTO core.teams (id, provider_team_id, name) VALUES (%s, %s, %s)", (t, t, f"Club {t}"))
    made = AT - timedelta(days=60)
    n = 0
    for rnd, offset in ((1, -7), (2, 7)):
        for i in range(10):
            n += 1
            h, a = (TEAMS[i], TEAMS[19 - i]) if rnd == 1 else (TEAMS[19 - i], TEAMS[(i + 1) % 10])
            c.execute("INSERT INTO core.fixtures (id, provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                      "round, status_short, status_group, created_at) VALUES (%s, %s, 9101, %s, %s, %s, %s, %s, %s, %s)",
                      (9300 + n, 9300 + n, h, a, AT + timedelta(days=offset), f"Regular Season - {rnd}", "FT" if rnd == 1 else "NS",
                       "finished" if rnd == 1 else "scheduled", made if n != 20 else AT + timedelta(days=1)))
            if rnd == 1:
                settled = AT - timedelta(days=6) if i else AT + timedelta(hours=1)  # the first result was recorded after AT
                c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 2, 0, %s)",
                          (9300 + n, settled))


def test_0147_reads_as_of_writes_once_append_only_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
        command.upgrade(_cfg(), "0147")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            _seed(c)
            c.commit()
            reading = store.read_season(c, 39, 2025, at=AT, simulate=False)
            assert reading is not None and reading["status"] == "ok"
            [table] = reading["tables"]
            assert table["key"] == "season.league"
            assert (table["played"], table["pending"]) == (9, 10), "the late result is still to play; the late fixture is not there"
            # 38 matches a club and two on the calendar (one for the two clubs of the fixture created later): the rest are phantoms
            assert table["phantom"] == {str(t): 37 if t in (TEAMS[0], TEAMS[10]) else 36 for t in TEAMS}
            first = store.write(c, reading, code_version="test")
            again = store.write(c, reading, code_version="test")
            c.commit()
            assert first is not None and again is None, "the same inputs are written once"
            later = store.read_season(c, 39, 2025, at=AT + timedelta(days=2), simulate=False)
            assert later is not None and later["tables"][0]["played"] == 10
            assert store.write(c, later, code_version="test") is not None
            c.commit()
            rows = c.execute("SELECT status, engine_version, rules_version, sims, contradictions, reading->>'version' "
                             "FROM intel.scenario_readings ORDER BY id").fetchall()
            assert rows == [("ok", "scenarios-v2", 1, 0, 0, "scenarios-v2")] * 2
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("UPDATE intel.scenario_readings SET contradictions = 1")
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("DELETE FROM intel.scenario_readings")
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):  # a coded reading names its rules
                c.execute("INSERT INTO intel.scenario_readings (computed_at, league_id, season, competition_season_id, status, "
                          "engine_version, sims, seed, input_hash, reading) VALUES (now(), 39, 2025, 9101, 'ok', 'scenarios-v2', 0, 1, "
                          "repeat('a', 64), '{}')")
            c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            left = c.execute("SELECT to_regclass('intel.scenario_readings')").fetchone()
            assert left == (None,)
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
