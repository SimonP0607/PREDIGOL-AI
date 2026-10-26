"""The adaptive budget v3 (Plan Maestro IA, section 26). It replaces the day's arithmetic of ``fbi.ai.usage`` unless the owner
rolls it back (``FBI_AI_BUDGET_V3=0``: V2 is still there, untouched).

THREE ENVELOPES, never one number:

    production  Claude of the production workspace (``ai.usage_scoped`` scope 'production' and the analyst's ``analytics.ai_runs``)
                against ``FBI_AI_MONTHLY_BUDGET_USD`` (US$185; the Console's limit for the workspace is 190)
    lab         Claude of the LAB workspace against ``FBI_AI_LAB_MONTHLY_BUDGET_USD`` (15 / 55 / 15 by phase) - and never more
                than the joint ceiling (190) leaves after production's projection: the LAB yields FIRST, by whole days, and
                never by changing its model (an arm that changes judge is another experiment)
    exa         every search against ``FBI_AI_EXA_MONTHLY_BUDGET_USD`` (US$35): web search is Exa's money, not Claude's

PRODUCTION'S MONTH is projected, not only counted:

    projected = spent so far + what is left of today + the days after it
    a day's cost = its matches with a market x the unit cost (what a match with a market has cost over the last 7 days, or 14)
    its matches  = the calendar for the next 7 days (tracked fixtures scheduled x the share that ends up with a market);
                   beyond, the median of the same weekday over the last 4 weeks

THE DAY'S ALLOCATION is what is left, less the reserve (US$10 that only production may use, released in the last 5 days), shared in
proportion to each day's expected load: from 0.5 to ``FBI_AI_DAILY_MAX_FACTOR`` times the average, never above the soft target's
ceiling. Its hard cap is 1.5 times it, and never more than what is left.

STATES, by the projection against the envelope (a fixed percentage of the day no longer decides alone):

    NORMAL      the projection is up to 95 % of the envelope
    AJUSTE      95 - 100 %: duplicate work is dropped, what is stored is reused, the cache and Batch carry what can wait,
                redundant calls and secondary experiments stop, the LAB shrinks. The quality of the main path does not change
    REDUCED     over 100 %, or the day's allocation passed: no paid depth for matches without candidates, no final tier
    CHEAP_ONLY  the OLD route's last step (125 % of the day's allocation): the bulk tier only, no web search - until it is retired
    EXHAUSTED   the month spent, the day's hard cap, or the provider said a spend limit is spent: the rules reviewer decides

A spent limit (HTTP 400 workspace limit, 429 tier cap) is read from ``ai.limit_hits``: EXHAUSTED for a cooldown that doubles with
each hit of the last 12 hours (30 minutes up to 6 hours), then ONE call tries again - never a loop.

ALERTS warn and degrade nothing: the month crossing 50 / 70 / 85 / 95 / 100 % of each envelope, and production's PROJECTION
crossing 95 and 100 %. Production's month alert is written to ``ai.budget_alerts`` exactly as the earlier code wrote it (one table,
one key, shared by both generations of code, so a rollback never meets a schema it cannot use); the LAB's, Exa's and the
projection's go to ``ai.envelope_alerts`` (scope and kind). ``ai.budget_alerts_all`` reads both.

Everything here is a function of the ledger and of ``at``: no clock, no network, nothing written but the alerts."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai.calendar import (
    day_bounds,
    day_start,
    days_left_in_month,
    local_day,
    month_start,
    next_month,
)
from fbi.ai.config import AiSettings
from fbi.ai.usage import (
    ALERT_THRESHOLDS,
    CHEAP_AT,
    HARD_FACTOR,
    LOAD_MIN,
    MONTH_ALERT_SQL,
    REDUCED_AT,
    Budget,
    BudgetState,
    _money,
    reserved_by_day,
)

AJUSTE_AT = Decimal("0.95")
PROJECTION_REDUCED_AT = Decimal("1.00")
RESERVE_RELEASE_DAYS = 5
"""The reserve is kept for production's emergencies until this many days are left in the month, and then it is spent."""
UNIT_WINDOWS = (7, 14)
MIN_UNIT_DAYS = 3
CALENDAR_DAYS = 7
SHARE_DAYS = 14
WEEKDAY_WEEKS = 4
MIN_WEEKDAY_SAMPLES = 2
LIMIT_WINDOW = timedelta(hours=12)
LIMIT_COOLDOWN = timedelta(minutes=30)
LIMIT_COOLDOWN_MAX = timedelta(hours=6)
PROJECTION_ALERTS = (95, 100)
EXA_HARD_FACTOR = Decimal("2")
EXA_SEARCH_USD = Decimal("0.015")
MIN_LAB_DAY = Decimal("0.01")

