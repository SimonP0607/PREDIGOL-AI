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

import asyncio
import random
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg
import structlog

from fbi.core.clock import day_start, now
from fbi.core.errors import QuotaExhaustedError
from fbi.providers.lanes import LANE_OF_JOB, LaneDecision, LaneMode, LanePolicy
from fbi.providers.lanes import (
    NO_LANE as NO_LANE,  # re-exported: the readers of PM-01-02 import it from here
)

log = structlog.get_logger(__name__)

DEFAULT_PROVIDER = "api_football"

# ── what the provider itself says (plan Cuotas, BE-011; E18 of the plan) ─────────────────────────────────────────

DAY_LIMIT_HEADER = "x-ratelimit-requests-limit"
DAY_REMAINING_HEADER = "x-ratelimit-requests-remaining"
MINUTE_LIMIT_HEADER = "x-ratelimit-limit"
MINUTE_REMAINING_HEADER = "x-ratelimit-remaining"
"""API-Football's quota headers: the day (``x-ratelimit-requests-*``) and the minute (``X-RateLimit-*``). Names are read
case-insensitively (HTTP headers are)."""


@dataclass(frozen=True, slots=True)
class ReportedQuota:
    """What one answer's headers said of our quota; None for a header the provider did not send."""

    observed_at: datetime
    requests_limit: int | None
    requests_remaining: int | None
    minute_limit: int | None
    minute_remaining: int | None


