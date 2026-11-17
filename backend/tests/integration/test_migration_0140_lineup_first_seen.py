"""Migration 0140 (IA-069, plan piece AD-D05): ``core.fixture_lineups.first_seen_at`` written once and never rewritten, and the
append-only ``core.fixture_lineup_arrivals`` - and nothing else. A line-up stored before the migration keeps NULL (its first
sighting is unknown, never guessed) and keeps it through later reads; going back drops both. Run on a scratch database at
revision 0137, the way production does."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0140"
T0 = datetime(2026, 11, 16, 18, 0, tzinfo=UTC)
NEW = {("core", "fixture_lineups", "first_seen_at")}


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', "
                     "'intel', 'picks', 'raw', 'audit', 'customer') ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if (r[0], r[1], r[2]) not in NEW and (r[0], r[1]) != ("core", "fixture_lineup_arrivals")]


def _payload(c: psycopg.Connection[Any], run: int, h: str, at: datetime) -> None:
    c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, bytes) "
              "VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1)", (h, run, at, h))


def _upsert(c: psycopg.Connection[Any], fixture: int, side: str, h: str, at: datetime, formation: str) -> int:
    """The detail writer's own statement (``fbi.ingestion.details``), newest wins."""
    cur = c.execute(
        "INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, provider_coach_id, coach_name, "
        "payload_hash, fetched_at) VALUES (%s,%s,'api-football',%s,NULL,'C',%s,%s) "
        "ON CONFLICT (fixture_id, team_side, source) DO UPDATE SET formation = EXCLUDED.formation, "
        "provider_coach_id = EXCLUDED.provider_coach_id, coach_name = EXCLUDED.coach_name, "
        "payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at "
        "WHERE core.fixture_lineups.fetched_at <= EXCLUDED.fetched_at", (fixture, side, formation, h, at))
    return cur.rowcount


def _lineup(c: psycopg.Connection[Any], fixture: int, side: str) -> tuple[Any, ...] | None:
    return c.execute("SELECT formation, fetched_at, first_seen_at FROM core.fixture_lineups WHERE fixture_id = %s AND "
                     "team_side = %s", (fixture, side)).fetchone()


def test_0140_keeps_the_first_sighting_refuses_to_edit_arrivals_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0139")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (140, 'M0140', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
            assert comp
            season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) "
                               "RETURNING id", (comp[0],)).fetchone()
            teams = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (14001, 'H'), (14002, 'A') "
                              "RETURNING id").fetchall()
            assert season and len(teams) == 2
            fixture = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                                "away_team_id, kickoff_at) VALUES (140001, %s, %s, %s, %s) RETURNING id",
                                (season[0], teams[0][0], teams[1][0], T0 + timedelta(hours=1))).fetchone()
            run = c.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) VALUES "
                            "('m0140', 'm0140', 'completed', now()) RETURNING id").fetchone()
            assert fixture and run
            f, r = int(fixture[0]), int(run[0])
            _payload(c, r, "m0140-old", T0 - timedelta(minutes=50))
            assert _upsert(c, f, "home", "m0140-old", T0 - timedelta(minutes=50), "4-4-2") == 1
        command.upgrade(_cfg(), "0140")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            assert _lineup(c, f, "home") == ("4-4-2", T0 - timedelta(minutes=50), None), "unknown, not guessed"
            for h, minutes in (("m0140-1", 40), ("m0140-2", 30), ("m0140-3", 10)):
                _payload(c, r, h, T0 - timedelta(minutes=minutes))
            # the old row, read again: it stays NULL
            assert _upsert(c, f, "home", "m0140-2", T0 - timedelta(minutes=30), "4-3-3") == 1
            assert _lineup(c, f, "home") == ("4-3-3", T0 - timedelta(minutes=30), None)
            # a new side: first_seen_at is its own fetch instant, and a second read does not move it
            assert _upsert(c, f, "away", "m0140-1", T0 - timedelta(minutes=40), "5-3-2") == 1
            assert _lineup(c, f, "away") == ("5-3-2", T0 - timedelta(minutes=40), T0 - timedelta(minutes=40))
            assert _upsert(c, f, "away", "m0140-3", T0 - timedelta(minutes=10), "5-4-1") == 1
            assert _lineup(c, f, "away") == ("5-4-1", T0 - timedelta(minutes=10), T0 - timedelta(minutes=40))
            c.execute("UPDATE core.fixture_lineups SET first_seen_at = %s WHERE fixture_id = %s", (T0, f))
            assert _lineup(c, f, "away") == ("5-4-1", T0 - timedelta(minutes=10), T0 - timedelta(minutes=40))
            assert _lineup(c, f, "home") == ("4-3-3", T0 - timedelta(minutes=30), None), "not even by hand"

            c.execute("INSERT INTO core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at, kickoff_at, "
                      "content_hash, starters_hash, starters, players, formation, channel, payload_hash) VALUES "
                      "(%s, 'away', 'api-football', %s, %s, %s, %s, 11, 18, '5-3-2', 'detail_writer', 'm0140-1')",
                      (f, T0 - timedelta(minutes=40), T0 + timedelta(hours=1), "a" * 64, "b" * 64))
            for sql in ("UPDATE core.fixture_lineup_arrivals SET starters = 10", "DELETE FROM core.fixture_lineup_arrivals"):
                with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                    c.execute(sql)
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at, kickoff_at, "
                          "content_hash, starters_hash, starters, players, channel, payload_hash) VALUES "
                          "(%s, 'away', 'api-football', now(), now(), 'x', 'y', 11, 18, 'someone', 'h')", (f,))
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at, kickoff_at, "
                          "content_hash, starters_hash, starters, players, channel, payload_hash) VALUES "
                          "(%s, 'away', 'api-football', %s, now(), %s, %s, 11, 18, 'lineup_watch', 'h')",
                          (f, T0 - timedelta(minutes=40), "a" * 64, "c" * 64))
        command.downgrade(_cfg(), "0139")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT formation FROM core.fixture_lineups WHERE fixture_id = %s ORDER BY team_side",
                             (f,)).fetchall() == [("5-4-1",), ("4-3-3",)]
            assert c.execute("SELECT to_regclass('core.fixture_lineup_arrivals')").fetchone() == (None,)
            assert c.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('keep_lineup_first_seen', "
                             "'refuse_arrival_change')").fetchone() == (0,)
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
