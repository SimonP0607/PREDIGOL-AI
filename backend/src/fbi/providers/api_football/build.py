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
import structlog

from fbi.core.config import settings
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.circuit import AccountPause
from fbi.providers.lanes import LanePolicy
from fbi.providers.quota import (
    MINUTE_SHARE,
    EndpointUsageCounter,
    LaneGuard,
    PersistentDailyQuota,
    PersistentMinuteLimiter,
    PersistentReportedQuota,
    RunCappedQuota,
)
from fbi.storage.payload_store import PayloadStore

log = structlog.get_logger(__name__)


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
        # The lanes of the budget (plan PM, PM-04-01): None while FBI_APIFOOTBALL_LANES is off.
        lanes=build_lane_guard(),
        # The account's pause (plan PM, PM-04-02): one per process; None while FBI_APIFOOTBALL_ACCOUNT_GUARD is off.
        account_pause=build_account_pause(),
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


_lanes_lock = threading.Lock()
_lane_guard: LaneGuard | None = None


def build_lane_guard() -> LaneGuard | None:
    """The process's one lane guard (plan PM, PM-04-01), shared by every client of the process; None while
    ``FBI_APIFOOTBALL_LANES`` is off - the behaviour before the lanes, exactly. It reads today's counts from what the usage
    counter (PM-01-02) writes, so with ``FBI_PROVIDER_USAGE`` off there is nothing to read and it stays off (said once)."""
    global _lane_guard
    plan = settings.provider_plan
    if plan.lanes_mode == "off":
        return None
    with _lanes_lock:
        if _lane_guard is None:
            counter = build_usage_counter()
            if counter is None:
                log.warning("quota.lanes_off", reason="FBI_PROVIDER_USAGE is off: the lanes have no counts to read")
                return None
            policy, ignored = LanePolicy.from_settings(plan.lane_ceilings, budget=plan.effective_budget,
                                                       reserve=plan.emergency_reserve, dynamic=plan.dynamic_limits_on)
            if ignored:
                log.warning("quota.lane_ceilings_ignored", entries=ignored[:10])
            _lane_guard = LaneGuard(policy=policy, mode=plan.lanes_mode, connect=_connect, counter=counter)
            log.info("quota.lanes", mode=plan.lanes_mode, ceilings=policy.ceilings, dynamic=policy.dynamic,
                     reserve=policy.reserve if policy.dynamic else None)
        return _lane_guard


_account_pause: AccountPause | None = None


def build_account_pause() -> AccountPause | None:
    """The process's one account pause (plan PM, PM-04-02): every client of the process waits together while the provider refuses
    the account. None while ``FBI_APIFOOTBALL_ACCOUNT_GUARD`` is off (the behaviour before: such an answer is a plain error)."""
    global _account_pause
    cfg = settings.api_football
    if not cfg.account_guard_on:
        return None
    with _lanes_lock:
        if _account_pause is None:
            _account_pause = AccountPause(seconds=cfg.account_pause_seconds)
        return _account_pause
