"""Sign-in and authorization, end to end over HTTP against the migrated database.

The server decides who may do what - for every route, not just the ones with a link:
no session is 401, a USER on an admin route is 403, a SUPER_ADMIN gets through.
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

ADMIN_EMAIL = "owner@predigol.test"
USER_EMAIL = "fan@predigol.test"
ADMIN_PW = "Owner-pass-2026!"
USER_PW = "Fan-password-2026"
SAME_SITE = {"x-requested-with": "predigol"}
COOKIE = "predigol_session"


@pytest.fixture(scope="module")
def accounts(migrated_database: str) -> Iterator[dict[str, int]]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    # Roles and permissions, not the second factor: that is test_auth_mfa.py, with the production policy
    # (SUPER_ADMIN must use one). Here the owner signs in with the password alone.
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    admin = service.create_user_unattended(email=ADMIN_EMAIL, display_name="Owner", role="SUPER_ADMIN",
                                           password=ADMIN_PW, language="es", timezone="Europe/Madrid")
    user = service.create_user_unattended(email=USER_EMAIL, display_name="Fan", role="USER", password=USER_PW,
                                          language="en", timezone="America/Bogota")
    yield {"admin": int(admin["id"]), "user": int(user["id"])}
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def app_client(accounts: dict[str, int]) -> Iterator[TestClient]:
    throttle.reset_all()
    from fbi.api.app import create_app

    with TestClient(create_app(), headers=SAME_SITE) as c:
        yield c


def login(c: TestClient, email: str, password: str) -> TestClient:
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_without_a_session_the_product_is_closed_and_health_is_open(app_client: TestClient) -> None:
    assert app_client.get("/health").status_code in (200, 503)
    for path in ("/api/v1/home", "/api/v1/matches", "/api/v1/live", "/api/v1/auth/me", "/api/v1/admin/overview"):
        r = app_client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"


def test_sign_in_sets_an_httponly_samesite_cookie_and_never_returns_the_token(app_client: TestClient) -> None:
    r = app_client.post("/api/v1/auth/login", json={"email": "  OWNER@predigol.test ", "password": ADMIN_PW})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    token = cookie.split("=", 1)[1].split(";", 1)[0]
    assert token not in r.text
    me = r.json()
    assert me["role"] == "SUPER_ADMIN" and me["language"] == "es" and me["timezone"] == "Europe/Madrid"
    assert "admin" in me["permissions"] and "app" in me["permissions"]
    assert app_client.get("/api/v1/auth/me").json()["email"] == ADMIN_EMAIL


def test_a_wrong_password_and_an_unknown_address_look_the_same(app_client: TestClient) -> None:
    wrong = app_client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "nope-nope-nope"})
    unknown = app_client.post("/api/v1/auth/login", json={"email": "nobody@predigol.test", "password": "x" * 12})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
    assert "set-cookie" not in wrong.headers


def test_repeated_failures_are_throttled_but_never_block_the_right_password_before(app_client: TestClient) -> None:
    for _ in range(5):
        assert app_client.post("/api/v1/auth/login", json={"email": USER_EMAIL, "password": "wrong-pw-123"}
                               ).status_code == 401
    r = app_client.post("/api/v1/auth/login", json={"email": USER_EMAIL, "password": USER_PW})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"
    assert int(r.headers["retry-after"]) > 0
    throttle.reset_all()
    # The five failures also locked the account in the database (test_auth_mfa.py covers that lock): lift it.
    from fbi.auth.db import write_connection

    with write_connection() as conn:
        conn.execute("UPDATE auth.users SET failed_logins = 0, locked_until = NULL")


def test_a_user_reaches_the_product_and_gets_403_on_every_admin_route(app_client: TestClient) -> None:
    login(app_client, USER_EMAIL, USER_PW)
    for path in ("/api/v1/home", "/api/v1/picks", "/api/v1/parlays/daily", "/api/v1/parlays/multiday",
                 "/api/v1/odds/best", "/api/v1/live", "/api/v1/matches", "/api/v1/odds"):
        assert app_client.get(path).status_code == 200, path
    from fbi.api.app import create_app

    paths = {p: ops for p, ops in create_app().openapi()["paths"].items() if p.startswith("/api/v1/admin")}
    assert len(paths) > 25
    for template, ops in paths.items():
        path = re.sub(r"\{[^}]+\}", "1", template)
        for method in ops:
            r = app_client.request(method.upper(), path, json={} if method in ("post", "patch") else None)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
            assert r.json()["error"]["code"] == "forbidden"


def test_the_shadow_preview_is_refused_to_a_user_and_labelled_for_the_owner(app_client: TestClient) -> None:
    login(app_client, USER_EMAIL, USER_PW)
    for path in ("/api/v1/home?preview=shadow", "/api/v1/picks?preview=shadow", "/api/v1/parlays/daily?preview=shadow",
                 "/api/v1/odds/best?preview=shadow"):
        assert app_client.get(path).status_code == 403, path
    user_view = app_client.get("/api/v1/picks").json()["data"]
    assert user_view["source"] == "qualified"
    app_client.post("/api/v1/auth/logout")
    login(app_client, ADMIN_EMAIL, ADMIN_PW)
    preview = app_client.get("/api/v1/picks?preview=shadow").json()["data"]
    assert preview["source"] == "shadow_preview"


def test_a_super_admin_reaches_the_admin_console(app_client: TestClient) -> None:
    login(app_client, ADMIN_EMAIL, ADMIN_PW)
    for path in ("/api/v1/admin/overview", "/api/v1/admin/system", "/api/v1/admin/users", "/api/v1/admin/audit",
                 "/api/v1/admin/models", "/api/v1/admin/performance", "/api/v1/admin/picks",
                 "/api/v1/admin/data-quality/issues", "/api/v1/admin/analytics/migration"):
        assert app_client.get(path).status_code == 200, path


def test_a_state_changing_request_needs_the_same_site_header(accounts: dict[str, int]) -> None:
    from fbi.api.app import create_app

    with TestClient(create_app()) as bare:
        r = bare.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
        r = bare.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
                      headers={**SAME_SITE, "origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_sign_out_ends_the_session_server_side(app_client: TestClient) -> None:
    login(app_client, USER_EMAIL, USER_PW)
    token = app_client.cookies.get(COOKIE)
    assert app_client.post("/api/v1/auth/logout").status_code == 204
    # the old cookie, replayed, is dead
    app_client.cookies.set(COOKIE, token or "")
    assert app_client.get("/api/v1/auth/me").status_code == 401


def test_preferences_are_validated_and_stored(app_client: TestClient) -> None:
    login(app_client, USER_EMAIL, USER_PW)
    r = app_client.patch("/api/v1/auth/me/preferences", json={"language": "es", "timezone": "Europe/Madrid"})
    assert r.status_code == 200 and r.json()["language"] == "es" and r.json()["timezone"] == "Europe/Madrid"
    assert app_client.get("/api/v1/auth/me").json()["timezone"] == "Europe/Madrid"
    bad = app_client.patch("/api/v1/auth/me/preferences", json={"timezone": "Mars/Olympus_Mons"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_timezone"
    assert app_client.patch("/api/v1/auth/me/preferences", json={"language": "fr"}).status_code == 422
    app_client.patch("/api/v1/auth/me/preferences", json={"language": "en", "timezone": "America/Bogota"})


def test_changing_the_password_ends_the_other_sessions(accounts: dict[str, int]) -> None:
    from fbi.api.app import create_app

    throttle.reset_all()
    with TestClient(create_app(), headers=SAME_SITE) as a, TestClient(create_app(), headers=SAME_SITE) as b:
        login(a, USER_EMAIL, USER_PW)
        login(b, USER_EMAIL, USER_PW)
        wrong = a.post("/api/v1/auth/me/password", json={"current_password": "nope", "new_password": "N3w-pass-2026"})
        assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "wrong_password"
        weak = a.post("/api/v1/auth/me/password", json={"current_password": USER_PW, "new_password": "short"})
        assert weak.status_code == 422 and "password_too_short" in weak.json()["error"]["problems"]
        ok = a.post("/api/v1/auth/me/password", json={"current_password": USER_PW, "new_password": "N3w-pass-2026"})
        assert ok.status_code == 204
        assert a.get("/api/v1/auth/me").status_code == 200
        assert b.get("/api/v1/auth/me").status_code == 401
        assert a.post("/api/v1/auth/me/password", json={"current_password": "N3w-pass-2026",
                                                        "new_password": USER_PW}).status_code == 204


def test_the_owner_manages_accounts_and_cannot_lock_everyone_out(app_client: TestClient,
                                                                  accounts: dict[str, int]) -> None:
    login(app_client, ADMIN_EMAIL, ADMIN_PW)
    users = app_client.get("/api/v1/admin/users").json()["data"]
    assert {u["email"] for u in users} >= {ADMIN_EMAIL, USER_EMAIL}
    assert not any(k in ("password", "password_hash", "totp_secret") or "hash" in k or "secret" in k
                   for u in users for k in u)
    # the only SUPER_ADMIN can neither demote nor disable themself
    me = accounts["admin"]
    r = app_client.patch(f"/api/v1/admin/users/{me}", json={"role": "USER"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_super_admin"
    r = app_client.patch(f"/api/v1/admin/users/{me}", json={"status": "disabled"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_disable_self"
    # create, promote, demote, disable
    created = app_client.post("/api/v1/admin/users", json={
        "email": "new.fan@predigol.test", "password": "Another-pass-26", "role": "USER", "language": "en"})
    assert created.status_code == 201, created.text
    new_id = created.json()["data"]["id"]
    dup = app_client.post("/api/v1/admin/users", json={"email": "NEW.fan@predigol.test", "password": "Another-pass-26"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"
    promoted = app_client.patch(f"/api/v1/admin/users/{new_id}", json={"role": "SUPER_ADMIN"}).json()["data"]
    assert promoted["role"] == "SUPER_ADMIN"
    assert app_client.patch(f"/api/v1/admin/users/{new_id}", json={"role": "USER"}).status_code == 200
    assert app_client.patch(f"/api/v1/admin/users/{new_id}", json={"role": "OVERLORD"}).status_code == 422


def test_disabling_an_account_ends_its_sessions_at_once(accounts: dict[str, int]) -> None:
    from fbi.api.app import create_app

    throttle.reset_all()
    with TestClient(create_app(), headers=SAME_SITE) as owner, TestClient(create_app(), headers=SAME_SITE) as fan:
        login(owner, ADMIN_EMAIL, ADMIN_PW)
        login(fan, USER_EMAIL, USER_PW)
        assert fan.get("/api/v1/home").status_code == 200
        assert owner.patch(f"/api/v1/admin/users/{accounts['user']}", json={"status": "disabled"}).status_code == 200
        assert fan.get("/api/v1/home").status_code == 401
        refused = fan.post("/api/v1/auth/login", json={"email": USER_EMAIL, "password": USER_PW})
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "account_disabled"
        assert owner.patch(f"/api/v1/admin/users/{accounts['user']}", json={"status": "active"}).status_code == 200
        login(fan, USER_EMAIL, USER_PW)


def test_the_audit_trail_records_who_did_what_and_never_a_secret(app_client: TestClient) -> None:
    login(app_client, ADMIN_EMAIL, ADMIN_PW)
    body = app_client.get("/api/v1/admin/audit?limit=200")
    events = body.json()["data"]
    actions = {e["action"] for e in events}
    assert {"login.succeeded", "login.failed", "logout", "user.created", "user.role_changed",
            "user.status_changed", "password.changed"} <= actions
    for secret in (ADMIN_PW, USER_PW, "N3w-pass-2026"):
        assert secret not in body.text
