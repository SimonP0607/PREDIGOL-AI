"""The one place a provider client is constructed for real work.

Before this existed, three scripts each built their own ``ApiFootballClient``
and two of them let it fall back to the in-memory ``DailyQuota``. So
``manage_competitions probe`` and ``sync_fixtures`` spent requests against a
budget that reset the moment the process started, while only
``capture_odds`` counted at all - and even that count died with the shell.

Everything that talks to the provider goes through here, so the budget is
enforced in one place and cannot be forgotten by the next script.
"""

from __future__ import annotations

import atexit
import os
import threading

import psycopg

from fbi.core.config import settings
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.quota import (
    MINUTE_SHARE,
    EndpointUsageCounter,
    PersistentDailyQuota,
    PersistentMinuteLimiter,
    PersistentReportedQuota,
    RunCappedQuota,
)
from fbi.storage.payload_store import PayloadStore


def _connect() -> psycopg.Connection:
    """A fresh autocommit connection for the quota counter alone.

    Autocommit because a reservation must not be rolled back with the caller's
    work: the request was really issued, so the budget really was spent.
    """
    return psycopg.connect(settings.database.psycopg_url, autocommit=True)


def build_quota() -> PersistentDailyQuota:
    """Our daily budget, never above what the plan allows."""
    cfg = settings.api_football
    return PersistentDailyQuota(
        budget=min(cfg.daily_budget, cfg.per_day_limit), connect=_connect
    )


def build_client(max_requests: int | None = None) -> ApiFootballClient:
    """A client whose daily budget survives this process.

    ``max_requests`` adds a ceiling for this run only - what
    ``capture_odds run --max-requests 5`` means. It never widens the daily
    budget and never replaces it; both have to allow a request.
    """
    quota: PersistentDailyQuota | RunCappedQuota = build_quota()
    if max_requests is not None:
        quota = RunCappedQuota(build_quota(), max_requests=max_requests)
    return ApiFootballClient(
        settings.api_football,
        PayloadStore(settings.runtime.raw_store_dir),
        quota=quota,
        rate_limiter=build_minute_limiter(),
        # What the provider says of our quota (its headers), kept in raw.provider_reported_quota (plan Cuotas, BE-011).
        quota_reporter=PersistentReportedQuota(connect=_connect),
        # Requests by endpoint, lane and job, in memory and added once a minute (plan PM, PM-01-02).
        usage=build_usage_counter(),
    )


def build_minute_limiter() -> PersistentMinuteLimiter:
    """The plan's per-minute limit, shared by every process (MINUTE_SHARE of it). While the usage switch is on, its hourly prune
    also keeps the day's peaks in raw.provider_minute_daily (PM-01-02)."""
    cfg = settings.api_football
    return PersistentMinuteLimiter(limit=max(1, int(cfg.per_minute_limit * MINUTE_SHARE)), connect=_connect,
                                   summarize=usage_enabled())


USAGE_SWITCH = "FBI_PROVIDER_USAGE"
"""Counting the requests by endpoint and lane (plan PM, PM-01-02). ON unless it says 0/off/false/no: it measures and changes no
request, no answer and nothing a reader sees; off, the client counts nothing and the limiter keeps no daily summary. The worker
reads it when it starts."""
_OFF_WORDS = frozenset({"0", "off", "false", "no"})
_usage_lock = threading.Lock()
_usage_counter: EndpointUsageCounter | None = None


def usage_enabled() -> bool:
    return os.environ.get(USAGE_SWITCH, "on").strip().lower() not in _OFF_WORDS


def build_usage_counter() -> EndpointUsageCounter | None:
    """The process's one usage counter (every client of the process shares it), flushed once more when the process exits; None
    while the switch is off."""
    global _usage_counter
    if not usage_enabled():
        return None
    with _usage_lock:
        if _usage_counter is None:
            _usage_counter = EndpointUsageCounter(connect=_connect)
            atexit.register(_flush_at_exit, _usage_counter)
        return _usage_counter


def _flush_at_exit(counter: EndpointUsageCounter) -> None:
    # The interpreter is leaving: flush() never raises (a write that fails is logged), so this is all it can cost.
    counter.flush()
