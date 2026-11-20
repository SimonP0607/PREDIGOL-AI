"""The owner's console of the provider's requests (plan PM, PM-04-05; BE-076): today, a window of days with annex F's figures, the
lanes against their ceilings, the endpoints, the competitions and the guards. Reads three tables the worker already writes
(``raw.provider_quota``, ``raw.provider_endpoint_usage``, ``raw.ingestion_payloads``) and the settings; asks the provider nothing.

Behind ``FBI_USAGE_CONSOLE`` (off: 404). The answer is kept 60 seconds.

Requests by competition are not counted anywhere: the counter of PM-01-02 keeps endpoint, lane and job, not the league. What the
console shows by competition is what is stored - the new answers that name a league - and says so; counting the requests would need
the league in the counter (a follow-up, not this piece).
"""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Final

from fbi.api.cache import shared
from fbi.api.contracts.provider_usage import (
    CompetitionUsage,
    EndpointUsage,
    LaneUsage,
    ProviderUsage,
    UsageDay,
    UsageGuards,
    UsageToday,
    UsageWindow,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.switches import usage_console_on
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.env import environment
from fbi.providers.lanes import LanePolicy

PROVIDER: Final = "api_football"
CACHE_SECONDS: Final = 60
DEFAULT_DAYS: Final = 30
MAX_DAYS: Final = 120
TOP_ENDPOINTS: Final = 40
TOP_COMPETITIONS: Final = 60

QUOTA_SQL: Final = """
SELECT quota_date, spent, budget, updated_at FROM raw.provider_quota
 WHERE provider = %(provider)s AND quota_date BETWEEN %(since)s AND %(until)s ORDER BY quota_date
"""
USAGE_SQL: Final = """
SELECT usage_date, endpoint, lane, sum(requests)::bigint AS requests, max(updated_at) AS updated_at
  FROM raw.provider_endpoint_usage
 WHERE provider = %(provider)s AND usage_date BETWEEN %(since)s AND %(until)s
 GROUP BY 1, 2, 3
"""
FIRST_COUNTED_SQL: Final = "SELECT min(usage_date) AS first FROM raw.provider_endpoint_usage WHERE provider = %(provider)s"
COMPETITIONS_SQL: Final = """
SELECT (p.params->>'league')::int AS league_id, count(*)::bigint AS responses
  FROM raw.ingestion_payloads p
 WHERE p.provider = %(provider)s AND p.fetched_at >= %(since)s AND p.fetched_at < %(until)s
   AND p.params->>'league' ~ '^[0-9]{1,9}$'
 GROUP BY 1 ORDER BY 2 DESC LIMIT %(limit)s
"""
NAMES_SQL: Final = "SELECT id, provider_league_id, name, country FROM core.competitions WHERE provider_league_id = ANY(%(ids)s)"


def _flag(name: str, *, default: bool) -> bool:
    raw = environment().get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "off", "false", "no"}


def _seconds(name: str, default: float) -> int:
    try:
        return int(float(environment().get(name) or default))
    except ValueError:
        return int(default)


def window_figures(days: list[UsageDay], since: date, until: date) -> UsageWindow:
    """Annex F's figures of a window: mean, median, the largest day and the largest NORMAL day (one under the budget)."""
    spent = [d.spent for d in days]
    normal = [d for d in days if not d.exhausted]
    top = max(days, key=lambda d: d.spent, default=None)
    top_normal = max(normal, key=lambda d: d.spent, default=None)
    return UsageWindow(
        since=since, until=until, days=len(days), mean=round(statistics.fmean(spent), 1) if spent else 0.0,
        median=float(statistics.median(spent)) if spent else 0.0, max=top.spent if top else 0, max_day=top.day if top else None,
        max_normal=top_normal.spent if top_normal else 0, max_normal_day=top_normal.day if top_normal else None,
        exhausted_days=sum(d.exhausted for d in days))


def projection(spent: int, at: datetime) -> tuple[float, int]:
    """Share of the UTC day gone and today's requests at today's pace (no projection in the first quarter hour: too noisy)."""
    start = datetime(at.year, at.month, at.day, tzinfo=UTC)
    elapsed = max(0.0, min(1.0, (at - start).total_seconds() / 86_400))
    return elapsed, (round(spent / elapsed) if elapsed >= 15 / 1440 else spent)


