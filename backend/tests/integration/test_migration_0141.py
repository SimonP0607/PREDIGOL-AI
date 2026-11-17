"""Migration 0141 (AD-H01/H02/H09, IA-071): new tables and views, ``player_id`` on squads and claims - and nothing else. The
old rows keep every value; the backfill gives them the key in batches (creating the squad players that had no row); going back
drops what was added. Run on a scratch database at revision 0137, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fbi.people.identity import store
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0141"
NEW = {("core", "squad_members", "player_id"), ("ai", "evidence", "player_id")}


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
    return [r for r in rows if (r[0], r[1], r[2]) not in NEW and not str(r[1]).startswith("entity_")]


def _seed(c: psycopg.Connection[Any]) -> dict[str, int]:
    comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                     "VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
    assert comp
    season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                       (comp[0],)).fetchone()
    home = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (33, 'Manchester United') RETURNING id"
                     ).fetchone()
    away = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (40, 'Liverpool') RETURNING id").fetchone()
    assert season and home and away
    fixture = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                        "kickoff_at) VALUES (1, %s, %s, %s, '2026-11-20 20:00Z') RETURNING id",
                        (season[0], home[0], away[0])).fetchone()
    player = c.execute("INSERT INTO core.players (provider_player_id, name, position) VALUES (306, 'M. Salah', 'F') "
                       "RETURNING id").fetchone()
    assert fixture and player
    for pid, name in ((306, "M. Salah"), (999_001, "N. Newcomer")):
        c.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, position, first_seen_at, "
                  "last_seen_at, payload_hash) VALUES (%s, %s, %s, 'Attacker', now(), now(), 'h')", (away[0], pid, name))
    c.execute("INSERT INTO ai.evidence (fixture_id, provider_player_id, kind, claim, origin, source_name, source_tier, "
              "retrieved_at, story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at) "
              "VALUES (%s, 306, 'injury', 'M. Salah doubtful for Sunday', 'provider', 'test', 'provider', now(), 's1', "
              "'c1', 0.9, 0.9, 'PROBABLE', 'test', now())", (fixture[0],))
    return {"player": int(player[0])}


def test_0141_adds_identity_and_the_player_key_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0140")
        with psycopg.connect(dsn, autocommit=True) as c:
            ids = _seed(c)
            before = _shape(c)
            claim_before = c.execute("SELECT claim, status, status_history FROM ai.evidence").fetchall()
        command.upgrade(_cfg(), "0141")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core' "
                                              "AND table_name LIKE 'entity_%'").fetchall()}
            assert tables == {"entity_id_loads", "entity_ids", "entity_aliases", "entity_identity_retirements",
                              "entity_identity_queue", "entity_identity_queue_seen", "entity_identity_decisions",
                              "entity_ids_live", "entity_aliases_live", "entity_identity_queue_open"}
            assert c.execute("SELECT count(*) FROM core.squad_members WHERE player_id IS NULL").fetchone() == (2,), \
                "the migration does not rewrite the old rows"
            assert store.player_key_gaps(c) == {"core.squad_members": 2, "ai.evidence": 1}
            c.commit()
            report = store.backfill_player_keys(c, batch=1, create_missing=True)
            assert report.players_created == 1, "the squad player the provider never named in a match"
            assert report.left == {"core.squad_members": 0, "ai.evidence": 0}
            assert c.execute("SELECT player_id FROM ai.evidence").fetchone() == (ids["player"],)
            assert c.execute("SELECT claim, status, status_history FROM ai.evidence").fetchall() == claim_before
            created = c.execute("SELECT name, position, birth_date FROM core.players WHERE provider_player_id = 999001"
                                ).fetchone()
            assert created == ("N. Newcomer", "Attacker", None)
            assert c.execute("SELECT core.position_group('M'), core.position_group('Attacker')").fetchone() == \
                ("midfielder", "forward")
            c.commit()
        command.downgrade(_cfg(), "0140")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' "
                             "AND table_name LIKE 'entity_%'").fetchone() == (0,)
            assert c.execute("SELECT claim, status FROM ai.evidence").fetchall() == [(r[0], r[1]) for r in claim_before]
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
