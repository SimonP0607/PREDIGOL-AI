"""The daily budget has to survive the process that spent it.

The hole this closes: ``DailyQuota`` counted in memory, so every CLI invocation
started again from zero and two shells could each spend the whole budget. The
decisive test here is not that one object remembers - it is that two separate
OPERATING SYSTEM PROCESSES racing for the last request cannot both get it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, day_start, set_clock
from fbi.core.errors import QuotaExhaustedError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.quota import PersistentDailyQuota, RunCappedQuota, read_usage
from tests.integration.helpers import scalar

NOW = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def dsn(migrated_database: str) -> Iterator[str]:
    """The real DSN, with the quota table emptied before and after.

    Committed writes, not a rolled-back transaction: a subprocess cannot see
    an uncommitted row, and seeing it is the whole point.
    """
    def clear() -> None:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DELETE FROM raw.provider_quota")
            conn.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN "
                         "(SELECT id FROM raw.ingestion_runs WHERE job_type = 'quota_test')")
            conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'quota_test'")

    clear()
    yield migrated_database
    clear()


def quota(dsn: str, budget: int) -> PersistentDailyQuota:
    """A quota object as a fresh CLI invocation would build one: its own
    connection factory, no shared state with any other instance."""
    return PersistentDailyQuota(
        budget=budget, connect=lambda: psycopg.connect(dsn, autocommit=True)
    )


# ---------------------------------------------------------------------------
# Across invocations
# ---------------------------------------------------------------------------

def test_a_second_invocation_sees_what_the_first_one_spent(dsn: str) -> None:
    first = quota(dsn, budget=10)
    first.spend(4)
    assert first.remaining == 6

    second = quota(dsn, budget=10)  # a new process would look exactly like this
    assert second.spent == 4, "restarting the CLI must not restart the budget"
    assert second.remaining == 6
    second.spend(6)
    assert quota(dsn, budget=10).remaining == 0


def test_the_budget_refuses_at_the_boundary_and_spends_nothing_doing_so(dsn: str) -> None:
    q = quota(dsn, budget=60)
    q.spend(59)
    with pytest.raises(QuotaExhaustedError, match="daily budget of 60"):
        q.spend(2)
    assert q.spent == 59, "a refused reservation must not consume anything"
    q.spend(1)
    assert q.spent == 60
    with pytest.raises(QuotaExhaustedError):
        q.spend(1)


def test_a_reservation_larger_than_the_whole_budget_is_refused_immediately(dsn: str) -> None:
    q = quota(dsn, budget=5)
    with pytest.raises(QuotaExhaustedError, match="cannot fit in a daily budget"):
        q.spend(6)
    assert q.spent == 0


def test_the_days_first_request_inherits_what_the_ledger_already_recorded(dsn: str) -> None:
    """A deploy in the middle of the day must not forget the morning.

    The counter row is created by the first spend of the day and seeded from
    raw.ingestion_runs, so requests made before this mechanism existed - or
    before the row was created - still count against the budget.
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        ledger = RunLedger(conn)
        run_id = ledger.open("quota_test")
        ledger.close(run_id, RunCounters(api_calls=13, rows_inserted=1))

    q = quota(dsn, budget=60)
    assert q.spent == 13, "the ledger stands in before the counter row exists"
    q.spend(1)
    assert q.spent == 14, "and is absorbed into it, not added twice"
    q.spend(1)
    assert q.spent == 15


def test_the_counter_resets_at_utc_midnight_and_not_before(dsn: str) -> None:
    clock = FrozenClock(NOW)
    set_clock(clock)
    try:
        q = quota(dsn, budget=10)
        q.spend(10)
        assert q.remaining == 0
        clock.advance(hours=15)  # 10:00 + 15h = 01:00 the next UTC day
        assert q.remaining == 10, "a new UTC day is a new row"
        q.spend(1)
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM raw.provider_quota")
            assert scalar(cur) == 2, "yesterday's row is kept, not overwritten"
    finally:
        set_clock(SystemClock())


def test_spending_survives_a_rollback_of_the_callers_transaction(dsn: str) -> None:
    """The request really was issued, so the budget really was spent. A quota
    that rode along inside the caller's transaction would hand the request back
    on rollback and let the same budget be spent twice."""
    q = quota(dsn, budget=10)
    caller = psycopg.connect(dsn)  # NOT autocommit: a normal working connection
    try:
        with caller.cursor() as cur:
            cur.execute("SELECT 1")
        q.spend(3)
        caller.rollback()
    finally:
        caller.close()
    assert quota(dsn, budget=10).spent == 3


# ---------------------------------------------------------------------------
# Across processes - the guarantee the block is about
# ---------------------------------------------------------------------------

CHILD = """
import os, sys
import psycopg
from fbi.core.errors import QuotaExhaustedError
from fbi.providers.quota import PersistentDailyQuota

dsn, budget, attempts = os.environ["Q_DSN"], int(os.environ["Q_BUDGET"]), int(os.environ["Q_ATTEMPTS"])
q = PersistentDailyQuota(budget=budget, connect=lambda: psycopg.connect(dsn, autocommit=True))
granted = 0
for _ in range(attempts):
    try:
        q.spend(1)
    except QuotaExhaustedError:
        break
    granted += 1
print("GRANTED=%d" % granted)
"""


def _granted(stdout: str) -> int:
    """The child also logs to stdout, so the answer carries a marker."""
    for line in stdout.splitlines():
        if line.startswith("GRANTED="):
            return int(line.removeprefix("GRANTED="))
    raise AssertionError(f"the child printed no GRANTED line:\n{stdout}")


