"""Migration 0136 (decision 8 of the plan maestro UX/UI 2026, BE-039): four settings of presentation in
``customer.preferences`` and a bell per followed team in ``customer.favorites`` - and nothing else.

Deploying must change nothing the system already stores: every row keeps its values and takes the defaults that leave
everything as it was (24 h, decimal, motion as the device says, Inicio by the rule, every bell on). The closed lists refuse
anything else. Going back drops the five columns and leaves the rest untouched. Run on a scratch database at revision 0135,
the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0136"
NEW = {("preferences", "time_format"), ("preferences", "odds_format"), ("preferences", "reduce_motion"),
       ("preferences", "home_default"), ("favorites", "notify")}


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
    return [r for r in rows if not (r[0] == "customer" and (r[1], r[2]) in NEW)]


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


def test_0136_adds_the_settings_with_todays_values_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0135")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('pref136@test.local', 'Pref', '$argon2id$x', 'USER') RETURNING id").fetchone()
            team = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (913601, 'T') RETURNING id").fetchone()
            assert user and team
            u, t = user[0], team[0]
            c.execute("INSERT INTO customer.preferences (user_id, guides_auto) VALUES (%s, false)", (u,))
            c.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, team_id) VALUES (%s, 'team', %s, %s)",
                      (u, t, t))
        command.upgrade(_cfg(), "0136")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            assert c.execute("SELECT guides_auto, time_format, odds_format, reduce_motion, home_default "
                             "FROM customer.preferences WHERE user_id = %s", (u,)).fetchone() == (
                False, "24h", "decimal", False, None), "the row keeps its values and takes today's defaults"
            assert c.execute("SELECT notify FROM customer.favorites WHERE user_id = %s", (u,)).fetchone() == (True,)
            _refused(c, "UPDATE customer.preferences SET time_format = 'am' WHERE user_id = %s", (u,))
            _refused(c, "UPDATE customer.preferences SET odds_format = 'hongkong' WHERE user_id = %s", (u,))
            _refused(c, "UPDATE customer.preferences SET home_default = 'picks' WHERE user_id = %s", (u,))
            c.execute("UPDATE customer.preferences SET time_format = '12h', odds_format = 'fractional', "
                      "reduce_motion = true, home_default = 'all' WHERE user_id = %s", (u,))
            c.execute("UPDATE customer.favorites SET notify = false WHERE user_id = %s", (u,))
        command.downgrade(_cfg(), "0135")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT guides_auto FROM customer.preferences WHERE user_id = %s", (u,)).fetchone() == (False,)
            assert c.execute("SELECT kind, ref_id FROM customer.favorites WHERE user_id = %s", (u,)).fetchone() == (
                "team", t), "the favourite is still there"
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
