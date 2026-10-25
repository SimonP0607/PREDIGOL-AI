"""A user's session slides with use (plan UX, A1, defect F05), over HTTP against the migrated database.

The audit found a user's session ending 168 hours after sign-in however much it was used: a reader who opened the
product every day was sent to sign in again every week. From A1 a USER's session lives while it is used - it ends
7 days after its last use - and never more than 30 days after sign-in, an absolute cap kept on purpose. A
SUPER_ADMIN keeps the short limits (24 h, 8 h without use) until the security plan shortens them (R14). And a
session dead from idleness is dead everywhere: it is not listed among "your sessions" nor counted in the Admin
Console, as it can no longer be used.

The clocks are moved back with SQL on the session rows (created_at, expires_at and last_seen_at together), so each
test reads what the server decides at a given age of the session.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from tests.integration.helpers import forget_sign_in_failures

ADMIN_EMAIL = "keeper@predigol.test"
USER_EMAIL = "regular@predigol.test"
ADMIN_PW = "Clean-sheet-2026!"
USER_PW = "Season-ticket-2026"
SAME_SITE = {"x-requested-with": "predigol"}


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    # The owner signs in with the password alone here; test_auth_mfa.py covers the second factor.
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    service.create_user_unattended(email=ADMIN_EMAIL, display_name="Keeper", role="SUPER_ADMIN", password=ADMIN_PW,
                                   language="es", timezone="Europe/Madrid")
    service.create_user_unattended(email=USER_EMAIL, display_name="Regular", role="USER", password=USER_PW,
                                   language="es", timezone="America/Bogota")
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str) -> Iterator[str]:
    """No session left from another test."""
    throttle.reset_all()
    forget_sign_in_failures()
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
    yield database


def signed_in(email: str, password: str) -> TestClient:
    from fbi.api.app import create_app

    client = TestClient(create_app(), headers=SAME_SITE)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return client


def age(database: str, email: str, *, since_sign_in: str, since_last_use: str) -> None:
    """Make every live session of the account as old as given: signed in `since_sign_in` ago (its absolute expiry
    moves with it) and last used `since_last_use` ago. Postgres intervals, e.g. '10 days'."""
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("""
            UPDATE auth.sessions s SET created_at = s.created_at - %(back)s::interval,
                   expires_at = s.expires_at - %(back)s::interval,
                   last_seen_at = now() - %(idle)s::interval
              FROM auth.users u WHERE u.id = s.user_id AND u.email = %(email)s AND s.revoked_at IS NULL
        """, {"back": since_sign_in, "idle": since_last_use, "email": email})


def test_a_user_session_in_use_outlives_the_old_seven_day_cap(fresh: str) -> None:
    client = signed_in(USER_EMAIL, USER_PW)
    age(fresh, USER_EMAIL, since_sign_in="10 days", since_last_use="1 day")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200, "a session used yesterday must still be open ten days after sign-in"
    assert r.json()["email"] == USER_EMAIL


def test_a_user_session_unused_for_seven_days_ends(fresh: str) -> None:
    client = signed_in(USER_EMAIL, USER_PW)
    age(fresh, USER_EMAIL, since_sign_in="8 days", since_last_use="7 days 1 hour")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_a_user_session_six_days_unused_is_still_open_and_its_use_renews_it(fresh: str) -> None:
    client = signed_in(USER_EMAIL, USER_PW)
    age(fresh, USER_EMAIL, since_sign_in="6 days 1 hour", since_last_use="6 days")
    assert client.get("/api/v1/auth/me").status_code == 200
    with psycopg.connect(fresh) as conn:
        idle = conn.execute("SELECT extract(epoch FROM now() - last_seen_at) FROM auth.sessions s JOIN auth.users u "
                            "ON u.id = s.user_id WHERE u.email = %s", (USER_EMAIL,)).fetchone()
    assert idle is not None and float(idle[0]) < 60, "using the session must write its last use again"


def test_a_user_session_ends_thirty_days_after_sign_in_however_much_it_is_used(fresh: str) -> None:
    client = signed_in(USER_EMAIL, USER_PW)
    age(fresh, USER_EMAIL, since_sign_in="30 days 1 hour", since_last_use="1 hour")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_the_cookie_lives_as_long_as_the_session_can(fresh: str) -> None:
    """The browser keeps the cookie for the absolute cap (30 days for a user, 24 h for the owner): the server decides
    the rest. A cookie of 7 days would end a session in use on day 8 whatever the server says."""
    from fbi.api.app import create_app

    for email, password, hours in ((USER_EMAIL, USER_PW, 30 * 24), (ADMIN_EMAIL, ADMIN_PW, 24)):
        with TestClient(create_app(), headers=SAME_SITE) as client:
            r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert r.status_code == 200, r.text
            found = re.search(r"max-age=(\d+)", r.headers["set-cookie"], flags=re.I)
            assert found, r.headers["set-cookie"]
            assert abs(int(found.group(1)) - hours * 3600) <= 120, (email, found.group(1))


def test_the_owner_keeps_the_short_admin_limits(fresh: str) -> None:
    client = signed_in(ADMIN_EMAIL, ADMIN_PW)
    age(fresh, ADMIN_EMAIL, since_sign_in="7 hours", since_last_use="7 hours")
    assert client.get("/api/v1/auth/me").status_code == 200
    age(fresh, ADMIN_EMAIL, since_sign_in="2 hours", since_last_use="9 hours")
    assert client.get("/api/v1/auth/me").status_code == 401, "eight hours without use end an owner's session"
    client = signed_in(ADMIN_EMAIL, ADMIN_PW)
    age(fresh, ADMIN_EMAIL, since_sign_in="24 hours 5 minutes", since_last_use="5 minutes")
    assert client.get("/api/v1/auth/me").status_code == 401, "an owner's session never lasts more than 24 hours"


def test_a_session_dead_from_idleness_is_neither_listed_nor_counted(fresh: str) -> None:
    """Dead from idleness only: unused one hour longer than the idle limit, well inside the absolute cap."""
    from fbi.auth.settings import session_settings

    idle = session_settings().idle_hours
    stale = signed_in(USER_EMAIL, USER_PW)
    age(fresh, USER_EMAIL, since_sign_in=f"{idle + 2} hours", since_last_use=f"{idle + 1} hours")
    assert stale.get("/api/v1/auth/me").status_code == 401
    live = signed_in(USER_EMAIL, USER_PW)
    listed = live.get("/api/v1/auth/me/sessions")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1, "the session that can no longer be used is not one of 'your sessions'"
    owner = signed_in(ADMIN_EMAIL, ADMIN_PW)
    users = owner.get("/api/v1/admin/users").json()["data"]
    regular = next(u for u in users if u["email"] == USER_EMAIL)
    assert regular["active_sessions"] == 1, regular


def test_the_account_is_told_how_long_its_session_lasts_unused(fresh: str) -> None:
    """The profile says the session closes sooner if it goes unused (it slides): /auth/me tells the limit that applies
    to the account - 7 days for a user, 8 hours for the owner - beside the absolute end."""
    user = signed_in(USER_EMAIL, USER_PW).get("/api/v1/auth/me").json()
    assert user["session_idle_hours"] == 7 * 24
    owner = signed_in(ADMIN_EMAIL, ADMIN_PW).get("/api/v1/auth/me").json()
    assert owner["session_idle_hours"] == 8
