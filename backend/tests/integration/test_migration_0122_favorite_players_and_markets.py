"""Migration 0122 (a reader follows players and markets, plan de cierre UX 3.1): ``customer.favorites`` widens, nothing else.

Deploying must change nothing the system already stores: 0122 touches ``customer.favorites`` alone; every other table keeps
its columns and the league and team rows keep working as they did. The table takes a player (a row of ``core.players``) or
a market (a key of ``market.markets``) and nothing else, refuses a row that points at two things or at the wrong one, the
same favourite twice and a market that does not exist, and follows a player row that disappears. Going back is refused
while a reader follows a player or a market, and once none does it puts the older constraints back. Run on a scratch
database at revision 0121, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0122"


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


ROW = ("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id, player_id, market_key) "
       "VALUES (%s, %s, %s, %s, %s, %s, %s)")


def test_0122_widens_the_favourites_and_goes_back_only_while_no_player_or_market_is_followed(
        migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0121")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('fav@test.local', 'Fav', '$argon2id$x', 'USER') RETURNING id").fetchone()
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                             "competition_type) VALUES (91001, 'L', 'league', 'club', 'domestic_league') "
                             "RETURNING id").fetchone()
            team = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (91001, 'T') RETURNING id").fetchone()
            assert user and comp and team
            u, league, side = user[0], comp[0], team[0]
            # What a reader already follows at 0121 must survive the revision untouched.
            c.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
                      (u, league, league))
            c.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, team_id) VALUES (%s, 'team', %s, %s)",
                      (u, side, side))
        command.upgrade(_cfg(), "0122")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            assert c.execute("SELECT kind, ref_id FROM customer.favorites ORDER BY kind").fetchall() == [
                ("league", league), ("team", side)], "the league and the team are still there"
            player = c.execute("INSERT INTO core.players (provider_player_id, name) VALUES (91001, 'P') "
                               "RETURNING id").fetchone()
            other = c.execute("INSERT INTO core.players (provider_player_id, name) VALUES (91002, 'Q') "
                              "RETURNING id").fetchone()
            assert player and other
            p, q = player[0], other[0]
            c.execute(ROW, (u, "player", p, None, None, p, None))
            c.execute(ROW, (u, "market", None, None, None, None, "OU"))
            c.execute(ROW, (u, "market", None, None, None, None, "BTTS"))
            _refused(c, ROW, (u, "player", p, None, None, p, None))  # the same player twice
            _refused(c, ROW, (u, "market", None, None, None, None, "OU"))  # the same market twice
            _refused(c, ROW, (u, "league", league, league, None, None, None))  # the same league twice
            _refused(c, ROW, (u, "market", None, None, None, None, "NOT_A_MARKET"))  # a market that does not exist
            _refused(c, ROW, (u, "player", q, None, None, p, None))  # its id and its player disagree
            _refused(c, ROW, (u, "player", q, None, None, q, "OU"))  # a player row that also names a market
            _refused(c, ROW, (u, "market", q, None, None, None, "1X2"))  # a market row that also has an id
            _refused(c, ROW, (u, "market", None, None, None, None, None))  # a market row without its market
            _refused(c, ROW, (u, "coach", q, None, None, q, None))  # another kind
            _refused(c, ROW, (u, "league", side, None, side, None, None))  # a league row pointing at a team
            c.execute("DELETE FROM core.players WHERE id = %s", (p,))
            assert c.execute("SELECT kind FROM customer.favorites ORDER BY kind").fetchall() == [
                ("league",), ("market",), ("market",), ("team",)], "a favourite whose player disappears goes with it"
            c.execute(ROW, (u, "player", q, None, None, q, None))
        with pytest.raises(Exception, match="players or markets"):
            command.downgrade(_cfg(), "0121")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM customer.favorites").fetchone() == (5,), "the favourites are kept"
            c.execute("DELETE FROM customer.favorites WHERE kind IN ('player', 'market')")
        command.downgrade(_cfg(), "0121")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT kind, ref_id FROM customer.favorites ORDER BY kind").fetchall() == [
                ("league", league), ("team", side)], "the league and the team are still there"
            assert not c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'customer' "
                                 "AND table_name = 'favorites' AND column_name IN ('player_id', 'market_key')").fetchall()
            _refused(c, "INSERT INTO customer.favorites (user_id, kind, ref_id, team_id) VALUES (%s, 'player', %s, %s)",
                     (u, side, side))  # the older constraints are back
            _refused(c, "INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
                     (u, league, league))  # and so is one row per reader and favourite
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
