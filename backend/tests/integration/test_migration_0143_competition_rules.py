"""Migration 0143 (IA-072): ``core.competition_rules`` - added on top of the revision below and nothing else changes; the loader
records every version once (idempotent), the table refuses UPDATE and DELETE, and going back drops it. Then the reconstruction
reads a season back from the database. Run on a scratch database at the revision below it, the way production does."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fbi.competitions import reconstruction as rc
from fbi.competitions import rules as rl
from fbi.competitions import rules_store as store
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0143"
BELOW = "0142"


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
                     "'picks', 'raw', 'audit', 'customer') ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "core" and r[1] == "competition_rules")]


def _seed_season(c: psycopg.Connection[Any]) -> None:
    c.execute("INSERT INTO core.competitions (id, provider_league_id, name, country, type, entity_scope, competition_type) "
              "VALUES (9001, 39, 'Premier League', 'England', 'league', 'club', 'domestic_league')")
    c.execute("INSERT INTO core.competition_seasons (id, competition_id, season) VALUES (9101, 9001, 2025)")
    for i, name in ((9201, 'Alpha'), (9202, 'Beta'), (9203, 'Gamma')):
        c.execute("INSERT INTO core.teams (id, provider_team_id, name) VALUES (%s, %s, %s)", (i, i, name))
    games = [(1, 9201, 9202, 2, 0), (2, 9202, 9203, 1, 1), (3, 9203, 9201, 0, 1), (4, 9202, 9201, 0, 0), (5, 9203, 9202, 2, 2),
             (6, 9201, 9203, 3, 3)]
    for n, h, a, gh, ga in games:
        c.execute("INSERT INTO core.fixtures (id, provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                  "round, status_short, status_group) VALUES (%s, %s, 9101, %s, %s, %s, %s, 'FT', 'finished')",
                  (9300 + n, 9300 + n, h, a, datetime(2026, 1, n, tzinfo=UTC), f"Regular Season - {n}"))
        c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)", (9300 + n, gh, ga))
    at = datetime(2026, 2, 1, tzinfo=UTC)
    for rank_, team, pts, gf, ga in ((1, 9201, 8, 6, 3), (2, 9203, 3, 6, 7), (3, 9202, 3, 3, 5)):
        c.execute("INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, wins, draws, "
                  "losses, goals_for, goals_against, \"group\") VALUES (9101, %s, %s, %s, %s, 4, 0, 0, 0, %s, %s, 'Premier League')",
                  (team, at, rank_, pts, gf, ga))


def test_0143_records_versions_append_only_and_goes_back_clean(migrated_database: str) -> None:
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
        command.upgrade(_cfg(), "0143")
        files = rl.load_files()
        at = datetime(2026, 11, 16, tzinfo=UTC)
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            first = store.load(c, files, at=at, code_version="test")
            c.commit()
            again = store.load(c, files, at=at, code_version="test")
            c.commit()
            # 13 on 16-nov-2026; Colombia v2 on 20-nov (BE-075); IA-149's two shadow versions are never recorded
            coded = [f for f in files if f.rules.state != "shadow"]
            assert len(files) == 16 and all(x.created for x in first) and len(first) == len(coded) == 14
            assert not any(x.created for x in again), "the same content twice writes nothing"
            recorded = store.loaded(c)
            assert {(r["league_id"], r["version"]) for r in recorded} == {f.key for f in coded}
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("UPDATE core.competition_rules SET state = 'retired', reason = 'nope'")
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("DELETE FROM core.competition_rules")
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):  # a retired row says why
                c.execute("INSERT INTO core.competition_rules (league_id, rules_version, state, seasons, schema_version, file_path, "
                          "file_sha256, rules, sources, reader_version, loaded_at, loaded_by) VALUES (39, 9, 'retired', '{2025}', "
                          "'competition-rules/1', 'x/v9.yaml', repeat('a', 64), '{}', '[{}]', 'rules-v1', now(), 'loader')")
            c.rollback()
            _seed_season(c)
            c.commit()
            c.read_only = True
            data = store.season_data(c, 39, 2025)
            assert data is not None and len(data.matches) == 6 and set(data.tables) == {"Premier League"}
            rules = rl.rules_for(39, 2025)
            assert isinstance(rules, rl.Coded)
            [comparison] = rc.reconstruct(rules.rules, "season.league", data.matches, data.tables)
            assert comparison.data_differs == () and comparison.same == 3 and comparison.complete  # Gamma 2nd on goal difference
            c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            left = c.execute("SELECT to_regclass('core.competition_rules'), to_regprocedure('core.refuse_rules_change()')").fetchone()
            assert left == (None, None)
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
