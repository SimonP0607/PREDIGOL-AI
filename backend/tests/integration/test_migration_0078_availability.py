"""Migration 0078 (``core.player_availability_obs``) over a database that already holds absences.

The new table is a history that can only be written forward, so the migration seeds it with the one thing the old table can
still say truthfully: that the provider listed each (match, player) at the ``fetched_at`` its row carries. It must copy,
never move: ``core.player_absences`` stays exactly as it was (the Match Center and the audits read it), and the downgrade
drops only the new table. Run on a scratch database at revision 0077 with rows in place, the way production is."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0078"
FETCHED = datetime(2026, 10, 12, 8, 30, tzinfo=UTC)


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _legacy_rows(c: psycopg.Connection) -> list[tuple[object, ...]]:
    return c.execute("SELECT source, provider_fixture_id, provider_player_id, fixture_id, provider_team_id, "
                     "player_name, absence_type, reason, payload_hash, fetched_at FROM core.player_absences "
                     "ORDER BY provider_fixture_id, provider_player_id").fetchall()


def test_0078_copies_the_absences_it_can_place_and_leaves_the_old_table_alone(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0077")
        with psycopg.connect(dsn) as c:
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                             "competition_type) VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') "
                             "RETURNING id").fetchone()
            assert comp is not None
            season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) "
                               "RETURNING id", (comp[0],)).fetchone()
            assert season is not None
            teams = [c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                               (33 + i, f"Team {i}")).fetchone() for i in range(2)]
            fixture = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                                "away_team_id, kickoff_at) VALUES (1001, %s, %s, %s, '2026-10-17 15:00Z') RETURNING id",
                                (season[0], teams[0][0], teams[1][0])).fetchone()  # type: ignore[index]
            assert fixture is not None
            run = c.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                            "VALUES ('t', 'context_refresh', 'completed', now()) RETURNING id").fetchone()
            assert run is not None
            c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                      "bytes) VALUES ('inj-1', %s, '/injuries', %s, 200, 'x', 1)", (run[0], FETCHED))
            for pf, player, name, kind, reason, fid in (
                    (1001, 9001, "Player A", "Missing Fixture", "Knee Injury", fixture[0]),
                    (1001, 9002, "Player B", "Questionable", None, fixture[0]),
                    (1002, 9003, "Player C", "Missing Fixture", "Suspended", None)):  # a match we do not hold
                c.execute("INSERT INTO core.player_absences (source, provider_fixture_id, provider_player_id, fixture_id, "
                          "provider_team_id, player_name, absence_type, reason, payload_hash, fetched_at) "
                          "VALUES ('api-football', %s, %s, %s, 33, %s, %s, %s, 'inj-1', %s)",
                          (pf, player, fid, name, kind, reason, FETCHED))
            c.commit()
            before = _legacy_rows(c)
        assert len(before) == 3

        command.upgrade(_cfg(), "0078")
        with psycopg.connect(dsn) as c:
            seeded = c.execute("SELECT provider_player_id, observed_at, status, absence_type, reason, payload_hash, origin, "
                               "normalizer_version, provider_fixture_id FROM core.player_availability_obs "
                               "ORDER BY provider_player_id").fetchall()
            assert seeded == [
                (9001, FETCHED, "LISTED", "Missing Fixture", "Knee Injury", "inj-1", "snapshot", "availability-v1", 1001),
                (9002, FETCHED, "LISTED", "Questionable", None, "inj-1", "snapshot", "availability-v1", 1001),
            ], "what the old table says, at the time it says it; the row with no match is not copied"
            assert _legacy_rows(c) == before, "the old table is untouched"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0078",)

        command.downgrade(_cfg(), "0077")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT to_regclass('core.player_availability_obs')").fetchone() == (None,)
            assert _legacy_rows(c) == before, "downgrading drops the copy; the source is intact"

        command.upgrade(_cfg(), "0078")  # and applies again, whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM core.player_availability_obs").fetchone() == (2,)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
