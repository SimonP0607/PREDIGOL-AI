"""The sign-in lock says the truth and says the same with or without an account (plan UX, A1, defect F01; R12).

The audit found two faults. The failure that locked an account answered 401 "invalid credentials", as if nothing had
happened, and only the next attempt learned of a lock; and the page always said "wait 60 s" whatever the real lock
was (15 minutes, doubling). Worse for privacy, an address with an account and one without did not lock alike: the
account's lock lives in the database and doubles with every further block of failures, the window of an unknown
address did not, so the answers told an attacker which addresses have accounts.

From A1 the failure that reaches the threshold answers 429 too_many_attempts with the real wait (Retry-After and
error.retry_after, in seconds), and every address - with or without an account - follows the account's rule: the
threshold of consecutive failures, then lock_minutes, doubling with every further block of failures, up to
lock_max_minutes. The rule is counted in the API's memory for every address; the account's lock in the database stays
too, for the next process. (A restart forgets the memory, while an account's database lock survives it: that last
difference goes away with the persistent counters of the security plan, S5.)
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache

KNOWN = "member@predigol.test"
UNKNOWN = "nobody-here@predigol.test"
PASSWORD = "Member-pass-2026"
WRONG = "Wrong-pass-2026!"
SAME_SITE = {"x-requested-with": "predigol"}
LOCK_S = 15 * 60  # FBI_AUTH_LOCK_MINUTES, default


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_API_LOGIN_RATE_LIMIT", "1000")  # the per-minute limit of the API is not what this file tests
    reset_cache()
    reset_session_settings()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    service.create_user_unattended(email=KNOWN, display_name="Member", role="USER", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    mp.undo()
    reset_cache()
    reset_session_settings()


class Clock:
    """The memory of the throttle on a clock the test moves (the database lock is moved with SQL)."""

    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def client(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Clock]]:
    throttle.reset_all()
    clock = Clock()
    for name in ("ADDRESSES", "BY_CLIENT"):
        if hasattr(throttle, name):  # (the rule per address is new in A1: before it, the test fails on the answers)
            monkeypatch.setattr(getattr(throttle, name), "_clock", clock)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET failed_logins = 0, locked_until = NULL")
    from fbi.api.app import create_app

    with TestClient(create_app(), headers=SAME_SITE) as c:
        yield c, clock
    throttle.reset_all()


def attempt(c: TestClient, email: str, password: str = WRONG) -> tuple[int, int | None]:
    """The status and the wait an attempt is answered with (the header and the body must agree)."""
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    if r.status_code != 429:
        assert "retry-after" not in r.headers
        return r.status_code, None
    body = r.json()["error"]
    assert body["code"] == "too_many_attempts"
    assert int(r.headers["retry-after"]) == body["retry_after"]
    return 429, int(body["retry_after"])


def expire(database: str, clock: Clock, seconds: float) -> None:
    """Let `seconds` pass for both locks: the API's memory and the account's row."""
    clock.t += seconds
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET locked_until = locked_until - make_interval(secs => %s) "
                     "WHERE locked_until IS NOT NULL", (seconds,))


def near(wait: int | None, expected: int) -> bool:
    return wait is not None and abs(wait - expected) <= 3


def test_the_failure_that_locks_answers_429_with_the_real_wait(client: tuple[TestClient, Clock]) -> None:
    c, _ = client
    for _ in range(4):
        assert attempt(c, KNOWN) == (401, None)
    status, wait = attempt(c, KNOWN)
    assert status == 429, "the fifth failure locks, and says so"
    assert near(wait, LOCK_S), wait
    # the right password waits too, with the time that is left
    status, left = attempt(c, KNOWN, PASSWORD)
    assert status == 429 and left is not None and wait is not None and left <= wait


def test_an_address_without_an_account_locks_exactly_alike(client: tuple[TestClient, Clock]) -> None:
    c, _ = client
    known = [attempt(c, KNOWN) for _ in range(6)]
    unknown = [attempt(c, UNKNOWN) for _ in range(6)]
    assert [s for s, _ in known] == [s for s, _ in unknown] == [401, 401, 401, 401, 429, 429]
    for (_, a), (_, b) in zip(known, unknown, strict=True):
        assert (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= 3), (known, unknown)


def test_the_wait_doubles_alike_with_every_further_block_of_failures(database: str,
                                                                     client: tuple[TestClient, Clock]) -> None:
    """Failures 5 to 9 lock for 15 minutes each, from the 10th on for 30: for the account, as its database row
    says, and for an address without one."""
    c, clock = client
    waits: dict[str, list[int | None]] = {KNOWN: [], UNKNOWN: []}
    for email in (KNOWN, UNKNOWN):
        for _ in range(4):
            assert attempt(c, email)[0] == 401
    for _ in range(6):  # failures 5..10, each after the previous lock has passed
        for email in (KNOWN, UNKNOWN):
            status, wait = attempt(c, email)
            assert status == 429
            waits[email].append(wait)
        expire(database, clock, LOCK_S * 2 + 5)
    for email in (KNOWN, UNKNOWN):
        assert all(near(w, LOCK_S) for w in waits[email][:5]), (email, waits[email])
        assert near(waits[email][5], 2 * LOCK_S), (email, waits[email])
    with psycopg.connect(database) as conn:
        row = conn.execute("SELECT failed_logins, extract(epoch FROM locked_until - now()) FROM auth.users "
                           "WHERE email = %s", (KNOWN,)).fetchone()
    assert row is not None and row[0] == 10, row
    assert abs(float(row[1]) + (LOCK_S * 2 + 5) - 2 * LOCK_S) <= 5, "the account's own lock agrees with the answer"


def test_after_the_lock_the_right_password_signs_in_and_starts_the_count_again(
        database: str, client: tuple[TestClient, Clock]) -> None:
    c, clock = client
    for _ in range(5):
        attempt(c, KNOWN)
    expire(database, clock, LOCK_S + 5)
    assert attempt(c, KNOWN, PASSWORD) == (200, None)
    for _ in range(4):
        assert attempt(c, KNOWN) == (401, None), "a fresh streak: four failures do not lock"