def _child(dsn: str, budget: int, attempts: int) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "Q_DSN": dsn,
        "Q_BUDGET": str(budget),
        "Q_ATTEMPTS": str(attempts),
        "PYTHONPATH": os.pathsep.join([REPO_ROOT, os.path.join(REPO_ROOT, "src")]),
    }
    return subprocess.Popen(
        [sys.executable, "-c", CHILD],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO_ROOT,
    )


def test_two_independent_processes_cannot_jointly_exceed_the_budget(dsn: str) -> None:
    """The one that matters.

    Two processes, neither aware of the other, each trying to spend the entire
    budget at the same time. Between them they must be granted exactly the
    budget - not twice it, and not less than it either, because refusing
    requests we can afford would be its own bug.
    """
    budget = 20
    left, right = _child(dsn, budget, budget), _child(dsn, budget, budget)
    out_l, err_l = left.communicate(timeout=120)
    out_r, err_r = right.communicate(timeout=120)

    assert left.returncode == 0, f"child failed: {err_l}"
    assert right.returncode == 0, f"child failed: {err_r}"
    granted_l, granted_r = _granted(out_l), _granted(out_r)

    assert granted_l + granted_r == budget, (
        f"two processes were granted {granted_l} + {granted_r} = "
        f"{granted_l + granted_r} requests against a budget of {budget}"
    )
    assert granted_l > 0 and granted_r > 0, (
        "both processes should get some share; if one got everything the other "
        "never really contended and this test proves nothing"
    )

    with psycopg.connect(dsn, autocommit=True) as conn:
        usage = read_usage(conn, budget=budget)
    assert usage.spent == budget and usage.remaining == 0


def test_a_process_that_starts_after_the_budget_is_gone_gets_nothing(dsn: str) -> None:
    """The plain version of the same guarantee: a new shell is not a new
    budget, so "just run it again in another terminal" cannot work."""
    quota(dsn, budget=5).spend(5)
    child = _child(dsn, 5, 5)
    out, err = child.communicate(timeout=120)
    assert child.returncode == 0, err
    assert _granted(out) == 0


# ---------------------------------------------------------------------------
# The pre-flight guard and the per-run cap
# ---------------------------------------------------------------------------

def test_can_afford_answers_the_preflight_question_without_reserving(dsn: str) -> None:
    """requests_used_today + planned <= internal_daily_budget, asked before a
    plan runs and answered without spending anything."""
    q = quota(dsn, budget=10)
    q.spend(7)
    assert q.can_afford(3) is True
    assert q.can_afford(4) is False
    assert q.spent == 7, "asking must not reserve"


def test_the_run_cap_and_the_daily_budget_are_both_enforced(dsn: str) -> None:
    """``--max-requests 5`` means five more requests now, not a daily budget of
    five - which on a day with requests already spent would refuse everything."""
    quota(dsn, budget=60).spend(13)  # the day already has history

    capped = RunCappedQuota(quota(dsn, budget=60), max_requests=5)
    assert capped.remaining == 5, "the run cap is the tighter of the two"
    for _ in range(5):
        capped.spend(1)
    with pytest.raises(QuotaExhaustedError, match="run cap of 5"):
        capped.spend(1)
    assert capped.spent == 18, "the daily counter kept counting past the cap"
    assert capped.usage().remaining == 42


def test_the_daily_budget_still_wins_when_it_is_tighter_than_the_run_cap(dsn: str) -> None:
    quota(dsn, budget=10).spend(8)
    capped = RunCappedQuota(quota(dsn, budget=10), max_requests=5)
    assert capped.remaining == 2
    capped.spend(1)
    capped.spend(1)
    with pytest.raises(QuotaExhaustedError, match="daily budget of 10"):
        capped.spend(1)
    assert capped.spent_this_run == 2


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def test_a_run_that_died_without_closing_shows_up_as_drift(dsn: str) -> None:
    """The counter is ahead of the ledger. That is the signature of a crash:
    the requests were issued and billed, but the run never recorded them."""
    q = quota(dsn, budget=60)
    q.spend(4)
    with psycopg.connect(dsn, autocommit=True) as conn:
        RunLedger(conn).open("quota_test")  # opened, never closed
        usage = read_usage(conn, budget=60)
    assert usage.spent == 4
    assert usage.ledger_api_calls == 0
    assert usage.drift == 4


def test_the_two_counters_agree_when_a_run_closes_properly(dsn: str) -> None:
    q = quota(dsn, budget=60)
    with psycopg.connect(dsn, autocommit=True) as conn:
        ledger = RunLedger(conn)
        run_id = ledger.open("quota_test")
        for _ in range(3):
            q.spend(1)
        ledger.close(run_id, RunCounters(api_calls=3, rows_inserted=2))
        usage = read_usage(conn, budget=60)
    assert (usage.spent, usage.ledger_api_calls, usage.drift) == (3, 3, 0)


def test_usage_reports_the_day_it_is_counting(dsn: str) -> None:
    set_clock(FrozenClock(NOW))
    try:
        quota(dsn, budget=60).spend(1)
        with psycopg.connect(dsn, autocommit=True) as conn:
            usage = read_usage(conn, budget=60)
        assert usage.quota_date == NOW.date()
        assert usage.as_dict()["quota_date"] == "2026-09-20"
        assert day_start() == datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
    finally:
        set_clock(SystemClock())
