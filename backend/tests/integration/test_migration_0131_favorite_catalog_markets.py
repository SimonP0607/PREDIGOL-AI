"""Migration 0131 (a reader follows markets of the catalogue, CUOTAS BE-025): ``customer.favorites`` widens, nothing else.

Deploying must change nothing the system already stores: 0131 touches ``customer.favorites`` alone; the league, team, player
and classic market rows keep working as they did. The table takes a ``catalog`` row (its own key and nothing else), refuses a
row that points at two things, the same catalogue market twice and a key of a silly length, and keeps one row per reader and
favourite for the older kinds. Going back is refused while a reader follows a catalogue market, and once none does it puts the
older constraint and index back. Run on a scratch database at revision 0130, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0131"


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


ROW = ("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id, player_id, market_key, catalog_key) "
       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)")


def test_0131_widens_the_favourites_and_goes_back_only_while_no_catalogue_market_is_followed(
        migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('fav131@test.local', 'Fav', '$argon2id$x', 'USER') RETURNING id").fetchone()
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                             "competition_type) VALUES (91131, 'L', 'league', 'club', 'domestic_league') "
                             "RETURNING id").fetchone()
            assert user and comp
            u, league = user[0], comp[0]
            # What a reader already follows at 0130 must survive the revision untouched.
            c.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
                      (u, league, league))
            c.execute("INSERT INTO customer.favorites (user_id, kind, market_key) VALUES (%s, 'market', 'OU')", (u,))
        command.upgrade(_cfg(), "0131")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any other table"
            assert c.execute("SELECT kind, ref_id, market_key, catalog_key FROM customer.favorites ORDER BY kind"
                             ).fetchall() == [("league", league, None, None), ("market", None, "OU", None)]
            c.execute(ROW, (u, "catalog", None, None, None, None, None, "corners_over_under.FT.match"))
            c.execute(ROW, (u, "catalog", None, None, None, None, None, "yellow_cards_1x2.1H.home"))
            _refused(c, ROW, (u, "catalog", None, None, None, None, None, "corners_over_under.FT.match"))  # twice
            _refused(c, ROW, (u, "market", None, None, None, None, "OU", None))  # a classic market twice
            _refused(c, ROW, (u, "catalog", None, None, None, None, None, None))  # a catalogue row without its key
            _refused(c, ROW, (u, "catalog", None, None, None, None, None, "x"))  # a key too short
            _refused(c, ROW, (u, "catalog", None, None, None, None, None, "k" * 81))  # a key too long
            _refused(c, ROW, (u, "catalog", None, None, None, None, "OU", "goals_btts.FT.match"))  # two things
            _refused(c, ROW, (u, "catalog", league, league, None, None, None, "goals_btts.FT.match"))  # an id too
            _refused(c, ROW, (u, "market", None, None, None, None, "BTTS", "goals_btts.FT.match"))  # a market with a key
            _refused(c, ROW, (u, "league", league, league, None, None, None, "goals_btts.FT.match"))  # a league with one
            other = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                              "('fav131b@test.local', 'Fav B', '$argon2id$x', 'USER') RETURNING id").fetchone()
            assert other
            c.execute(ROW, (other[0], "catalog", None, None, None, None, None, "corners_over_under.FT.match"))
        with pytest.raises(Exception, match="catalogue markets"):
            command.downgrade(_cfg(), "0130")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM customer.favorites WHERE user_id = %s", (u,)).fetchone() == (4,), (
                "the favourites are kept")
            c.execute("DELETE FROM customer.favorites WHERE kind = 'catalog'")
        command.downgrade(_cfg(), "0130")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT kind, ref_id, market_key FROM customer.favorites ORDER BY kind").fetchall() == [
                ("league", league, None), ("market", None, "OU")], "the league and the market are still there"
            assert not c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'customer' "
                                 "AND table_name = 'favorites' AND column_name = 'catalog_key'").fetchall()
            _refused(c, "INSERT INTO customer.favorites (user_id, kind, market_key) VALUES (%s, 'market', 'OU')", (u,))
            _refused(c, "INSERT INTO customer.favorites (user_id, kind, market_key) VALUES (%s, 'catalog', 'OU')", (u,))
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