COSTS_SQL = """
SELECT day, sum(cost) AS cost FROM (
    SELECT (at AT TIME ZONE 'America/Bogota')::date AS day, cost_usd AS cost
      FROM ai.usage_scoped WHERE scope = %(scope)s AND at >= %(since)s AND at < %(until)s
    UNION ALL
    SELECT (started_at AT TIME ZONE 'America/Bogota')::date, cost_usd
      FROM analytics.ai_runs WHERE %(scope)s::text = 'production' AND started_at >= %(since)s AND started_at < %(until)s
) x GROUP BY day
"""

PLANS_SQL = """
SELECT day, stage, fixtures_total, fixtures_with_market FROM ai.day_plans WHERE day >= %(since)s AND day <= %(until)s
"""

CALENDAR_SQL = """
SELECT (f.kickoff_at AT TIME ZONE 'America/Bogota')::date AS day, count(*) AS n
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
 GROUP BY 1
"""

LIMITS_SQL = """
SELECT at, kind FROM ai.limit_hits WHERE (workspace = %(workspace)s OR kind = 'tier_cap') AND at > %(since)s AND at <= %(until)s
 ORDER BY at
"""


# ── pure arithmetic ────────────────────────────────────────────────────────────────────────────────────────


def locked_reserve(*, remaining: Decimal, reserve: Decimal, days_left: int) -> Decimal:
    """What is kept back from the day's allocation: the reserve, until the last ``RESERVE_RELEASE_DAYS`` days of the month. When
    all that is left is the reserve itself, production may spend it - that is what it is for."""
    if days_left <= RESERVE_RELEASE_DAYS or remaining <= reserve:
        return Decimal(0)
    return reserve


def day_weight(*, load_today: float, loads_rest: float, days_left: int, factor: Decimal) -> float:
    """How a day's allocation compares with the average one: its load against the average load of the days left, between
    ``LOAD_MIN`` and ``FBI_AI_DAILY_MAX_FACTOR`` (a Saturday or a Champions night gets more, a quiet day less)."""
    total = load_today + loads_rest
    if total <= 0 or days_left <= 0:
        return 1.0
    return max(LOAD_MIN, min(float(factor), load_today * days_left / total))


def daily_allocation(*, available: Decimal, days_left: int, weight: float, ceiling: Decimal) -> Decimal:
    """The day's allocation: the average of what is available, times the day's weight, never above the soft target's ceiling
    nor above what is available."""
    if available <= 0 or days_left <= 0:
        return Decimal(0)
    average = available / days_left
    return _money(min(average * Decimal(str(round(weight, 4))), ceiling, available))


def project_month(*, spent_month: Decimal, spent_today: Decimal, unit_cost: Decimal | None, load_today: float,
                  loads_after: list[float], run_rate: Decimal) -> Decimal:
    """The month's spend by its last day: what is spent, what today still has to spend (its load x the unit cost, less what it
    spent), and the days after it. Without a unit cost (no days to measure it on) the days spend at ``run_rate``."""
    if unit_cost is None:
        rest_today = max(Decimal(0), run_rate - spent_today)
        return spent_month + rest_today + run_rate * len(loads_after)
    rest_today = max(Decimal(0), unit_cost * Decimal(str(load_today)) - spent_today)
    return spent_month + rest_today + unit_cost * Decimal(str(sum(loads_after)))


def state_of(*, monthly: Decimal, spent_month: Decimal, spent_today: Decimal, daily: Decimal, cap: Decimal,
             projected: Decimal, limit_active: bool) -> tuple[BudgetState, tuple[str, ...]]:
    """The state and why. The first that applies wins, from the worst down."""
    if monthly <= 0:
        return "EXHAUSTED", ("no_envelope",)
    if spent_month >= monthly:
        return "EXHAUSTED", ("month_spent",)
    if limit_active:
        return "EXHAUSTED", ("api_limit",)
    if daily <= 0 or spent_today >= cap:
        return "EXHAUSTED", ("day_cap",)
    reasons: list[str] = []
    ratio_day = spent_today / daily
    if ratio_day >= CHEAP_AT:
        return "CHEAP_ONLY", ("day_allocation_125",)
    share = projected / monthly
    if ratio_day >= REDUCED_AT:
        reasons.append("day_allocation")
    if share > PROJECTION_REDUCED_AT:
        reasons.append("projection_over_100")
    if reasons:
        return "REDUCED", tuple(reasons)
    if share > AJUSTE_AT:
        return "AJUSTE", ("projection_over_95",)
    return "NORMAL", ()


