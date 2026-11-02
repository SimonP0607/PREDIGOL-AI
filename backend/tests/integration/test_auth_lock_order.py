"""The sign-in streak's lock is always taken first, and every row that ends a streak carries its address (plan UX, A1;
third review of A1).

A sign-in holds the lock of its address (fbi.auth.store.lock_address) while it touches the account's row. A wrong
second-factor code locked the session and the account's rows FIRST and asked for the address's lock after: with a
sign-in of the same address in flight, each waited for the other and PostgreSQL aborted one - in practice the wrong
code, which was then never counted (500, its attempt and its failure rolled back), so somebody with the password could
guess codes without the lock ever engaging. The owner's unlock and password reset did not take the address's lock at
all: a failure that had read the streak before an unlock wrote its count after it, and locked the account again.

From the third review every transaction that reads or writes a streak or the account's lock takes the address's lock
first (fbi.auth.service._lock_streak_of), in the order a sign-in takes them, and the unlock and the reset are written
with their address, as every other row a streak is made of; the rows an account got without an address before A1 are
still read - through the NULL entries of the index of revision 0094, the same few old rows whatever the address.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, store, throttle, totp
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from tests.integration.helpers import forget_sign_in_failures

OWNER = "warden@predigol.test"
OWNER_PW = "Warden-pass-2026!"
KNOWN = "visitor@predigol.test"
PASSWORD = "Visitor-pass-2026"
WRONG = "Wrong-pass-2026!"
SAME_SITE = {"x-requested-with": "predigol"}


@pytest.fixture(scope="module")
def db(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_API_LOGIN_RATE_LIMIT", "1000")
    mp.delenv("FBI_AUTH_MFA_ROLES", raising=False)  # the production policy: a SUPER_ADMIN uses an authenticator
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


def client() -> TestClient:
    from fbi.api.app import create_app

    return TestClient(create_app(), headers=SAME_SITE, raise_server_exceptions=False)


def _code(secret: bytes, dsn: str, email: str) -> str:
    """A valid code newer than the last one the account used (codes are never accepted twice). These tests sign the
    owner in more often than every 30 seconds: the account's last step is moved back first - the replay rule is
    test_auth_mfa.py's subject, not this file's."""
    now = totp.step_at()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET totp_last_step = %s WHERE email = %s AND totp_last_step IS NOT NULL",
                     (now - 2, email))
    return totp.code_at(secret, now)


@pytest.fixture(scope="module")
def people(db: str) -> dict[str, Any]:
    """The owner with an authenticator, and a member."""
    throttle.reset_all()
    owner = service.create_user_unattended(email=OWNER, display_name="Warden", role="SUPER_ADMIN", password=OWNER_PW)
    member = service.create_user_unattended(email=KNOWN, display_name="Visitor", role="USER", password=PASSWORD)
    with client() as c:
        assert c.post("/api/v1/auth/login", json={"email": OWNER, "password": OWNER_PW}).json()["stage"] == "enroll"
        started = c.post("/api/v1/auth/mfa/enroll/start", json={}).json()
        raw = started["secret"].replace(" ", "")
        secret = base64.b32decode(raw + "=" * (-len(raw) % 8))
        done = c.post("/api/v1/auth/mfa/enroll/confirm", json={"code": _code(secret, db, OWNER)})
        assert done.status_code == 200, done.text
    return {"owner": int(owner["id"]), "member": int(member["id"]), "secret": secret}


@pytest.fixture()
def clean(db: str, people: dict[str, Any]) -> Iterator[dict[str, Any]]:
    throttle.reset_all()
    forget_sign_in_failures()
    yield people
    throttle.reset_all()


def owner_signed_in(db: str, people: dict[str, Any]) -> TestClient:
    c = client()
    c.__enter__()
    assert c.post("/api/v1/auth/login", json={"email": OWNER, "password": OWNER_PW}).json()["stage"] == "mfa"
    r = c.post("/api/v1/auth/mfa/verify", json={"code": _code(people["secret"], db, OWNER)})
    assert r.status_code == 200 and r.json()["stage"] == "full", r.text
    return c


class SignInInFlight:
    """A transaction that holds the lock of an address, as a sign-in does while it checks a password."""

    def __init__(self, db: str, address: str) -> None:
        self.conn = psycopg.connect(db)
        store.lock_address(self.conn, address)

    def row_is_free(self, email: str) -> bool:
        """Whether this transaction can lock the account's row at once, as a sign-in in flight must (to count a
        failure or a success on it)."""
        try:
            self.conn.execute("SAVEPOINT probe")
            self.conn.execute("SELECT 1 FROM auth.users WHERE email = %s FOR NO KEY UPDATE NOWAIT", (email,))
            self.conn.execute("RELEASE SAVEPOINT probe")
            return True
        except psycopg.errors.LockNotAvailable:
            self.conn.execute("ROLLBACK TO SAVEPOINT probe")
            return False

    def finish(self) -> None:
        self.conn.commit()
        self.conn.close()

    def abandon(self) -> None:
        if not self.conn.closed:
            self.conn.rollback()
            self.conn.close()


def waiting(future: Future[Any], seconds: float = 0.6) -> bool:
    time.sleep(seconds)
    return not future.done()


def test_a_wrong_code_waits_for_a_sign_in_in_flight_and_is_counted(db: str, clean: dict[str, Any]) -> None:
    """Before the third review the wrong code held the account's row while it waited for the address's lock: the
    sign-in in flight could not count on the row, PostgreSQL aborted the code with a deadlock (500) and its failure
    was never counted."""
    with client() as c:
        assert c.post("/api/v1/auth/login", json={"email": OWNER, "password": OWNER_PW}).json()["stage"] == "mfa"
        flight = SignInInFlight(db, OWNER)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                verdict = pool.submit(c.post, "/api/v1/auth/mfa/verify", json={"code": "000000"})
                assert waiting(verdict), "the wrong code waits for the sign-in in flight"
                assert flight.row_is_free(OWNER), "and holds no lock on the account while it waits"
                flight.finish()
                r = verdict.result(timeout=10)
        finally:
            flight.abandon()
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "invalid_code" and r.json()["error"]["attempts_left"] == 4
    with psycopg.connect(db) as conn:
        counted = conn.execute("SELECT count(*) FROM auth.audit_events WHERE action = 'mfa.failed' AND email = %s",
                               (OWNER,)).fetchone()
    assert counted == (1,), "the wrong code is counted"


def test_the_owners_unlock_waits_for_a_failure_in_flight(db: str, clean: dict[str, Any]) -> None:
    """Before the third review an unlock ran past a failure in flight, which then wrote its count over the unlock."""
    owner = owner_signed_in(db, clean)
    try:
        flight = SignInInFlight(db, KNOWN)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                unlocked = pool.submit(owner.post, f"/api/v1/admin/users/{clean['member']}/unlock")
                assert waiting(unlocked), "the unlock waits for the failure in flight"
                assert flight.row_is_free(KNOWN), "without holding the account's row"
                flight.finish()
                assert unlocked.result(timeout=10).status_code == 200
        finally:
            flight.abandon()
    finally:
        owner.__exit__(None, None, None)


def test_an_unlock_and_a_reset_are_written_with_their_address(db: str, clean: dict[str, Any],
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    with psycopg.connect(db) as conn:
        start = conn.execute("SELECT coalesce(max(id), 0) FROM auth.audit_events").fetchone()
    assert start is not None
    owner = owner_signed_in(db, clean)
    try:
        assert owner.post(f"/api/v1/admin/users/{clean['member']}/unlock").status_code == 200
        r = owner.post(f"/api/v1/admin/users/{clean['member']}/password", json={})
        assert r.status_code == 200, r.text
    finally:
        owner.__exit__(None, None, None)
    import sys

    from scripts import accounts

    monkeypatch.setattr(sys, "argv", ["accounts", "unlock", "--email", KNOWN])
    assert accounts.main() == 0
    with psycopg.connect(db) as conn:
        rows = conn.execute("SELECT action, email FROM auth.audit_events WHERE target_user_id = %s AND id > %s "
                            "AND action IN ('user.unlocked', 'password.reset') ORDER BY id",
                            (clean["member"], start[0])).fetchall()
    assert rows == [("user.unlocked", KNOWN), ("password.reset", KNOWN), ("user.unlocked", KNOWN)], rows
    service.set_password_unattended(email=KNOWN, password=PASSWORD)  # the member's own password again


def test_a_reset_written_without_an_address_before_a1_still_ends_the_streak(db: str, clean: dict[str, Any]) -> None:
    """The owner's unlock wrote no address before A1: it still ends the streak. Both halves of the streak are read
    through the index of revision 0094 - the second through its entries without an address, the same few old rows for
    an address with an account as for one without - and never through the index of every action of an account."""
    with client() as c:
        for _ in range(4):
            assert c.post("/api/v1/auth/login", json={"email": KNOWN, "password": WRONG}).status_code == 401
        with psycopg.connect(db, autocommit=True) as conn:
            conn.execute("INSERT INTO auth.audit_events (action, target_user_id, detail) VALUES "
                         "('user.unlocked', %s, '{\"by\": \"before A1\"}')", (clean["member"],))
        statuses = [c.post("/api/v1/auth/login", json={"email": KNOWN, "password": WRONG}).status_code
                    for _ in range(5)]
    assert statuses == [401, 401, 401, 401, 429], "a fresh streak after the unlock: the fifth failure locks"
    with psycopg.connect(db) as conn:
        conn.execute("SET enable_seqscan = off")
        plan = "\n".join(r[0] for r in conn.execute("EXPLAIN " + store.ADDRESS_STREAK_SQL,
                                                     {"a": KNOWN, "h": 30}).fetchall())
    assert plan.count("Index Scan using audit_events_signin_idx") == 2, plan
    assert "email IS NULL" in plan, "the second half: the rows without an address, by the index"
    assert "audit_events_target_idx" not in plan, "never the index of every action of the account"