def _header_int(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def parse_reported(headers: Mapping[str, str], *, at: datetime) -> ReportedQuota | None:
    """The provider's own count of our quota in one answer's headers (``httpx.Headers`` reads names in any case), or None when
    the answer carried none of them."""
    reported = ReportedQuota(observed_at=at, requests_limit=_header_int(headers, DAY_LIMIT_HEADER),
                             requests_remaining=_header_int(headers, DAY_REMAINING_HEADER),
                             minute_limit=_header_int(headers, MINUTE_LIMIT_HEADER),
                             minute_remaining=_header_int(headers, MINUTE_REMAINING_HEADER))
    known = (reported.requests_limit, reported.requests_remaining, reported.minute_limit, reported.minute_remaining)
    return reported if any(v is not None for v in known) else None


_REPORTED_UPSERT = """
INSERT INTO raw.provider_reported_quota AS q (provider, quota_date, observed_at, requests_limit, requests_remaining,
       minute_limit, minute_remaining)
VALUES (%(provider)s, %(day)s, %(at)s, %(rl)s, %(rr)s, %(ml)s, %(mr)s)
ON CONFLICT (provider, quota_date) DO UPDATE SET
       observed_at = EXCLUDED.observed_at,
       requests_limit = coalesce(EXCLUDED.requests_limit, q.requests_limit),
       requests_remaining = coalesce(EXCLUDED.requests_remaining, q.requests_remaining),
       minute_limit = coalesce(EXCLUDED.minute_limit, q.minute_limit),
       minute_remaining = coalesce(EXCLUDED.minute_remaining, q.minute_remaining)
 WHERE q.observed_at < EXCLUDED.observed_at
"""
"""The day's row holds the newest observation: an older one, arriving late from another process, changes nothing."""

_REPORTED_READ = """
SELECT quota_date, observed_at, requests_limit, requests_remaining, minute_limit, minute_remaining
  FROM raw.provider_reported_quota WHERE provider = %(provider)s AND quota_date = %(day)s
"""


def record_reported(conn: psycopg.Connection, reported: ReportedQuota, *, provider: str = DEFAULT_PROVIDER) -> None:
    """Keep the provider's count (``raw.provider_reported_quota``, migration 0129), on a connection the caller owns."""
    with conn.cursor() as cur:
        cur.execute(_REPORTED_UPSERT, {
            "provider": provider, "day": reported.observed_at.date(), "at": reported.observed_at,
            "rl": reported.requests_limit, "rr": reported.requests_remaining, "ml": reported.minute_limit,
            "mr": reported.minute_remaining})


def read_reported(conn: psycopg.Connection, *, provider: str = DEFAULT_PROVIDER,
                  day: date | None = None) -> ReportedQuota | None:
    """The provider's newest count of today (UTC), as its headers said it; None when no answer of the day carried one. Read only."""
    with conn.cursor() as cur:
        cur.execute(_REPORTED_READ, {"provider": provider, "day": day or now().date()})
        row = cur.fetchone()
    if row is None:
        return None
    return ReportedQuota(observed_at=row[1], requests_limit=row[2], requests_remaining=row[3], minute_limit=row[4],
                         minute_remaining=row[5])


class PersistentReportedQuota:
    """The client's sink for the provider's count: each observation is written on a short autocommit connection of its own,
    like the daily budget, so it never joins - nor waits on - the caller's transaction. A failure is logged, never raised: a
    header that could not be kept must not cost the request that brought it."""

    def __init__(self, *, connect: Callable[[], psycopg.Connection], provider: str = DEFAULT_PROVIDER) -> None:
        self._connect = connect
        self._provider = provider

    def __call__(self, reported: ReportedQuota) -> None:
        try:
            with self._connect() as conn:
                record_reported(conn, reported, provider=self._provider)
        except psycopg.Error as exc:
            log.warning("quota.reported_not_kept", error=type(exc).__name__)

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


MINUTE_SHARE = 0.8
"""The share of the plan's per-minute limit every process together may use."""

_MINUTE_SPEND = """
INSERT INTO raw.provider_minute_usage (provider, minute, spent) VALUES (%(provider)s, %(minute)s, %(n)s)
ON CONFLICT (provider, minute) DO UPDATE SET spent = raw.provider_minute_usage.spent + EXCLUDED.spent
 WHERE raw.provider_minute_usage.spent + EXCLUDED.spent <= %(limit)s
RETURNING spent
"""

_MINUTE_PRUNE = "DELETE FROM raw.provider_minute_usage WHERE provider = %(provider)s AND minute < %(before)s"


class PersistentMinuteLimiter:
    """The provider's per-minute limit, shared by every process (raw.provider_minute_usage, migration 0062).

    Each process used to keep its own token bucket at 90% of the limit, so two jobs at full speed went over it
    together: on 5 Oct 2026 at 02:46 UTC the provider answered "Too many requests ... per minute" during the
    historical backfill, while the reference feeds were also running, and a backfill unit was lost. The counter
    is one atomic statement per request, like the daily budget: a process that finds the minute full waits for
    the next one. Interface-compatible with ``TokenBucket.acquire``.
    """

    def __init__(self, *, limit: int, connect: Callable[[], psycopg.Connection], provider: str = DEFAULT_PROVIDER,
                 sleep: Callable[[float], Awaitable[None]] | None = None, summarize: bool = False) -> None:
        if limit < 1:
            raise ValueError("the per-minute limit must be at least 1 request")
        self.limit = limit
        self._connect = connect
        self._provider = provider
        self._sleep = sleep or asyncio.sleep
        self._summarize = summarize

    def try_spend(self, tokens: int = 1) -> bool:
        """Reserve ``tokens`` in the current minute, or refuse without spending.

        The first request of each hour (across every process) also prunes what is older than two days - and, with ``summarize``
        (plan PM, PM-01-02), keeps the day of yesterday and of today in ``raw.provider_minute_daily`` first, so the peaks outlive
        the 48 hours of the counter. A summary that cannot be written is logged, never raised: it must not cost the request."""
        moment = now()
        minute = moment.replace(second=0, microsecond=0)
        with self._connect() as conn:
            row = conn.execute(_MINUTE_SPEND, {"provider": self._provider, "minute": minute, "n": tokens,
                                               "limit": self.limit}).fetchone()
            if row is not None and int(row[0]) == tokens and minute.minute == 0:
                if self._summarize:
                    try:
                        summarize_minutes(conn, provider=self._provider, at=minute)
                    except psycopg.Error as exc:
                        log.warning("quota.minute_summary_not_kept", error=type(exc).__name__)
                conn.execute(_MINUTE_PRUNE, {"provider": self._provider, "before": minute - timedelta(days=2)})
        return row is not None

    async def acquire(self, tokens: int = 1) -> float:
        """Wait until the shared minute has room for ``tokens``. Returns the seconds waited."""
        if tokens > self.limit:
            raise ValueError(f"cannot acquire {tokens} requests in a minute limited to {self.limit}")
        waited = 0.0
        while not self.try_spend(tokens):
            moment = now()
            delay = 60.0 - moment.second - moment.microsecond / 1e6 + random.uniform(0.05, 1.5)
            log.info("quota.minute_full", limit=self.limit, wait_seconds=round(delay, 1))
            await self._sleep(delay)
            waited += delay
        return waited


# ── the daily summary of the per-minute counter (plan PM, PM-01-02, migration 0168) ─────────────────────────────────────────

_MINUTE_SUMMARY = """
INSERT INTO raw.provider_minute_daily AS d (provider, usage_date, minutes_active, requests, max_per_minute, peak_minute, p50, p95,
       p99, complete, computed_at)
SELECT %(provider)s, m.day, count(*), sum(m.spent), max(m.spent), (array_agg(m.minute ORDER BY m.spent DESC, m.minute))[1],
       percentile_cont(0.50) WITHIN GROUP (ORDER BY m.spent), percentile_cont(0.95) WITHIN GROUP (ORDER BY m.spent),
       percentile_cont(0.99) WITHIN GROUP (ORDER BY m.spent), m.day < %(today)s, now()
  FROM (SELECT (minute AT TIME ZONE 'UTC')::date AS day, minute, spent FROM raw.provider_minute_usage
         WHERE provider = %(provider)s AND minute >= %(since)s AND minute < %(until)s) m
 GROUP BY m.day
ON CONFLICT (provider, usage_date) DO UPDATE SET
       minutes_active = EXCLUDED.minutes_active, requests = EXCLUDED.requests, max_per_minute = EXCLUDED.max_per_minute,
       peak_minute = EXCLUDED.peak_minute, p50 = EXCLUDED.p50, p95 = EXCLUDED.p95, p99 = EXCLUDED.p99,
       complete = EXCLUDED.complete, computed_at = EXCLUDED.computed_at
 WHERE NOT d.complete OR EXCLUDED.requests >= d.requests
"""
"""Yesterday and today, from the minutes the counter still holds (48 h). Percentiles over the minutes WITH requests - the measure of
19 Nov 2026 (p95 = 85, max 202 over 450) was taken that way. A finished day is only rewritten by a count at least as large: once
the prune has begun to remove its first minutes, a late recomputation cannot shrink it."""


def summarize_minutes(conn: psycopg.Connection, *, provider: str = DEFAULT_PROVIDER, at: datetime | None = None) -> int:
    """Keep yesterday's and today's per-minute peaks (UTC) in ``raw.provider_minute_daily``; returns the days written."""
    moment = at or now()
    today = moment.date()
    since = moment.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(_MINUTE_SUMMARY, {"provider": provider, "today": today, "since": since, "until": since + timedelta(days=2)})
        return cur.rowcount


# ── requests by endpoint, lane and job (plan PM, PM-01-02, migration 0168) ──────────────────────────────────────────────────

NO_JOB = "sin_trabajo"
OTHER_ENDPOINT = "/otro"
USAGE_FLUSH_SECONDS = 60.0
"""The counts are added to the table at most this often per process (and on close): one statement a minute, not one per request."""
USAGE_MAX_KEYS = 5_000
"""A bound on what waits in memory (a day has a few dozen keys); a count beyond it is dropped and logged, never kept without limit."""

PROVISIONAL_LANES: Mapping[str, str] = LANE_OF_JOB
"""The lane of each job: since PM-04-01 (BE-060) the table of the lanes of the quota (``fbi.providers.lanes``), by the
``job_type`` the ledger records; it was the provisional table of PM-01-02 and keeps its name for the readers of then. A job not
listed counts under ``sin_carril``.

A job that knows its lane may still say so with ``bind_usage_lane(name)`` (it wins over this table). ``raw.provider_endpoint_usage``
keeps the ``job`` beside the ``lane``, so the history can be re-read under other lanes without asking the provider again. A lane is
``[a-z0-9_]``, at most 40 characters."""

_usage_job: ContextVar[str | None] = ContextVar("provider_usage_job", default=None)
_usage_lane: ContextVar[str | None] = ContextVar("provider_usage_lane", default=None)
_ENDPOINT = re.compile(r"/[a-z0-9_/-]{0,63}")
_TAG_CHARS = re.compile(r"[^a-z0-9_]+")


def _tag(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = _TAG_CHARS.sub("_", str(value).strip().lower()).strip("_")[:limit]
    return cleaned or None


def bind_usage_job(job: str | None) -> None:
    """The job whose requests follow in this task (``RunLedger.open`` calls it with the run's ``job_type``)."""
    _usage_job.set(_tag(job, limit=64))


def bind_usage_lane(lane: str | None) -> None:
    """The lane of the quota of the requests that follow in this task, when the job declares it (PM-04-01). None: from the job."""
    _usage_lane.set(_tag(lane, limit=40))


def current_usage_tags() -> tuple[str, str]:
    """(lane, job) of a request made now in this task: the declared lane, or the provisional one of the job, or ``sin_carril``."""
    job = _usage_job.get() or NO_JOB
    lane = _usage_lane.get() or PROVISIONAL_LANES.get(job, NO_LANE)
    return lane, job


def normalise_endpoint(endpoint: str) -> str:
    """``/fixtures`` for ``fixtures``, ``/Fixtures/`` or ``/fixtures?x=1``; ``/otro`` for anything that is not a plain path."""
    path = "/" + str(endpoint).split("?", 1)[0].strip().lower().strip("/")
    return path if _ENDPOINT.fullmatch(path) else OTHER_ENDPOINT


_USAGE_UPSERT = """
INSERT INTO raw.provider_endpoint_usage AS u (provider, usage_date, endpoint, lane, job, requests, first_at, updated_at)
SELECT %(provider)s, v.day, v.endpoint, v.lane, v.job, v.n, %(at)s, %(at)s
  FROM unnest(%(days)s::date[], %(endpoints)s::text[], %(lanes)s::text[], %(jobs)s::text[], %(counts)s::bigint[])
       WITH ORDINALITY AS v(day, endpoint, lane, job, n, i)
 ORDER BY v.i
ON CONFLICT (provider, usage_date, endpoint, lane, job) DO UPDATE SET
       requests = u.requests + EXCLUDED.requests, updated_at = EXCLUDED.updated_at
"""
"""One statement per flush. The keys arrive sorted, so two processes flushing the same keys lock them in the same order (no
deadlock); each adds its own count to the row (the row lock serialises them)."""

UsageKey = tuple[date, str, str, str]


class EndpointUsageCounter:
    """How many requests went to each endpoint, by UTC day, lane and job: counted in memory, added to ``raw.provider_endpoint_usage``
    at most every ``flush_every`` seconds and on ``flush()`` (the client's close, the process's exit).

    ``record`` is called by the client right after the daily budget accepted the request - the same place ``raw.provider_quota`` is
    spent, every attempt included - so a day's sum here matches that ledger. What could be lost is what a killed process had not yet
    flushed: at most a minute of its requests. Shared by every client of a process and by its threads (a lock); a flush that fails
    keeps the counts for the next one and is logged, never raised: counting must not cost the request."""

    def __init__(self, *, connect: Callable[[], psycopg.Connection], provider: str = DEFAULT_PROVIDER,
                 flush_every: float = USAGE_FLUSH_SECONDS, max_keys: int = USAGE_MAX_KEYS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._connect = connect
        self._provider = provider
        self._flush_every = flush_every
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[UsageKey, int] = {}
        self._last_flush = clock()
        self.dropped = 0

    @property
    def pending_requests(self) -> int:
        with self._lock:
            return sum(self._pending.values())

    def pending_by_lane(self, day: date) -> dict[str, int]:
        """What waits in memory for ``day``, by lane: the part of this process's requests the table does not hold yet."""
        out: dict[str, int] = {}
        with self._lock:
            for (d, _endpoint, lane, _job), n in self._pending.items():
                if d == day:
                    out[lane] = out.get(lane, 0) + n
        return out

    def record(self, endpoint: str, calls: int = 1) -> None:
        lane, job = current_usage_tags()
        key = (now().date(), normalise_endpoint(endpoint), lane, job)
        with self._lock:
            if key in self._pending or len(self._pending) < self._max_keys:
                self._pending[key] = self._pending.get(key, 0) + calls
            else:
                self.dropped += calls
            due = self._clock() - self._last_flush >= self._flush_every
        if due:
            self.flush()

    def _merge_back(self, batch: Mapping[UsageKey, int]) -> None:
        with self._lock:
            for key, n in batch.items():
                if key in self._pending or len(self._pending) < self._max_keys:
                    self._pending[key] = self._pending.get(key, 0) + n
                else:
                    self.dropped += n

    def flush(self) -> int:
        """Add what is pending to the table; returns the requests written (0 when nothing waited or the write failed)."""
        with self._lock:
            batch, self._pending = self._pending, {}
            self._last_flush = self._clock()
        if not batch:
            return 0
        keys = sorted(batch)
        params = {"provider": self._provider, "at": now(), "days": [k[0] for k in keys], "endpoints": [k[1] for k in keys],
                  "lanes": [k[2] for k in keys], "jobs": [k[3] for k in keys], "counts": [batch[k] for k in keys]}
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(_USAGE_UPSERT, params)
        except Exception as exc:  # the counts wait for the next flush; the request that triggered this one goes on
            self._merge_back(batch)
            log.warning("quota.endpoint_usage_not_kept", error=type(exc).__name__, pending=sum(batch.values()))
            return 0
        return sum(batch.values())


# ── the lanes of the budget (plan PM, PM-04-01; BE-060) ─────────────────────────────────────────────────────────────────────


class LaneLimitedError(QuotaExhaustedError):
    """A lane of the budget refused the request (``FBI_APIFOOTBALL_LANES=enforce``). A ``QuotaExhaustedError``, so every job that
    already stops when the day's budget is spent stops the same way - it has never been a reason to retry."""


_LANES_READ = """
SELECT lane, sum(requests)::bigint FROM raw.provider_endpoint_usage
 WHERE provider = %(provider)s AND usage_date = %(day)s GROUP BY lane
"""

LANES_REFRESH_SECONDS = 15.0
"""Today's counts by lane are read again at most this often per process. Between two reads the guard adds what it let through;
what another process sent and had not yet flushed (at most a minute of it) is not seen - a soft bound by design: the hard one, shared
and atomic, is still the daily budget."""
LANES_LOG_SECONDS = 600.0
"""A lane's ``quota.lane_would_limit`` / ``quota.lane_limited`` line is logged at most this often (the count goes on)."""


class LaneGuard:
    """The lanes of the budget in front of every request (PM-04-01): the client asks ``check()`` before it spends the daily budget.

    ``measure``: the decision is taken and counted, a refusal is only logged (``quota.lane_would_limit``) - nothing changes for any
    request. ``enforce``: a refusal raises ``LaneLimitedError``. It never waits: a request is let through or refused at once, so a
    match in play is never held behind anything. A count it cannot read lets the request through (logged): the guard's own failure
    never costs a request.

    Today's spending by lane comes from ``raw.provider_endpoint_usage`` (PM-01-02: the same place every request is counted, in the
    same lane) plus what this process's counter holds in memory, read at most every ``refresh_every`` seconds; it starts again at 00:00
    UTC with the day of the counter."""

    def __init__(self, *, policy: LanePolicy, mode: LaneMode, connect: Callable[[], psycopg.Connection],
                 counter: EndpointUsageCounter | None, provider: str = DEFAULT_PROVIDER,
                 refresh_every: float = LANES_REFRESH_SECONDS, log_every: float = LANES_LOG_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.policy = policy
        self.mode = mode
        self._connect = connect
        self._counter = counter
        self._provider = provider
        self._refresh_every = refresh_every
        self._log_every = log_every
        self._clock = clock
        self._lock = threading.Lock()
        self._day: date | None = None
        self._read_at: float | None = None
        self._spent: dict[str, int] = {}
        self._logged: dict[tuple[str, str], float] = {}
        self.would_limit: dict[str, int] = {}
        """Requests each lane would have refused since the process started (``measure``) or did refuse (``enforce``)."""

    def _read(self, day: date) -> dict[str, int] | None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(_LANES_READ, {"provider": self._provider, "day": day})
                rows = cur.fetchall()
        except Exception as exc:  # the guard's own failure never costs a request
            log.warning("quota.lanes_not_read", error=type(exc).__name__)
            return None
        spent = {str(lane): int(n) for lane, n in rows}
        if self._counter is not None:
            for lane, n in self._counter.pending_by_lane(day).items():
                spent[lane] = spent.get(lane, 0) + n
        return spent

    def spent_today(self) -> dict[str, int]:
        """Today's requests by lane as the guard sees them now (refreshed when due)."""
        day = now().date()
        moment = self._clock()
        with self._lock:
            due = self._day != day or self._read_at is None or moment - self._read_at >= self._refresh_every
        if due:
            fresh = self._read(day)
            with self._lock:
                if fresh is not None or self._day != day:
                    self._spent = fresh or {}
                    self._day = day
                self._read_at = moment
        with self._lock:
            return dict(self._spent)

    def check(self, calls: int = 1) -> LaneDecision:
        """The lane of the request made now in this task (``current_usage_tags``): let it through, or refuse it in ``enforce``."""
        lane, job = current_usage_tags()
        decision = self.policy.decide(lane, lane_spent=self.spent_today(), calls=calls)
        if not decision.allowed:
            with self._lock:
                self.would_limit[decision.lane] = self.would_limit.get(decision.lane, 0) + calls
                key = (decision.lane, decision.reason)
                moment = self._clock()
                say = key not in self._logged or moment - self._logged[key] >= self._log_every
                if say:
                    self._logged[key] = moment
            if say:
                log.warning("quota.lane_limited" if self.mode == "enforce" else "quota.lane_would_limit", lane=decision.lane,
                            job=job, reason=decision.reason, lane_spent=decision.lane_spent, ceiling=decision.ceiling,
                            refused_since_start=self.would_limit[decision.lane], mode=self.mode)
            if self.mode == "enforce":
                raise LaneLimitedError(
                    f"lane {decision.lane!r} reached its daily ceiling ({decision.lane_spent} of {decision.ceiling} today): "
                    f"{job} stops here; the other lanes go on. It starts again at 00:00 UTC (FBI_APIFOOTBALL_LANES).")
        with self._lock:
            self._spent[decision.lane] = self._spent.get(decision.lane, 0) + calls
        return decision