def build(conn: Conn, *, until: date | None = None, days: int = DEFAULT_DAYS, at: datetime | None = None) -> ProviderUsage:
    moment = at or now()
    today = moment.astimezone(UTC).date()
    last = min(until or today, today)
    span = max(1, min(days, MAX_DAYS))
    since = last - timedelta(days=span - 1)
    plan = settings.provider_plan
    budget = plan.effective_budget

    quota = fetch_all(conn, QUOTA_SQL, {"provider": PROVIDER, "since": since, "until": today})
    by_day = {r["quota_date"]: r for r in quota}
    window_days = [UsageDay(day=r["quota_date"], spent=int(r["spent"]), budget=int(r["budget"]),
                            exhausted=int(r["spent"]) >= int(r["budget"]))
                   for r in quota if since <= r["quota_date"] <= last]
    today_row = by_day.get(today)
    spent_today = int(today_row["spent"]) if today_row else 0

    usage = fetch_all(conn, USAGE_SQL, {"provider": PROVIDER, "since": since, "until": today})
    counted_today = sum(int(r["requests"]) for r in usage if r["usage_date"] == today)
    last_counted = max((r["updated_at"] for r in usage if r["usage_date"] == today), default=None)
    last_request = max(filter(None, [last_counted, today_row["updated_at"] if today_row else None]), default=None)

    elapsed, projected = projection(spent_today, moment)
    margin = budget - projected
    today_view = UsageToday(day=today, spent=spent_today, counted=counted_today, budget=budget, provider_limit=plan.per_day_limit,
                            elapsed=round(elapsed, 4), projected=projected, margin=margin,
                            margin_pct=round(100 * margin / budget, 1) if budget else 0.0, last_request_at=last_request)

    policy, _ = LanePolicy.from_settings(plan.lane_ceilings, budget=budget, reserve=plan.emergency_reserve,
                                         dynamic=plan.dynamic_limits_on)
    per_lane_day: dict[tuple[str, date], int] = {}
    per_endpoint: dict[tuple[str, str], list[int]] = {}
    for r in usage:
        if not since <= r["usage_date"] <= today:
            continue
        key = (r["lane"], r["usage_date"])
        per_lane_day[key] = per_lane_day.get(key, 0) + int(r["requests"])
        cell = per_endpoint.setdefault((r["endpoint"], r["lane"]), [0, 0])
        cell[1] += int(r["requests"])
        if r["usage_date"] == today:
            cell[0] += int(r["requests"])
    lanes = []
    for lane in policy.lanes:
        spent_lane = per_lane_day.get((lane.name, today), 0)
        best = max((v for (name, _d), v in per_lane_day.items() if name == lane.name), default=0)
        lanes.append(LaneUsage(lane=lane.name, label=lane.label, priority=lane.priority, ceiling=lane.ceiling, vital=lane.vital,
                               today=spent_lane, max_day=best,
                               share=round(100 * spent_lane / lane.ceiling, 1) if lane.ceiling else 0.0))
    endpoints = sorted((EndpointUsage(endpoint=e, lane=lane, today=v[0], window=v[1]) for (e, lane), v in per_endpoint.items()),
                       key=lambda x: (-x.today, -x.window, x.endpoint))[:TOP_ENDPOINTS]

    start = datetime(since.year, since.month, since.day, tzinfo=UTC)
    end = datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1)
    stored = fetch_all(conn, COMPETITIONS_SQL, {"provider": PROVIDER, "since": start, "until": end, "limit": TOP_COMPETITIONS})
    ids = [int(r["league_id"]) for r in stored]
    names = {int(r["provider_league_id"]): r for r in fetch_all(conn, NAMES_SQL, {"ids": ids})} if ids else {}
    competitions = [CompetitionUsage(league_id=int(r["league_id"]), competition_id=names[int(r["league_id"])]["id"]
                                     if int(r["league_id"]) in names else None,
                                     name=names.get(int(r["league_id"]), {}).get("name"),
                                     country=names.get(int(r["league_id"]), {}).get("country"), responses=int(r["responses"]))
                    for r in stored]

    first = fetch_one(conn, FIRST_COUNTED_SQL, {"provider": PROVIDER})
    quiet = round((moment - last_request).total_seconds() / 60, 1) if last_request else None
    guards = UsageGuards(lanes_mode=str(plan.lanes_mode), dynamic_limits=plan.dynamic_limits_on, emergency_reserve=plan.emergency_reserve,
                         account_guard=_flag("FBI_APIFOOTBALL_ACCOUNT_GUARD", default=True),
                         account_pause_seconds=_seconds("FBI_APIFOOTBALL_ACCOUNT_PAUSE_SECONDS", 900.0), quiet_minutes=quiet)
    return ProviderUsage(provider=PROVIDER, generated_at=moment, today=today_view,
                         window=window_figures(window_days, since, last), days=window_days, lanes=lanes, endpoints=endpoints,
                         competitions=competitions, counted_since=first["first"] if first else None, guards=guards)


@shared(CACHE_SECONDS)
def _cached(conn: Conn, until: date | None, days: int) -> Envelope[ProviderUsage]:
    return ok(build(conn, until=until, days=days))


def usage(conn: Conn, *, until: date | None = None, days: int = DEFAULT_DAYS) -> Envelope[ProviderUsage]:
    if not usage_console_on():
        raise ApiError(404, "not_found", "not found")
    return _cached(conn, until, days)