def lab_allocation(*, envelope: Decimal, joint_ceiling: Decimal, projected_production: Decimal) -> Decimal:
    """What the LAB may spend this month: its envelope, or what the joint ceiling leaves after production's projection -
    whichever is less. Production goes first."""
    return max(Decimal(0), min(envelope, joint_ceiling - projected_production))


def limit_cooldown(hits_in_window: int) -> timedelta:
    """How long a workspace that said its spend limit is spent is left alone: 30 minutes, doubling with each hit of the last 12
    hours, at most 6 hours. After it ONE call tries again; if it is refused it is another hit and a longer cooldown."""
    if hits_in_window <= 0:
        return timedelta(0)
    return min(LIMIT_COOLDOWN_MAX, LIMIT_COOLDOWN * (1 << (min(hits_in_window, 8) - 1)))


def crossed(spent: Decimal, envelope: Decimal, thresholds: tuple[int, ...] = ALERT_THRESHOLDS) -> list[int]:
    """The thresholds (percent of the envelope) a figure has reached."""
    if envelope <= 0:
        return []
    return [t for t in thresholds if spent * 100 >= envelope * t]


# ── the ledger ─────────────────────────────────────────────────────────────────────────────────────────────


def costs_by_day(conn: psycopg.Connection[Any], scope: str, since: datetime, until: datetime) -> dict[date, Decimal]:
    """What an envelope spent per Bogotá day in [since, until)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(COSTS_SQL, {"scope": scope, "since": since, "until": until})
        return {r[0]: Decimal(r[1] or 0) for r in cur.fetchall()}


@dataclass(frozen=True)
class Plans:
    opened: dict[date, int] = field(default_factory=dict)
    """Matches with a market, per day, as the opened plan (00:05) counted them."""
    opened_total: dict[date, int] = field(default_factory=dict)
    prepared: dict[date, int] = field(default_factory=dict)


def plans(conn: psycopg.Connection[Any], since: date, until: date) -> Plans:
    opened: dict[date, int] = {}
    total: dict[date, int] = {}
    prepared: dict[date, int] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PLANS_SQL, {"since": since, "until": until})
        for r in cur.fetchall():
            if r["stage"] == "opened":
                opened[r["day"]] = int(r["fixtures_with_market"])
                total[r["day"]] = int(r["fixtures_total"])
            elif r["stage"] == "prepared":
                prepared[r["day"]] = int(r["fixtures_with_market"])
    return Plans(opened, total, prepared)


def market_share(p: Plans, today: date) -> float:
    """Of the fixtures scheduled for a day, the share that ends up with a market (the last two weeks); 1 when unknown."""
    days = [d for d in p.opened if today - timedelta(days=SHARE_DAYS) <= d < today and p.opened_total.get(d, 0) > 0]
    total = sum(p.opened_total[d] for d in days)
    return 1.0 if total <= 0 else min(1.0, sum(p.opened[d] for d in days) / total)


def unit_cost(costs: Mapping[date, Decimal], p: Plans, today: date) -> tuple[Decimal | None, int]:
    """What a match with a market has cost production, all in: the days before today that had matches, over the last 7 days
    (or 14 when fewer than three of those had any). None when there is nothing to measure it on."""
    for window in UNIT_WINDOWS:
        days = [d for d in (today - timedelta(days=k) for k in range(1, window + 1)) if p.opened.get(d, 0) > 0]
        if len(days) >= MIN_UNIT_DAYS:
            matches = sum(p.opened[d] for d in days)
            return sum((costs.get(d, Decimal(0)) for d in days), Decimal(0)) / matches, len(days)
    return None, 0


def run_rate(costs: Mapping[date, Decimal], today: date) -> Decimal:
    """The average daily spend of the last seven days that spent anything (the fallback when no unit cost can be measured)."""
    days = [costs[d] for d in (today - timedelta(days=k) for k in range(1, 8)) if costs.get(d, 0) > 0]
    return sum(days, Decimal(0)) / len(days) if days else Decimal(0)


def scheduled_fixtures(conn: psycopg.Connection[Any], first: date, last: date) -> dict[date, int]:
    """Tracked fixtures still scheduled, per Bogotá day, from ``first`` to ``last`` inclusive."""
    start, _ = day_bounds(first)
    _, end = day_bounds(last)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CALENDAR_SQL, {"start": start, "end": end})
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def weekday_load(p: Plans, day: date, today: date) -> float:
    """The matches with a market a day is expected to have from its own weekday in the last four weeks (the median, with at least
    two of them to go on); otherwise the median of the last two weeks' days; 0 when the AI has not run long enough to say."""
    same = [p.opened[w] for w in (day - timedelta(days=7 * k) for k in range(1, WEEKDAY_WEEKS + 1)) if w in p.opened]
    if len(same) >= MIN_WEEKDAY_SAMPLES:
        return float(statistics.median(same))
    recent = [n for dd, n in p.opened.items() if today - timedelta(days=14) <= dd < today]
    return float(statistics.median(recent)) if recent else 0.0


