"""The daily request budget, in the database rather than in process memory.

There are two different daily limits and confusing them is expensive:

  * the PROVIDER's limit (free plan: 100/day) is enforced by the provider. We
    cannot see its counter except by asking ``/status``, and it does not count
    requests it refused.
  * OUR budget (``FBI_APIFOOTBALL_DAILY_BUDGET``, 60) is enforced here. It sits
    below the provider's on purpose, so a runaway job cannot spend a whole
    day's quota in one afternoon, and it counts every request ISSUED - refused
    ones included, because the request left the building either way.

This module enforces the second one. ``DailyQuota`` in ``ratelimit`` keeps the
same interface in memory and is still what unit tests use; the difference is
that this one survives the process.

Why not just sum ``raw.ingestion_runs.api_calls``? Because a run records its
calls when it CLOSES. Two runs in flight would both read the same total and
both spend the whole budget, which is exactly the hole being closed here - and
a run killed mid-flight never records its calls at all. So the counter is
incremented before each request, in its own committed transaction, and the
ledger sum is kept beside it as a cross-check: ``QuotaUsage.unattributed``
reports requests no closed run has claimed.

The atomicity that makes this work across processes is one statement:

    UPDATE raw.provider_quota SET spent = spent + n
     WHERE ... AND spent + n <= budget RETURNING spent

PostgreSQL takes a row lock, so a concurrent updater waits and then
re-evaluates its WHERE against the committed new value. The loser gets zero
rows back, which is a refusal - not a silent overspend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import psycopg
import structlog

from fbi.core.clock import day_start, now
from fbi.core.errors import QuotaExhaustedError

log = structlog.get_logger(__name__)

DEFAULT_PROVIDER = "api_football"

_ENSURE_ROW = """
INSERT INTO raw.provider_quota (provider, quota_date, spent, budget)
SELECT %(provider)s, %(day)s,
       coalesce((SELECT sum(api_calls) FROM raw.ingestion_runs
                  WHERE started_at >= %(day_start)s), 0),
       %(budget)s
ON CONFLICT (provider, quota_date) DO NOTHING
"""
"""Create the day's row once, seeded from whatever the ledger already recorded
today so a mid-day deploy does not forget the morning's requests."""

_SPEND = """
UPDATE raw.provider_quota
   SET spent = spent + %(calls)s, budget = %(budget)s, updated_at = now()
 WHERE provider = %(provider)s AND quota_date = %(day)s
   AND spent + %(calls)s <= %(budget)s
RETURNING spent
"""

_READ = """
SELECT spent, budget FROM raw.provider_quota
 WHERE provider = %(provider)s AND quota_date = %(day)s
"""

_LEDGER_SUM = """
SELECT coalesce(sum(api_calls), 0) FROM raw.ingestion_runs WHERE started_at >= %(day_start)s
"""


@dataclass(frozen=True, slots=True)
class QuotaUsage:
    """What the budget looks like right now, read without spending anything."""

    quota_date: date
    spent: int
    budget: int
    ledger_api_calls: int
    """``sum(api_calls)`` for today from raw.ingestion_runs, for comparison."""

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    @property
    def unattributed(self) -> int:
        """Requests billed here that no CLOSED run has claimed.

        Three innocent reasons and one bad one, which is why this is a number
        and not an alarm:

          * ``/status`` and other ad-hoc calls do not open a ledger run at all;
          * a run still in flight has not written its total yet;
          * a run that died never will - the bad one.

        Only the third is a fault, and ``stale_running_jobs`` in /health is the
        check that identifies it. Treating this figure as a fault on its own
        made a plain ``capture_odds status`` degrade the health of the system,
        which is a false alarm, and a health check that cries wolf is worse
        than one that says nothing.

        Negative should be impossible: it would mean something reached the
        provider without passing through this counter.
        """
        return self.spent - self.ledger_api_calls

    def as_dict(self) -> dict[str, object]:
        return {
            "quota_date": self.quota_date.isoformat(),
            "requests_today": self.spent,
            "daily_budget": self.budget,
            "remaining": self.remaining,
            "ledger_api_calls_today": self.ledger_api_calls,
            "unattributed_requests": self.unattributed,
        }


def read_usage(conn: psycopg.Connection, *, budget: int, provider: str = DEFAULT_PROVIDER) -> QuotaUsage:
    """Read-only, on a connection the caller already owns.

    Used by /health, the quality snapshot and ``capture_odds status``, none of
    which may spend a request to find out how many have been spent. When the
    day's row does not exist yet, the ledger sum stands in for it: that is the
    number the row would be seeded with.
    """
    today = now().date()
    params = {"provider": provider, "day": today, "day_start": day_start()}
    with conn.cursor() as cur:
        cur.execute(_LEDGER_SUM, params)
        row = cur.fetchone()
        ledger = int(row[0]) if row else 0
        cur.execute(_READ, params)
        row = cur.fetchone()
    if row is None:
        return QuotaUsage(quota_date=today, spent=ledger, budget=budget, ledger_api_calls=ledger)
    return QuotaUsage(quota_date=today, spent=int(row[0]), budget=budget, ledger_api_calls=ledger)


