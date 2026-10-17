"""The second factor, the lock-out, staged sessions and the owner's account controls, over HTTP against the migrated
database, with the production policy: a SUPER_ADMIN must use an authenticator.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, throttle, totp
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache

OWNER = "boss@predigol.test"
OWNER_PW = "Boss-pass-2026!"
FAN = "reader@predigol.test"
FAN_PW = "Reader-pass-2026"
SAME_SITE = {"x-requested-with": "predigol"}
COOKIE = "predigol_session"


@pytest.fixture(scope="module")
def db(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.delenv("FBI_AUTH_MFA_ROLES", raising=False)
    reset_cache()
    reset_auth_settings()
    _wipe(migrated_database)
    yield migrated_database
    _wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_auth_settings()


def _wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.users"):
            conn.execute(f"DELETE FROM {t}")


@pytest.fixture()
def accounts(db: str) -> Iterator[dict[str, int]]:
    _wipe(db)
    throttle.reset_all()
    owner = service.create_user_unattended(email=OWNER, display_name="Boss", role="SUPER_ADMIN", password=OWNER_PW)
    fan = service.create_user_unattended(email=FAN, display_name="Reader", role="USER", password=FAN_PW)
    yield {"owner": int(owner["id"]), "fan": int(fan["id"])}
    throttle.reset_all()


def client() -> TestClient:
    from fbi.api.app import create_app

    return TestClient(create_app(), headers=SAME_SITE)


def login(c: TestClient, email: str, password: str) -> dict[str, object]:
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def secret_of(enrollment: dict[str, str]) -> bytes:
    raw = enrollment["secret"].replace(" ", "")
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


def code(secret: bytes, *, after: int | None = None) -> str:
    """A valid code whose step is newer than `after` (codes are never accepted twice)."""
    now = totp.step_at()
    step = now if after is None else max(now, after + 1)
    assert step <= now + totp.WINDOW
    return totp.code_at(secret, step)


def last_step(db: str, user_id: int) -> int:
    with psycopg.connect(db) as conn:
        row = conn.execute("SELECT totp_last_step FROM auth.users WHERE id = %s", (user_id,)).fetchone()
        assert row is not None
        return int(row[0])


def enroll(c: TestClient, *, password: str | None = None) -> tuple[bytes, list[str], dict[str, object]]:
    started = c.post("/api/v1/auth/mfa/enroll/start", json={"password": password} if password else {})
    assert started.status_code == 200, started.text
    secret = secret_of(started.json())
    done = c.post("/api/v1/auth/mfa/enroll/confirm", json={"code": code(secret)})
    assert done.status_code == 200, done.text
    body = done.json()
    return secret, body["recovery_codes"], body["me"]


def test_a_super_admin_must_set_up_an_authenticator_before_anything_else(accounts: dict[str, int], db: str) -> None:
    with client() as c:
        me = login(c, OWNER, OWNER_PW)
        assert me["stage"] == "enroll" and me["mfa_required"] and me["permissions"] == []
        staged_token = c.cookies.get(COOKIE)
        for path in ("/api/v1/home", "/api/v1/admin/overview", "/api/v1/admin/users"):
            r = c.get(path)
            assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_enrollment_required", path
        assert c.get("/api/v1/auth/me").json()["stage"] == "enroll"
        started = c.post("/api/v1/auth/mfa/enroll/start", json={}).json()
        assert started["qr_svg"].startswith("data:image/svg+xml") and started["account"] == OWNER
        assert started["otpauth_uri"].startswith("otpauth://totp/PrediGol:")
        wrong = c.post("/api/v1/auth/mfa/enroll/confirm", json={"code": "000000"})
        assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_code"
        assert wrong.json()["error"]["attempts_left"] == 4
        secret = secret_of(started)
        done = c.post("/api/v1/auth/mfa/enroll/confirm", json={"code": code(secret)}).json()
        assert done["me"]["stage"] == "full" and done["me"]["mfa_enabled"]
        codes = done["recovery_codes"]
        assert len(codes) == 10 and len(set(codes)) == 10
        assert c.cookies.get(COOKIE) != staged_token
        assert c.get("/api/v1/admin/overview").status_code == 200
    # the token of the staged session is dead after the step
    with client() as old:
        old.cookies.set(COOKIE, staged_token or "")
        assert old.get("/api/v1/auth/me").status_code == 401
    # nothing secret is stored in clear
    with psycopg.connect(db) as conn:
        sealed = conn.execute("SELECT totp_secret FROM auth.users WHERE email = %s", (OWNER,)).fetchone()
        assert sealed is not None and secret not in bytes(sealed[0])
        hashes = [r[0] for r in conn.execute("SELECT code_hash FROM auth.recovery_codes").fetchall()]
        assert len(hashes) == 10 and not any(c.replace("-", "") in h for c in codes for h in hashes)
        audit = conn.execute("SELECT string_agg(detail::text, ' ') FROM auth.audit_events").fetchone()
        assert audit is not None and totp.b32(secret) not in (audit[0] or "")


def test_the_second_sign_in_asks_for_a_code_and_never_accepts_one_twice(accounts: dict[str, int], db: str) -> None:
    with client() as c:
        login(c, OWNER, OWNER_PW)
        secret, codes, _ = enroll(c)
        c.post("/api/v1/auth/logout")
        me = login(c, OWNER, OWNER_PW)
        assert me["stage"] == "mfa" and me["mfa_enabled"]
        assert c.get("/api/v1/home").json()["error"]["code"] == "mfa_required"
        used = totp.code_at(secret, last_step(db, accounts["owner"]))
        replay = c.post("/api/v1/auth/mfa/verify", json={"code": used})
        assert replay.status_code == 401 and replay.json()["error"]["code"] == "invalid_code"
        ok = c.post("/api/v1/auth/mfa/verify", json={"code": code(secret, after=last_step(db, accounts["owner"]))})
        assert ok.status_code == 200 and ok.json()["stage"] == "full"
        assert c.get("/api/v1/home").status_code == 200
        # a recovery code works once, in place of a code
        c.post("/api/v1/auth/logout")
        login(c, OWNER, OWNER_PW)
        r = c.post("/api/v1/auth/mfa/verify", json={"recovery_code": codes[0].upper()})
        assert r.status_code == 200 and r.json()["recovery_codes_left"] == 9
        c.post("/api/v1/auth/logout")
        login(c, OWNER, OWNER_PW)
        again = c.post("/api/v1/auth/mfa/verify", json={"recovery_code": codes[0]})
        assert again.status_code == 401
    with psycopg.connect(db) as conn:
        actions = {r[0] for r in conn.execute("SELECT action FROM auth.audit_events").fetchall()}
    assert {"login.password_ok", "mfa.enrolled", "mfa.verified", "mfa.failed", "mfa.recovery_code_used",
            "login.succeeded"} <= actions


def test_wrong_codes_end_the_staged_session_and_lock_the_account(accounts: dict[str, int], db: str) -> None:
    with client() as c:
        login(c, OWNER, OWNER_PW)
        secret, _, _ = enroll(c)
        c.post("/api/v1/auth/logout")
        login(c, OWNER, OWNER_PW)
        for left in (4, 3, 2, 1):
            r = c.post("/api/v1/auth/mfa/verify", json={"code": "123456"})
            assert r.status_code == 401 and r.json()["error"]["attempts_left"] == left
        r = c.post("/api/v1/auth/mfa/verify", json={"code": "123456"})
        assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"
        assert int(r.headers["retry-after"]) > 0
        assert c.get("/api/v1/auth/me").status_code == 401
        # five failures in a row lock the ACCOUNT (in the database): even the right password and code wait
        throttle.reset_all()
        locked = c.post("/api/v1/auth/login", json={"email": OWNER, "password": OWNER_PW})
        assert locked.status_code == 429 and locked.json()["error"]["code"] == "too_many_attempts"
    with psycopg.connect(db) as conn:
        row = conn.execute("SELECT failed_logins, locked_until > now() FROM auth.users WHERE id = %s",
                           (accounts["owner"],)).fetchone()
        assert row == (5, True)
        assert conn.execute("SELECT count(*) FROM auth.audit_events WHERE action = 'login.locked'").fetchone() == (1,)
        conn.execute("UPDATE auth.users SET failed_logins = 0, locked_until = NULL WHERE id = %s",
                     (accounts["owner"],))
        conn.commit()
    with client() as c:
        login(c, OWNER, OWNER_PW)
        assert c.post("/api/v1/auth/mfa/verify",
                      json={"code": code(secret, after=last_step(db, accounts["owner"]))}).status_code == 200


def test_wrong_passwords_lock_the_account_across_processes_until_the_owner_unlocks_it(
        accounts: dict[str, int], db: str) -> None:
    with client() as c:
        for _ in range(5):
            assert c.post("/api/v1/auth/login", json={"email": FAN, "password": "Wrong-pass-2026"}).status_code == 401
        throttle.reset_all()  # another API process: nothing in its memory
        r = c.post("/api/v1/auth/login", json={"email": FAN, "password": FAN_PW})
        assert r.status_code == 429 and r.json()["error"]["retry_after"] > 800
    with client() as owner:
        login(owner, OWNER, OWNER_PW)
        enroll(owner)
        listed = {u["email"]: u for u in owner.get("/api/v1/admin/users").json()["data"]}
        assert listed[FAN]["locked_until"] is not None and listed[FAN]["failed_logins"] == 5
        unlocked = owner.post(f"/api/v1/admin/users/{accounts['fan']}/unlock").json()["data"]
        assert unlocked["locked_until"] is None and unlocked["failed_logins"] == 0
    with client() as c:
        assert login(c, FAN, FAN_PW)["stage"] == "full"


def test_an_account_the_owner_creates_or_resets_must_choose_its_own_password(accounts: dict[str, int]) -> None:
    with client() as owner:
        login(owner, OWNER, OWNER_PW)
        enroll(owner)
        created = owner.post("/api/v1/admin/users", json={"email": "new.reader@predigol.test",
                                                           "password": "Given-by-owner-26", "role": "USER"})
        assert created.status_code == 201 and created.json()["data"]["must_change_password"]
        new_id = created.json()["data"]["id"]
        with client() as reader:
            me = login(reader, "new.reader@predigol.test", "Given-by-owner-26")
            assert me["stage"] == "password"
            assert reader.get("/api/v1/home").json()["error"]["code"] == "password_change_required"
            same = reader.post("/api/v1/auth/password/required", json={"new_password": "Given-by-owner-26"})
            assert same.status_code == 422 and "password_reused" in same.json()["error"]["problems"]
            weak = reader.post("/api/v1/auth/password/required", json={"new_password": "short"})
            assert weak.status_code == 422
            done = reader.post("/api/v1/auth/password/required", json={"new_password": "My-own-pass-2026"})
            assert done.status_code == 200 and done.json()["stage"] == "full"
            assert reader.get("/api/v1/home").status_code == 200
            # the owner resets it: a generated password, shown once; the reader's session ends
            reset = owner.post(f"/api/v1/admin/users/{new_id}/password", json={}).json()["data"]
            temporary = reset["temporary_password"]
            assert len(temporary) == 16 and reset["user"]["must_change_password"]
            assert reader.get("/api/v1/auth/me").status_code == 401
            assert login(reader, "new.reader@predigol.test", temporary)["stage"] == "password"
        audit = owner.get("/api/v1/admin/audit?action=password.reset").text
        assert temporary not in audit and "Given-by-owner-26" not in audit


def test_a_lost_phone_reset_by_the_owner_means_a_new_enrolment(accounts: dict[str, int], db: str) -> None:
    with client() as owner:
        login(owner, OWNER, OWNER_PW)
        enroll(owner)
        promoted = owner.patch(f"/api/v1/admin/users/{accounts['fan']}", json={"role": "SUPER_ADMIN"}).json()["data"]
        assert promoted["mfa_required"] and not promoted["mfa_enabled"]
        with client() as second:
            assert login(second, FAN, FAN_PW)["stage"] == "enroll"
            enroll(second)
            assert second.get("/api/v1/admin/overview").status_code == 200
            reset = owner.post(f"/api/v1/admin/users/{accounts['fan']}/mfa/reset").json()["data"]
            assert not reset["mfa_enabled"] and reset["recovery_codes_left"] == 0
            assert second.get("/api/v1/auth/me").status_code == 401
            assert login(second, FAN, FAN_PW)["stage"] == "enroll"
        # a SUPER_ADMIN cannot switch the second factor off
        refused = owner.post("/api/v1/auth/me/mfa/disable", json={"password": OWNER_PW, "code": "000000"})
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "mfa_required_by_policy"


def test_a_user_can_turn_a_second_factor_on_and_off_with_password_and_code(
        accounts: dict[str, int], db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_900_000_000.0]
    monkeypatch.setattr(totp, "_clock", lambda: clock[0])
    with client() as a, client() as b:
        assert login(a, FAN, FAN_PW)["stage"] == "full"
        login(b, FAN, FAN_PW)
        refused = a.post("/api/v1/auth/mfa/enroll/start", json={"password": "Wrong-pass-2026"})
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "wrong_password"
        secret, _, me = enroll(a, password=FAN_PW)
        assert me["mfa_enabled"] and me["stage"] == "full"
        assert b.get("/api/v1/auth/me").status_code == 401  # sessions from before the second factor end
        clock[0] += 60  # each code is good once: the next ones come from later 30-second steps
        renewed = a.post("/api/v1/auth/me/mfa/recovery-codes",
                         json={"password": FAN_PW, "code": code(secret, after=last_step(db, accounts["fan"]))})
        assert renewed.status_code == 200 and len(renewed.json()["recovery_codes"]) == 10
        no_code = a.post("/api/v1/auth/me/mfa/disable", json={"password": FAN_PW})
        assert no_code.status_code == 401 and no_code.json()["error"]["code"] == "invalid_code"
        clock[0] += 60
        off = a.post("/api/v1/auth/me/mfa/disable",
                     json={"password": FAN_PW, "code": code(secret, after=last_step(db, accounts["fan"]))})
        assert off.status_code == 204
        assert not a.get("/api/v1/auth/me").json()["mfa_enabled"]


def test_my_sessions_and_my_sign_in_history(accounts: dict[str, int]) -> None:
    with client() as a, client() as b:
        login(a, FAN, FAN_PW)
        login(b, FAN, FAN_PW)
        a.post("/api/v1/auth/login", json={"email": FAN, "password": "Wrong-pass-2026"})
        login(a, FAN, FAN_PW)
        sessions = a.get("/api/v1/auth/me/sessions").json()
        assert len(sessions) == 3 and sum(s["current"] for s in sessions) == 1
        assert all(len(s["id"]) == 16 for s in sessions)
        other = next(s for s in sessions if not s["current"])
        assert a.post(f"/api/v1/auth/me/sessions/{other['id']}/revoke").status_code == 204
        assert a.post("/api/v1/auth/me/sessions/revoke-others").json()["revoked"] == 1
        assert b.get("/api/v1/auth/me").status_code == 401
        assert len(a.get("/api/v1/auth/me/sessions").json()) == 1
        history = a.get("/api/v1/auth/me/access").json()
        actions = [h["action"] for h in history]
        assert "login.succeeded" in actions and "login.failed" in actions and "session.revoked" in actions
        assert a.post("/api/v1/auth/me/sessions/zzzz/revoke").status_code == 422


def test_admin_writes_are_audited_and_limits_hold(accounts: dict[str, int], db: str,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    with client() as owner:
        login(owner, OWNER, OWNER_PW)
        enroll(owner)
        r = owner.post("/api/v1/admin/evolution/hypotheses",
                       json={"title": "Audit me", "hypothesis": "h", "rationale": "r"})
        assert r.status_code in (200, 201, 422), r.text
        with psycopg.connect(db) as conn:
            row = conn.execute("SELECT detail FROM auth.audit_events WHERE action = 'admin.write' "
                               "ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None and row[0]["path"] == "/api/v1/admin/evolution/hypotheses"
        assert row[0]["method"] == "POST" and row[0]["status"] == r.status_code
        # a body over the limit never reaches the application
        big = owner.post("/api/v1/auth/login", content=b"{" + b" " * (300 * 1024) + b"}",
                         headers={"content-type": "application/json"})
        assert big.status_code == 413
    # per-account request limit
    from fbi.api import security
    from fbi.api.limits import SlidingWindow

    monkeypatch.setattr(security, "USER_LIMIT", SlidingWindow(per_window=3, window_s=60))
    with client() as c:
        login(c, FAN, FAN_PW)
        codes = [c.get("/api/v1/auth/me").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