def expected_loads(conn: psycopg.Connection[Any], today: date, p: Plans) -> dict[date, float]:
    """The matches with a market expected on each day from today to the month's last: today's from its opened plan, the next
    seven days' from the calendar (and the prepared plan, if bigger), and later ones from the same weekday of the last four
    weeks. A calendar with NOTHING scheduled in all seven days is a gap in the data, not a week without football: those days
    are filled from the weekday too."""
    last = next_month(today) - timedelta(days=1)
    near_last = min(last, today + timedelta(days=CALENDAR_DAYS))
    cal = scheduled_fixtures(conn, today, near_last)
    gap = sum(cal.values()) == 0
    share = market_share(p, today)
    out: dict[date, float] = {}
    d = today
    while d <= last:
        if d == today and d in p.opened:
            out[d] = float(p.opened[d])
        elif d <= near_last and not gap:
            out[d] = max(float(p.prepared.get(d, 0)), cal.get(d, 0) * share)
        elif d <= near_last:
            out[d] = max(float(p.prepared.get(d, 0)), weekday_load(p, d, today))
        else:
            out[d] = weekday_load(p, d, today)
        d += timedelta(days=1)
    return out


@dataclass(frozen=True)
class Limit:
    active: bool
    until: datetime | None = None
    hits: int = 0


