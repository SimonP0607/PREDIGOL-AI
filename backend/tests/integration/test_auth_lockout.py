"""The sign-in lock says the truth and says the same with or without an account (plan UX, A1, defect F01; R12).

The audit found two faults. The failure that locked an account answered 401 "invalid credentials", as if nothing had
happened, and only the next attempt learned of a lock; and the page always said "wait 60 s" whatever the real lock
was (15 minutes, doubling). Worse for privacy, an address with an account and one without did not lock alike: the
account's lock lives in the database and doubles with every further block of failures, the window of an unknown
address did not, so the answers told an attacker which addresses have accounts.

From A1 the failure that reaches the threshold answers 429 too_many_attempts with the real wait (Retry-After and
error.retry_after, in seconds), and every address - with or without an account - follows the account's rule: the
threshold of consecutive failures, then lock_minutes, doubling with every further block of failures, up to
lock_max_minutes. The streak of every address is read from the audit trail in the database, which records each
failure with its address: the API runs two worker processes (deploy/vps/docker-compose.yml) and restarts, and a
count kept in one process's memory would lock an address without an account later than one with (review of A1).
The account's own counters follow the same streak; the owner's unlock ends both.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from tests.integration.helpers import forget_sign_in_failures

KNOWN = "member@predigol.test"
UNKNOWN = "nobody-here@predigol.test"
OWNER = "keeper@predigol.test"
OWNER_PW = "Keeper-pass-2026!"
PASSWORD = "Member-pass-2026"
WRONG = "Wrong-pass-2026!"
SAME_SITE = {"x-requested-with": "predigol"}
LOCK_S = 15 * 60  # FBI_AUTH_LOCK_MINUTES, default


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_API_LOGIN_RATE_LIMIT", "1000")  # the per-minute limit of the API is not what this file tests
    mp.setenv("FBI_AUTH_MFA_ROLES", "")  # the owner signs in with the password alone here (test_auth_mfa.py: MFA)
    reset_cache()
    reset_session_settings()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    service.create_user_unattended(email=KNOWN, display_name="Member", role="USER", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    service.create_user_unattended(email=OWNER, display_name="Keeper", role="SUPER_ADMIN", password=OWNER_PW,
                                   language="es", timezone="Europe/Madrid")
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    mp.undo()
    reset_cache()
    reset_session_settings()


class Clock:
    """The per-client window of the throttle on a clock the test moves (the streaks are moved with SQL)."""

    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def client(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Clock]]:
    throttle.reset_all()
    clock = Clock()
    monkeypatch.setattr(throttle.BY_CLIENT, "_clock", clock)
    forget_sign_in_failures()
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
    """Let `seconds` pass: for the audit trail the streaks are read from, the accounts' rows and the per-client
    window."""
    clock.t += seconds
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE auth.audit_events SET at = at - make_interval(secs => %s)", (seconds,))
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


def test_the_lock_holds_in_every_api_process_and_after_a_restart(client: tuple[TestClient, Clock]) -> None:
    """The API runs two worker processes, and restarts: a lock kept in one process's memory locked an address
    without an account later than one with (review of A1: 8 failures against 5 with the attempts spread over two
    workers). The streak is in the database now; a process with nothing in its memory answers the same."""
    c, _ = client
    for email in (KNOWN, UNKNOWN):
        for _ in range(4):
            assert attempt(c, email)[0] == 401
            throttle.reset_all()  # the next attempt reaches the other process, or a restarted one
        status, wait = attempt(c, email)
        assert status == 429 and near(wait, LOCK_S), (email, status, wait)
        throttle.reset_all()
        status, left = attempt(c, email, PASSWORD)
        assert status == 429 and left is not None, (email, status)


def test_the_owners_unlock_lets_the_account_in_at_once(database: str, client: tuple[TestClient, Clock]) -> None:
    """The owner's Unlock cleared the account's row while the lock in the API's memory went on - up to a day once
    it had doubled (review of A1). It now ends the streak itself: the right password works at once."""
    c, _ = client
    for _ in range(5):
        attempt(c, KNOWN)
    assert attempt(c, KNOWN, PASSWORD)[0] == 429
    from fbi.api.app import create_app

    with TestClient(create_app(), headers=SAME_SITE) as owner:
        assert owner.post("/api/v1/auth/login", json={"email": OWNER, "password": OWNER_PW}).status_code == 200
        user_id = next(u["id"] for u in owner.get("/api/v1/admin/users").json()["data"] if u["email"] == KNOWN)
        assert owner.post(f"/api/v1/admin/users/{user_id}/unlock").status_code == 200
    assert attempt(c, KNOWN, PASSWORD) == (200, None)


def test_a_right_password_with_a_second_step_owed_does_not_end_the_streak(
        database: str, client: tuple[TestClient, Clock]) -> None:
    """Only a finished sign-in ends a streak, as it ends the account's count: a right password that still owes a
    step (here a new password: a staged session) leaves it as it was."""
    c, _ = client
    for _ in range(4):
        assert attempt(c, KNOWN) == (401, None)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET must_change_password = true WHERE email = %s", (KNOWN,))
    try:
        r = c.post("/api/v1/auth/login", json={"email": KNOWN, "password": PASSWORD})
        assert r.status_code == 200 and r.json()["stage"] == "password"
        assert attempt(c, KNOWN)[0] == 429, "the fifth failure still locks"
    finally:
        with psycopg.connect(database, autocommit=True) as conn:
            conn.execute("UPDATE auth.users SET must_change_password = false WHERE email = %s", (KNOWN,))


def test_a_refusal_while_locked_writes_nothing_and_the_streak_is_read_through_its_index(
        database: str, client: tuple[TestClient, Clock]) -> None:
    """The attempts of a locked address cannot grow the trail (second review of A1: every attempt read thirty days
    of it, and every refusal wrote a row), and the streak is read through the index of revision 0094."""
    c, _ = client
    for _ in range(5):
        attempt(c, UNKNOWN)
    with psycopg.connect(database) as conn:
        before = conn.execute("SELECT count(*) FROM auth.audit_events").fetchone()
    for _ in range(20):
        assert attempt(c, UNKNOWN)[0] == 429
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM auth.audit_events").fetchone() == before
        from fbi.auth.store import ADDRESS_STREAK_SQL

        conn.execute("SET enable_seqscan = off")
        plan = "\n".join(r[0] for r in conn.execute("EXPLAIN " + ADDRESS_STREAK_SQL,
                                                     {"a": UNKNOWN, "h": 30}).fetchall())
    assert "audit_events_signin_idx" in plan, plan


def test_parallel_failures_of_one_address_are_decided_one_at_a_time(client: tuple[TestClient, Clock]) -> None:
    """Five wrong passwords sent at once: the streak is read under a lock of the address, so exactly one of them is
    the fifth and locks (review of A1: each read the streak before the others' failures were written)."""
    from concurrent.futures import ThreadPoolExecutor

    from fbi.api.app import create_app

    def one(_: int) -> int:
        with TestClient(create_app(), headers=SAME_SITE) as each:
            return each.post("/api/v1/auth/login", json={"email": UNKNOWN, "password": WRONG}).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = sorted(pool.map(one, range(5)))
    assert statuses == [401, 401, 401, 401, 429], statuses


def test_below_the_threshold_the_account_is_not_locked_whatever_it_was(database: str,
                                                                       client: tuple[TestClient, Clock]) -> None:
    """The account's lock is the streak's (second review of A1: a lock stored on the row outlived the streak and
    answered where an address without an account did not)."""
    c, _ = client
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET locked_until = now() + interval '8 hours' WHERE email = %s", (KNOWN,))
    assert attempt(c, KNOWN)[0] == 401, "the streak (1) decides, not a lock left on the row"
    with psycopg.connect(database) as conn:
        row = conn.execute("SELECT failed_logins, locked_until FROM auth.users WHERE email = %s", (KNOWN,)).fetchone()
    assert row == (1, None)
