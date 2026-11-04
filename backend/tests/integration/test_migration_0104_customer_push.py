"""Migration 0104 (the readers' notices on their devices, plan UX B7): three new tables in ``customer`` and one column in
``customer.preferences``, nothing else.

Deploying must change nothing the system already stores: every other table keeps its columns, and ``customer.preferences``
gains only ``push_off``, empty for every reader who had preferences. The tables refuse what they must never hold - an
address that is no web address, keys no browser gives, a second live row for the same browser, a revocation without its
reason, a bell at another minute or twice on the same match, a notice of another category, with a key, a title, a line or
a page out of shape, the same notice twice, a notice sent without its devices or dropped without its reason, a category
switched off that cannot be - and never let an account be deleted from under them (an account is anonymised, A7); a match
deleted takes its bells with it. Going back drops them while they are empty and is refused once a reader has a device, a
bell, a notice or a category off. Run on a scratch database at revision 0103, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0104"
NEW = ["push_subscriptions", "match_alerts", "push_notices"]


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
                     "AND (table_name = ANY(%s) OR (table_name = 'preferences' AND column_name = 'push_off'))) "
                     "ORDER BY 1, 2, ordinal_position", (NEW,)).fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


def _one(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


P256DH = "B" + "x" * 86  # a P-256 public point, uncompressed, in base64url: 87 characters
AUTH = "y" * 22  # sixteen bytes in base64url
SUB = ("INSERT INTO customer.push_subscriptions (user_id, endpoint, p256dh, auth, family, system, revoked_at, "
       "revoked_reason, failures) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")
ALERT = "INSERT INTO customer.match_alerts (user_id, fixture_id, minutes_before) VALUES (%s, %s, %s)"
NOTICE = ("INSERT INTO customer.push_notices (user_id, category, dedup_key, title, body, url, expires_at, status, sent_at, "
          "devices, dropped) VALUES (%s, %s, %s, %s, %s, %s, now() + %s * interval '1 hour', %s, %s, %s, %s)")
FCM = "https://fcm.googleapis.com/fcm/send/abc:APA91b"


def _football(c: psycopg.Connection[Any]) -> tuple[int, int]:
    league = _one(c, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                     "competition_type, is_tracked) VALUES (7714901, 'Liga M0104', 'Colombia', 'league', 'club', "
                     "'domestic_league', true) RETURNING id")
    season = _one(c, "INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                     "RETURNING id", (league,))
    home = _one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (7714902, 'Local') RETURNING id")
    away = _one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (7714903, 'Visitante') RETURNING id")
    fixtures = [_one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                        "kickoff_at, status_group) VALUES (%s, %s, %s, %s, now() + interval '1 day', 'scheduled') "
                        "RETURNING id", (provider, season, home, away)) for provider in (7714904, 7714905)]
    return fixtures[0], fixtures[1]


def test_0104_adds_the_devices_the_bells_and_the_queue_and_goes_back_only_while_nobody_has_them(
        migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0103")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            u = _one(c, "INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                        "('push@test.local', 'Push', '$argon2id$x', 'USER') RETURNING id")
            c.execute("INSERT INTO customer.preferences (user_id, email_off) VALUES (%s, '{support}')", (u,))
        command.upgrade(_cfg(), "0104")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there, push_off aside"
            assert c.execute("SELECT email_off, push_off FROM customer.preferences WHERE user_id = %s",
                             (u,)).fetchone() == (["support"], []), "a reader's preferences stay; nothing switched off"
            one, two = _football(c)

            # the devices
            c.execute(SUB, (u, FCM, P256DH, AUTH, "chrome", "android", None, None, 0))
            _refused(c, SUB, (u, FCM, P256DH, AUTH, "chrome", "android", None, None, 0))  # the same browser twice, live
            for endpoint in ("ftp://fcm.googleapis.com/x", "https://a.b", "https://" + "a" * 1020):
                _refused(c, SUB, (u, endpoint, P256DH, AUTH, "chrome", "android", None, None, 0))  # no web address
            for key in ("B" + "x" * 84, P256DH + "==", "B" + "x" * 85 + "+"):
                _refused(c, SUB, (u, FCM + "1", key, AUTH, "chrome", "android", None, None, 0))  # no browser's key
            for auth in ("y" * 20, "y" * 21 + "/"):
                _refused(c, SUB, (u, FCM + "2", P256DH, auth, "chrome", "android", None, None, 0))
            _refused(c, SUB, (u, FCM + "3", P256DH, AUTH, "opera", "android", None, None, 0))  # another family
            _refused(c, SUB, (u, FCM + "4", P256DH, AUTH, "chrome", "beos", None, None, 0))  # another system
            _refused(c, SUB, (u, FCM + "5", P256DH, AUTH, "chrome", "android", "now", None, 0))  # revoked: why?
            _refused(c, SUB, (u, FCM + "6", P256DH, AUTH, "chrome", "android", None, "gone", 0))  # a reason, not revoked
            _refused(c, SUB, (u, FCM + "7", P256DH, AUTH, "chrome", "android", "now", "banned", 0))  # another reason
            _refused(c, SUB, (u, FCM + "8", P256DH, AUTH, "chrome", "android", None, None, -1))
            c.execute("UPDATE customer.push_subscriptions SET revoked_at = now(), revoked_reason = 'unsubscribed'")
            c.execute(SUB, (u, FCM, P256DH, AUTH, "chrome", "android", None, None, 0))  # allowed again: a new live row
            assert _one(c, "SELECT count(*) FROM customer.push_subscriptions") == 2

            # the bells
            c.execute(ALERT, (u, one, 15))
            c.execute("INSERT INTO customer.match_alerts (user_id, fixture_id) VALUES (%s, %s)", (u, two))
            assert _one(c, "SELECT minutes_before FROM customer.match_alerts WHERE fixture_id = %s", (two,)) == 30
            _refused(c, ALERT, (u, one, 60))  # a second bell on the same match
            for minutes in (0, 10, 45, 120):
                _refused(c, "UPDATE customer.match_alerts SET minutes_before = %s WHERE fixture_id = %s", (minutes, one))
            c.execute("DELETE FROM core.fixtures WHERE id = %s", (two,))
            assert _one(c, "SELECT count(*) FROM customer.match_alerts") == 1, "a match deleted takes its bell"

            # the queue
            ok = (u, "result", "result:pick:1", "Ganado: tu pick", "Mira el postpartido.", "/matches/1#postmatch", 24,
                  "queued", None, None, None)
            c.execute(NOTICE, ok)
            _refused(c, NOTICE, ok)  # the same notice twice
            fields = {"category": 1, "key": 2, "title": 3, "body": 4, "url": 5, "hours": 6}
            for field, value in (("category", "promo"), ("key", "Result:1"), ("key", "result"), ("key", "result:"),
                                 ("key", "result:a b"), ("key", "result:" + "a" * 101), ("title", ""), ("title", "t" * 121),
                                 ("body", ""), ("body", "b" * 301), ("url", "https://evil.example/"),
                                 ("url", "/x y"), ("url", "matches/1"), ("url", "//evil.example/x"),
                                 ("hours", -1)):
                row = list(ok)
                row[2] = "result:pick:2"
                row[fields[field]] = value
                _refused(c, NOTICE, tuple(row))
            for status, sent_at, devices, dropped in (("sent", None, None, None), ("sent", "now", None, None),
                                                      ("dropped", None, None, None), ("queued", None, None, "expired"),
                                                      ("dropped", None, None, "unsent"), ("sent", "now", -1, None),
                                                      ("waiting", None, None, None)):
                _refused(c, NOTICE, (u, "test", "test:2", "t", "b", "/home", 1, status, sent_at, devices, dropped))
            c.execute(NOTICE, (u, "reminder", "reminder:1:30", "t", "b", "/matches/1", 1, "sent", "now", 2, None))
            c.execute(NOTICE, (u, "lineup", "lineup:1", "t", "b", "/matches/1#lineups", 1, "dropped", None, None,
                               "daily_cap"))

            # the categories a reader switches off: the four of the plan, never the bell they asked for
            c.execute("UPDATE customer.preferences SET push_off = '{result,account}' WHERE user_id = %s", (u,))
            for off in ("{reminder}", "{test}", "{promo}"):
                _refused(c, "UPDATE customer.preferences SET push_off = %s WHERE user_id = %s", (off, u))
            with pytest.raises(psycopg.errors.ForeignKeyViolation), c.transaction():
                c.execute("DELETE FROM auth.users WHERE id = %s", (u,))  # an account is anonymised, never deleted

        with pytest.raises(Exception, match="devices, bells or notices"):
            command.downgrade(_cfg(), "0103")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert [_one(c, f"SELECT count(*) FROM customer.{table}") for table in NEW] == [2, 1, 3], "all kept"
            for table in NEW:
                c.execute(f"DELETE FROM customer.{table}")
        with pytest.raises(Exception, match="devices, bells or notices"):
            command.downgrade(_cfg(), "0103")  # a category still switched off
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("UPDATE customer.preferences SET push_off = '{}'")
        command.downgrade(_cfg(), "0103")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert [_one(c, f"SELECT to_regclass('customer.{table}')") for table in NEW] == [None, None, None]
            assert _shape(c) == before
            assert c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'customer' "
                             "AND table_name = 'preferences' AND column_name = 'push_off'").fetchone() == (0,)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