def limit_state(conn: psycopg.Connection[Any], *, at: datetime, workspace: str) -> Limit:
    """Whether the provider said a spend limit is spent for this workspace (or for the whole account) and the cooldown has not
    passed. The cooldown starts at the newest hit."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LIMITS_SQL, {"workspace": workspace, "since": at - LIMIT_WINDOW, "until": at})
        hits = [r[0] for r in cur.fetchall()]
    if not hits:
        return Limit(False)
    until = max(hits) + limit_cooldown(len(hits))
    return Limit(at < until, until, len(hits))


# ── production ─────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Forecast:
    unit_cost: Decimal | None
    unit_days: int
    loads: dict[date, float]
    run_rate: Decimal
    spent_before: Decimal
    spent_today: Decimal
    projected: Decimal
    """The month's spend by its last day, with today's spend updated as it goes."""
    projected_at_dawn: Decimal
    """The same with today's expected cost instead of its live spend: it does not move during the day (the LAB's whole days)."""


def forecast(conn: psycopg.Connection[Any], *, at: datetime, scope: str = "production") -> Forecast:
    day = local_day(at)
    month_first = month_start(day)
    since = min(day_start(month_first), day_start(day - timedelta(days=max(UNIT_WINDOWS))))
    costs = costs_by_day(conn, scope, since, at + timedelta(seconds=1))
    held = reserved_by_day(conn, scope)  # the Message Batches still open count as spent: their result will replace the reservation
    before = sum((c for d, c in costs.items() if month_first <= d < day), Decimal(0)) + sum(
        (v for d, v in held.items() if month_first <= d < day), Decimal(0))
    today = costs.get(day, Decimal(0)) + held.get(day, Decimal(0))
    p = plans(conn, day - timedelta(days=7 * WEEKDAY_WEEKS), day + timedelta(days=CALENDAR_DAYS))
    loads = expected_loads(conn, day, p)
    unit, unit_days = unit_cost(costs, p, day)
    rate = run_rate(costs, day)
    load_today = loads.get(day, 0.0)
    after = [n for d, n in sorted(loads.items()) if d > day]
    projected = project_month(spent_month=before + today, spent_today=today, unit_cost=unit, load_today=load_today,
                              loads_after=after, run_rate=rate)
    dawn = project_month(spent_month=before, spent_today=Decimal(0), unit_cost=unit, load_today=load_today,
                         loads_after=after, run_rate=rate)
    return Forecast(unit, unit_days, loads, rate, before, today, projected, dawn)


def budget(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> Budget:
    """Today's budget of PRODUCTION under v3, with the interface of ``usage.Budget`` (``state``, ``allows``, ``pass_allows``,
    ``marginal_allowed``...). Its figures are Claude's of the production workspace: Exa's searches and the LAB's calls are not
    counted here."""
    day = local_day(at)
    days_left = days_left_in_month(day)
    fc = forecast(conn, at=at)
    monthly = settings.monthly_budget
    before, today = fc.spent_before, fc.spent_today
    remaining = max(Decimal(0), monthly - before)
    locked = locked_reserve(remaining=remaining, reserve=settings.reserve, days_left=days_left)
    available = max(Decimal(0), remaining - locked)
    load_today = fc.loads.get(day, 0.0)
    rest = sum(n for d, n in fc.loads.items() if d > day)
    weight = day_weight(load_today=load_today, loads_rest=rest, days_left=days_left, factor=settings.daily_max_factor)
    ceiling = settings.daily_budget * settings.daily_max_factor
    daily = daily_allocation(available=available, days_left=days_left, weight=weight, ceiling=ceiling)
    cap = _money(min(remaining, daily * HARD_FACTOR))
    limit = limit_state(conn, at=at, workspace=settings.workspace)
    state, reasons = state_of(monthly=monthly, spent_month=before + today, spent_today=today, daily=daily, cap=cap,
                              projected=fc.projected, limit_active=limit.active)
    pace = available / days_left
    return Budget(state, today, before + today, daily, monthly, cap, pace, weight, days_left, settings.daily_budget, day,
                  version="v3", projected=fc.projected, reserve_locked=locked,
                  limit_until=limit.until if limit.active else None, reasons=reasons)


# ── the LAB and Exa ────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LabDay:
    allowed: bool
    """Whether the LAB runs today at all - decided from what was known at the day's start, so it holds the whole day."""
    allocation: Decimal
    """What the LAB may spend this month: its envelope, or what the joint ceiling leaves after production's projection."""
    spent_month: Decimal
    remaining: Decimal
    """The month's allocation less what the LAB has spent: the hard stop inside the day."""
    typical_day: Decimal
    reason: str

    @property
    def can_spend(self) -> bool:
        return self.allowed and self.remaining > 0

    def as_json(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "allocation_usd": str(_money(self.allocation)),
                "spent_month_usd": str(_money(self.spent_month)), "remaining_usd": str(_money(self.remaining)),
                "typical_day_usd": str(_money(self.typical_day)), "reason": self.reason}


