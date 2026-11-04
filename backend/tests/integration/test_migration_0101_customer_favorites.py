"""Migration 0101 (a reader's favourites, plan UX A13): one new table in ``customer``, nothing else.

Deploying must change nothing the system already stores: 0101 adds ``customer.favorites``; every other table keeps its
columns. The table refuses what it must never hold - a favourite of another kind, a league row pointing at a team, the same
favourite twice - follows a league or team row that disappears, and never lets an account be deleted from under it (an
account is anonymised, A7). Going back drops it while it is empty and is refused once readers chose favourites. Run on a
scratch database at revision 0100, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0101"


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
    return c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', "
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND NOT (table_schema = 'customer' "
                     "AND table_name = 'favorites') ORDER BY 1, 2, ordinal_position").fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


FAVOURITE = ("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id) VALUES (%s, %s, %s, %s, %s)")


def test_0101_adds_the_favourites_and_goes_back_only_while_none_was_chosen(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0100")
        with psycopg.connect(dsn) as c:
            before = _shape(c)
        command.upgrade(_cfg(), "0101")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('fav@test.local', 'Fav', '$argon2id$x', 'USER') RETURNING id").fetchone()
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (91001, 'L', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
            team = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (91001, 'T') RETURNING id").fetchone()
            assert user and comp and team
            u, league, side = user[0], comp[0], team[0]
            c.execute(FAVOURITE, (u, "league", league, league, None))
            c.execute(FAVOURITE, (u, "team", side, None, side))
            _refused(c, FAVOURITE, (u, "league", league, league, None))  # the same favourite twice
            _refused(c, FAVOURITE, (u, "player", side, None, side))  # another kind
            _refused(c, FAVOURITE, (u, "league", side, None, side))  # a league row pointing at a team
            _refused(c, FAVOURITE, (u, "team", league + 999, None, side))  # its id and its team disagree
            with pytest.raises(psycopg.errors.ForeignKeyViolation), c.transaction():
                c.execute("DELETE FROM auth.users WHERE id = %s", (u,))  # an account is anonymised, never deleted
            c.execute("DELETE FROM core.teams WHERE id = %s", (side,))
            assert c.execute("SELECT kind FROM customer.favorites").fetchall() == [("league",)], (
                "a favourite whose team disappears goes with it")
        with pytest.raises(Exception, match="readers' favourites"):
            command.downgrade(_cfg(), "0100")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM customer.favorites").fetchone() == (1,), "the favourites are kept"
            c.execute("DELETE FROM customer.favorites")
        command.downgrade(_cfg(), "0100")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT to_regclass('customer.favorites')").fetchone() == (None,)
            assert _shape(c) == before
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