class PersistentDailyQuota:
    """A daily budget that holds across processes, restarts and CLI runs.

    Interface-compatible with ``DailyQuota`` so the provider client does not
    care which one it was given.

    Each operation uses its own short-lived autocommit connection. That is
    deliberate: spending must not join the caller's transaction, because a
    rollback of the caller's work must NOT un-spend a request that really was
    sent. It also keeps this off whatever locks the caller is holding.
    """

    def __init__(
        self,
        *,
        budget: int,
        connect: Callable[[], psycopg.Connection],
        provider: str = DEFAULT_PROVIDER,
    ) -> None:
        if budget < 1:
            raise ValueError("the daily budget must be at least 1 request")
        self.budget = budget
        self._connect = connect
        self._provider = provider

    # -- reading -----------------------------------------------------------
    def usage(self) -> QuotaUsage:
        with self._connect() as conn:
            return read_usage(conn, budget=self.budget, provider=self._provider)

    @property
    def spent(self) -> int:
        return self.usage().spent

    @property
    def remaining(self) -> int:
        return self.usage().remaining

    # -- spending ----------------------------------------------------------
    def spend(self, calls: int = 1) -> None:
        """Reserve ``calls`` requests, or refuse.

        Raises ``QuotaExhaustedError`` without spending anything if the budget
        cannot absorb them. The check and the increment are the same statement,
        so two processes racing for the last request cannot both win it.
        """
        if calls < 1:
            raise ValueError("cannot spend fewer than one request")
        if calls > self.budget:
            raise QuotaExhaustedError(
                f"a single reservation of {calls} requests cannot fit in a daily "
                f"budget of {self.budget}"
            )
        params = {
            "provider": self._provider,
            "day": now().date(),
            "day_start": day_start(),
            "budget": self.budget,
            "calls": calls,
        }
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(_ENSURE_ROW, params)
            cur.execute(_SPEND, params)
            row = cur.fetchone()
            if row is None:
                cur.execute(_READ, params)
                current = cur.fetchone()
                spent = int(current[0]) if current else self.budget
                raise QuotaExhaustedError(
                    f"daily budget of {self.budget} requests exhausted ({spent} spent "
                    f"today, {calls} more requested). The capturer stops instead of "
                    f"issuing calls it has no budget for. This count is shared by every "
                    f"process, so waiting for a different shell will not help - it "
                    f"resets at UTC midnight."
                )
            log.debug("quota.spent", calls=calls, spent=int(row[0]), budget=self.budget)

    def can_afford(self, planned: int) -> bool:
        """Pre-flight, no reservation: would ``planned`` requests fit?

        The guard the operator sees before a plan runs:
        ``requests_used_today + planned <= internal_daily_budget``.
        """
        return self.usage().remaining >= planned


class RunCappedQuota:
    """A per-run ceiling on top of the persistent daily budget.

    ``--max-requests 5`` means "spend at most five more requests in THIS run",
    which is a different thing from "today's budget is five". Conflating them
    is what the in-memory quota used to do, and with a persistent counter it
    would be actively wrong: today already has requests on it, so a budget of
    five would refuse the very first call.

    So there are two gates and a request needs both. The cap is local and
    forgotten when the process ends; the daily budget is shared and durable.
    The local one is checked first because it costs nothing to check, and if
    the durable one then refuses, nothing has been spent on either.
    """

    def __init__(self, inner: PersistentDailyQuota, *, max_requests: int) -> None:
        if max_requests < 1:
            raise ValueError("a run cap below one request would do nothing at all")
        self._inner = inner
        self._cap = max_requests
        self._spent_here = 0

    @property
    def budget(self) -> int:
        return self._inner.budget

    @property
    def cap(self) -> int:
        return self._cap

    @property
    def spent_this_run(self) -> int:
        return self._spent_here

    @property
    def spent(self) -> int:
        return self._inner.spent

    @property
    def remaining(self) -> int:
        """Whichever gate is tighter - that is what the caller can actually
        spend, and what the plan validator must be given."""
        return min(self._inner.remaining, self._cap - self._spent_here)

    def usage(self) -> QuotaUsage:
        return self._inner.usage()

    def spend(self, calls: int = 1) -> None:
        if self._spent_here + calls > self._cap:
            raise QuotaExhaustedError(
                f"run cap of {self._cap} request(s) reached ({self._spent_here} spent "
                f"in this run). This is the --max-requests ceiling, not the daily "
                f"budget; the daily budget still has {self._inner.remaining} left."
            )
        self._inner.spend(calls)
        self._spent_here += calls