def lab_day(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> LabDay:
    """May the LAB spend today? Its allocation is the envelope or what is left under the joint ceiling after production's
    projection (production first). It runs a day only if what is left of the allocation before today covers a typical LAB day,
    so a day is run whole or not at all - the LAB yields by whole days and never by changing its model."""
    day = local_day(at)
    envelope = settings.lab_monthly_budget
    prod = forecast(conn, at=at)
    allocation = lab_allocation(envelope=envelope, joint_ceiling=settings.joint_ceiling,
                                projected_production=prod.projected_at_dawn)
    month_first = month_start(day)
    since = min(day_start(month_first), day_start(day - timedelta(days=14)))
    costs = costs_by_day(conn, "lab", since, at + timedelta(seconds=1))
    held = reserved_by_day(conn, "lab")
    before = sum((c for d, c in costs.items() if month_first <= d < day), Decimal(0)) + sum(
        (v for d, v in held.items() if month_first <= d < day), Decimal(0))
    spent = before + costs.get(day, Decimal(0)) + held.get(day, Decimal(0))
    active = [c for d, c in costs.items() if day - timedelta(days=7) <= d < day and c > 0]
    typical = Decimal(str(statistics.median(active))) if active else Decimal(0)
    remaining = max(Decimal(0), allocation - spent)
    limit = limit_state(conn, at=at, workspace=settings.workspace_lab)
    if envelope <= 0:
        return LabDay(False, allocation, spent, Decimal(0), typical, "no_envelope")
    if limit.active:
        return LabDay(False, allocation, spent, Decimal(0), typical, "api_limit")
    if allocation <= 0:
        return LabDay(False, allocation, spent, Decimal(0), typical, "yields_to_production")
    if allocation - before < max(typical, MIN_LAB_DAY):
        return LabDay(False, allocation, spent, remaining, typical, "allocation_spent")
    return LabDay(True, allocation, spent, remaining, typical, "ok")


@dataclass(frozen=True)
class ExaBudget:
    allowed: bool
    envelope: Decimal
    spent_month: Decimal
    spent_today: Decimal
    daily: Decimal
    cap: Decimal
    reason: str

    def as_json(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "envelope_usd": str(self.envelope), "spent_month_usd": str(_money(self.spent_month)),
                "spent_today_usd": str(_money(self.spent_today)), "daily_usd": str(_money(self.daily)),
                "daily_cap_usd": str(_money(self.cap)), "reason": self.reason}


def exa_budget(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> ExaBudget:
    """Exa's own envelope: searches stop when the month has spent it, or when today has spent twice its average share of what is
    left - Exa's money never moves Claude's budget and Claude's never moves Exa's."""
    day = local_day(at)
    month_first = month_start(day)
    costs = costs_by_day(conn, "exa", day_start(month_first), at + timedelta(seconds=1))
    before = sum((c for d, c in costs.items() if d < day), Decimal(0))
    today = costs.get(day, Decimal(0))
    envelope = settings.exa_monthly_budget
    remaining = max(Decimal(0), envelope - before)
    daily = remaining / days_left_in_month(day)
    cap = min(remaining, daily * EXA_HARD_FACTOR)
    if envelope <= 0:
        return ExaBudget(False, envelope, before + today, today, daily, cap, "no_envelope")
    if before + today + EXA_SEARCH_USD > envelope:
        return ExaBudget(False, envelope, before + today, today, daily, cap, "month_spent")
    if today + EXA_SEARCH_USD > cap:
        return ExaBudget(False, envelope, before + today, today, daily, cap, "day_cap")
    return ExaBudget(True, envelope, before + today, today, daily, cap, "ok")


# ── alerts ─────────────────────────────────────────────────────────────────────────────────────────────────

ENVELOPE_ALERT_SQL = ("INSERT INTO ai.envelope_alerts (month, scope, kind, threshold, created_at, spent_usd, budget_usd) "
                      "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (month, scope, kind, threshold) DO NOTHING "
                      "RETURNING threshold")


def check_alerts(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> list[int]:
    """Record, once a month each, the thresholds crossed: 50 / 70 / 85 / 95 / 100 % of the month's spend of production, of the LAB
    and of Exa against their own envelopes, and 95 / 100 % of production's PROJECTION. Returns the thresholds newly recorded.
    An alert warns; nothing is cut by it."""
    month = month_start(local_day(at))
    since, until = day_start(month), at + timedelta(seconds=1)
    new: list[int] = []
    with conn.cursor(row_factory=tuple_row) as cur:

        def record(scope: str, kind: str, thresholds: list[int], figure: Decimal, envelope: Decimal) -> None:
            for t in thresholds:
                if (scope, kind) == ("production", "month"):  # the one alert both generations of code share
                    cur.execute(MONTH_ALERT_SQL, (month, t, at, _money(figure), envelope))
                else:
                    cur.execute(ENVELOPE_ALERT_SQL, (month, scope, kind, t, at, _money(figure), envelope))
                if cur.fetchone() is not None:
                    new.append(t)

        prod = sum(costs_by_day(conn, "production", since, until).values(), Decimal(0))
        record("production", "month", crossed(prod, settings.monthly_budget), prod, settings.monthly_budget)
        if settings.monthly_budget > 0:
            projected = forecast(conn, at=at).projected
            record("production", "projection", crossed(projected, settings.monthly_budget, PROJECTION_ALERTS), projected,
                   settings.monthly_budget)
        for scope, envelope in (("lab", settings.lab_monthly_budget), ("exa", settings.exa_monthly_budget)):
            spent = sum(costs_by_day(conn, scope, since, until).values(), Decimal(0))
            record(scope, "month", crossed(spent, envelope), spent, envelope)
    return new
