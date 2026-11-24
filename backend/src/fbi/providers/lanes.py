"""The lanes of the daily request budget (plan PM, PM-04-01; BE-060).

The internal budget (``FBI_APIFOOTBALL_DAILY_BUDGET``, 60,000 a day) used to be one pool with a few loose caps of its own (live odds
12,000, the book refreshes 8,000, the live follower stopping when fewer than 3,000 are left). Nothing stopped one sweep from taking
what the matches in play would need: on 20 Nov 2026 the reference feeds were 57.8 % of the measured month.

A lane is a group of jobs with a priority and a daily ceiling. Every job belongs to one lane (``LANE_OF_JOB``, by the ``job_type``
its ledger run records - the same one ``raw.provider_endpoint_usage`` keeps since PM-01-02); a job nobody listed falls in
``sin_carril``. Priority 1 is the most important. The vital lanes (directo, cuotas, alineaciones, resultados) are the ones the
emergency reserve and the dynamic limits of PM-04-02 keep alive to the end of the day; the others yield first, lowest priority
first.

This module is pure: the table, its parsing and the decision for one request. The guard that reads today's counts and applies the
decision in front of every request is ``fbi.providers.quota.LaneGuard``; the switch is ``FBI_APIFOOTBALL_LANES`` (``off`` by default:
exactly the behaviour before the lanes; ``measure`` decides and logs what it would have refused, refusing nothing; ``enforce``
refuses).

The ceilings are NOT the plan's target table: they are set to cover what was measured from 15 Oct to 19 Nov 2026 (36 days: the
largest day of each lane, with room), so that switching the lanes on changes nothing that works today. The plan's targets
(referencia 9,000, históricos 6,000, estadísticas 2,000) need PM-04-03 and PM-04-04 first, and are reached through
``FBI_APIFOOTBALL_LANE_CEILINGS`` once fourteen measured days say they fit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from types import MappingProxyType
from typing import Literal

LaneMode = Literal["off", "measure", "enforce"]
LANE_MODES: tuple[LaneMode, ...] = ("off", "measure", "enforce")
NO_LANE = "sin_carril"


@dataclass(frozen=True, slots=True)
class Lane:
    name: str
    priority: int
    """1 = the most important. A lower lane yields first (PM-04-02)."""
    ceiling: int
    """Requests this lane may spend in a UTC day."""
    vital: bool
    """Kept alive to the end of the day: may spend the emergency reserve (PM-04-02)."""
    jobs: tuple[str, ...]
    label: str
    pause_at: float | None = None
    """PM-04-02: the share of the day's budget at which the lane pauses until 00:00 UTC (None: never). The lower the lane, the
    sooner: históricos and ampliación at 60 %, referencia at 75 %, and at 88 % only the vital lanes are left."""
    quiet: bool = False
    """PM-04-02: a fill (historical, expansion) that does not run between 03:50 and 05:00 UTC, the window of the server's
    point-in-time copy and daily backup."""


PAUSE_FILLS = 0.60
PAUSE_REFERENCE = 0.75
PAUSE_ALL_BUT_VITAL = 0.88
QUIET_START = time(3, 50)
QUIET_END = time(5, 0)
DEFAULT_EMERGENCY_RESERVE = 7_000
"""The last 7,000 requests of the day's budget (section 6 of the plan): only the vital lanes may spend them."""


DEFAULT_LANES: tuple[Lane, ...] = (
    Lane("directo", 1, 15_000, True, ("live_match_capture", "live_odds_capture"), "Directo"),
    Lane("cuotas", 2, 10_000, True, ("odds_capture", "odds_book_refresh", "final_prematch"), "Cuotas"),
    Lane("alineaciones", 3, 1_500, True, ("prematch_lineups", "lineup_watch"), "Alineaciones"),
    Lane("resultados", 4, 1_500, True, ("results_sync", "results_repair", "post_match_detail"), "Resultados"),
    Lane("calendario", 5, 1_500, False, ("fixtures_sync", "catalogue_refresh", "seasons_refresh", "teams_sync"),
         "Calendario y prioritarias", PAUSE_ALL_BUT_VITAL),
    Lane("estadisticas_contexto", 6, 3_000, False, ("context_refresh", "context_due", "context_refresh_manual", "period_stats"),
         "Estadísticas y contexto", PAUSE_ALL_BUT_VITAL),
    Lane("referencia", 7, 15_000, False, ("reference_refresh",), "Jugadores y referencia", PAUSE_REFERENCE),
    Lane("historicos", 8, 8_000, False, ("historical_backfill", "historical_odds_import", "raw_backfill_season_stats", "period_backfill"),
         "Históricos", PAUSE_FILLS, quiet=True),
    Lane("ampliacion", 9, 5_000, False, ("league_probe", "league_expansion", "plan_probe", "window_probe", "capacity_probe",
                                         "odds_flag_probe", "half_probe"), "Ampliación", PAUSE_FILLS, quiet=True),
    Lane("reparacion", 10, 1_500, False, ("reprocess_fixture_venues",), "Reparación", PAUSE_FILLS),
    Lane(NO_LANE, 11, 2_000, False, (), "Sin carril", PAUSE_FILLS),
)
"""Measured 15 Oct - 19 Nov 2026 (``raw.ingestion_runs.api_calls`` by day and job), the largest day of each lane: directo 5,606 ·
cuotas 3,217 · alineaciones 788 · resultados 163 · calendario 718 · estadísticas 2,527 (29 Oct; otherwise at most 952) · referencia
14,343 (a Tuesday: the weekly people round; its structural top is 300 a run, 14,400 a day) · históricos 6,533 (a Monday: the
weekly /players sweep) · ampliación and reparación 0 · sin carril: the ad-hoc probes and ``/status``. Mean day 16,400 over 60,000.
Every ceiling is at least the measured top; no measured day would have been refused (``tests/unit/test_quota_lanes.py``)."""


def _check(lanes: Iterable[Lane]) -> tuple[Lane, ...]:
    table = tuple(sorted(lanes, key=lambda lane: lane.priority))
    names = [lane.name for lane in table]
    if len(set(names)) != len(names):
        raise ValueError("a lane is named twice")
    if len({lane.priority for lane in table}) != len(table):
        raise ValueError("two lanes share a priority")
    jobs = [job for lane in table for job in lane.jobs]
    if len(set(jobs)) != len(jobs):
        raise ValueError("a job is in two lanes")
    if NO_LANE not in names:
        raise ValueError(f"the table needs the {NO_LANE!r} lane for the jobs nobody listed")
    if any(lane.ceiling < 0 for lane in table):
        raise ValueError("a ceiling cannot be negative")
    if any(lane.vital and lane.pause_at is not None for lane in table):
        raise ValueError("a vital lane never pauses")
    if any(lane.pause_at is not None and not 0 < lane.pause_at <= 1 for lane in table):
        raise ValueError("a pause is a share of the budget, above 0 and at most 1")
    return table


LANE_OF_JOB: Mapping[str, str] = MappingProxyType({job: lane.name for lane in _check(DEFAULT_LANES) for job in lane.jobs})
"""The lane of each job, by the ``job_type`` the ledger records. ``fbi.providers.quota`` tags every request with it."""


def parse_ceilings(text: str) -> tuple[dict[str, int], list[str]]:
    """``"referencia=9000, historicos=6000"`` -> ({'referencia': 9000, 'historicos': 6000}, []); entries it cannot read are returned
    apart (they change nothing) so the caller can say so: a typo in ``app.env`` must never stop the worker."""
    known = {lane.name for lane in DEFAULT_LANES}
    ceilings: dict[str, int] = {}
    ignored: list[str] = []
    for raw in (text or "").split(","):
        entry = raw.strip()
        if not entry:
            continue
        name, _, value = entry.partition("=")
        name, value = name.strip().lower(), value.strip().replace("_", "").replace(".", "")
        if name in known and value.isdigit():
            ceilings[name] = int(value)
        else:
            ignored.append(entry)
    return ceilings, ignored


def lane_mode(value: str | None) -> LaneMode:
    """The switch, read leniently: anything that is not ``measure`` or ``enforce`` is ``off`` (the behaviour before the lanes)."""
    word = (value or "").strip().lower()
    if word in ("measure", "medir", "shadow"):
        return "measure"
    if word in ("enforce", "on", "aplicar"):
        return "enforce"
    return "off"


@dataclass(frozen=True, slots=True)
class LaneDecision:
    lane: str
    allowed: bool
    reason: str
    """``ok`` or why not: ``lane_ceiling``; with the dynamic limits (PM-04-02) also ``quiet_hours``, ``emergency_reserve`` and
    ``paused_60`` / ``paused_75`` / ``paused_88``."""
    lane_spent: int
    ceiling: int


@dataclass(frozen=True, slots=True)
class LanePolicy:
    """The table in force. ``decide`` is the rule for one request; it never waits and never reads anything.

    ``dynamic`` (PM-04-02, ``FBI_APIFOOTBALL_DYNAMIC_LIMITS``) adds, over the ceilings, the rules that keep the vital lanes alive
    to the end of a bad day: the pauses by share of ``budget`` (``Lane.pause_at``), the emergency ``reserve`` that only the vital
    lanes may spend, and the quiet window of the fills."""

    lanes: tuple[Lane, ...] = DEFAULT_LANES
    budget: int = 0
    reserve: int = 0
    dynamic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "lanes", _check(self.lanes))
        if self.dynamic and self.budget < 1:
            raise ValueError("the dynamic limits need the day's budget")
        if self.reserve < 0 or (self.budget and self.reserve >= self.budget):
            raise ValueError("the reserve is a part of the budget")

    @classmethod
    def from_settings(cls, ceilings_text: str = "", *, budget: int = 0, reserve: int = 0,
                      dynamic: bool = False) -> tuple[LanePolicy, list[str]]:
        overrides, ignored = parse_ceilings(ceilings_text)
        lanes = tuple(replace(lane, ceiling=overrides.get(lane.name, lane.ceiling)) for lane in DEFAULT_LANES)
        reserve = min(reserve, max(0, budget - 1)) if budget else 0
        return cls(lanes, budget=budget, reserve=reserve, dynamic=dynamic), ignored

    def lane(self, name: str) -> Lane:
        for lane in self.lanes:
            if lane.name == name:
                return lane
        return self.lane(NO_LANE)

    @property
    def ceilings(self) -> dict[str, int]:
        return {lane.name: lane.ceiling for lane in self.lanes}

    def decide(self, lane_name: str, *, lane_spent: Mapping[str, int], calls: int = 1, total_spent: int | None = None,
               at: datetime | None = None) -> LaneDecision:
        """May ``calls`` more requests of ``lane_name`` go out, given what each lane has spent today?

        The lane's own ceiling first: a lane is never refused because another lane spent - so the matches in play are never held
        back by a sweep. With the dynamic limits, a lane that is not vital then also yields, lowest priority first, as the day's
        ``total_spent`` grows (its ``pause_at``), and never spends the emergency reserve; a fill waits out the quiet window. A lane
        name the table does not know counts as ``sin_carril``."""
        lane = self.lane(lane_name)
        spent = int(lane_spent.get(lane.name, 0))
        if spent + calls > lane.ceiling:
            return LaneDecision(lane.name, False, "lane_ceiling", spent, lane.ceiling)
        if self.dynamic and not lane.vital:
            total = int(total_spent if total_spent is not None else sum(lane_spent.values()))
            moment = (at or datetime.now(UTC)).astimezone(UTC).time()
            if lane.quiet and QUIET_START <= moment < QUIET_END:
                return LaneDecision(lane.name, False, "quiet_hours", spent, lane.ceiling)
            if total + calls > self.budget - self.reserve:
                return LaneDecision(lane.name, False, "emergency_reserve", spent, lane.ceiling)
            if lane.pause_at is not None and total >= lane.pause_at * self.budget:
                return LaneDecision(lane.name, False, f"paused_{round(lane.pause_at * 100)}", spent, lane.ceiling)
        return LaneDecision(lane.name, True, "ok", spent, lane.ceiling)


# ── the replay of a measured day (the 30-day simulation of the card; ``scripts.quota_lanes simulate``) ─────────────────────────


@dataclass(frozen=True, slots=True)
class LaneDay:
    day: str
    spent: dict[str, int]
    """What each lane asked for that day."""
    refused: dict[str, int]
    """What the lanes would have refused (0 everywhere = nothing would have changed)."""

    @property
    def total(self) -> int:
        return sum(self.spent.values())

    @property
    def limited(self) -> list[str]:
        return [name for name, n in self.refused.items() if n > 0]


def replay(rows: Iterable[tuple[str, int, str, int]], policy: LanePolicy, *, daily_budget: int | None = None) -> list[LaneDay]:
    """Replay measured requests through the lanes: ``rows`` are (day, hour, job, requests), in any order; each (day, hour) is
    applied in time order, job by job, as if its requests went out one after another. Returns, per day, what each lane asked for
    and what was refused - by the lanes and, with ``daily_budget``, by the day's budget once it is spent (what happened to every
    job after 21:32 UTC on 29 Oct 2026)."""
    by_slot: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for day, hour, job, requests in rows:
        if requests > 0:
            by_slot.setdefault((day, int(hour)), []).append((job, int(requests)))
    days: dict[str, LaneDay] = {}
    spent: dict[str, dict[str, int]] = {}
    for (day, hour) in sorted(by_slot):
        result = days.setdefault(day, LaneDay(day, {}, {}))
        today = spent.setdefault(day, {})
        at = datetime.fromisoformat(day).replace(hour=hour, minute=30, tzinfo=UTC)
        for job, requests in sorted(by_slot[(day, hour)]):
            lane = policy.lane(LANE_OF_JOB.get(job, NO_LANE)).name
            result.spent[lane] = result.spent.get(lane, 0) + requests
            taken = _taken(policy, lane, requests, today, at)
            if daily_budget is not None:
                taken = min(taken, max(0, daily_budget - sum(today.values())))
            today[lane] = today.get(lane, 0) + taken
            result.refused[lane] = result.refused.get(lane, 0) + (requests - taken)
    return [days[d] for d in sorted(days)]


def _taken(policy: LanePolicy, lane: str, requests: int, today: Mapping[str, int], at: datetime) -> int:
    """How many of ``requests`` the lanes let through, one after another: the n-th passes when the rule allows one more after
    n - 1 (a bisection; the rule is monotonic in the count)."""
    total = sum(today.values())

    def fits(n: int) -> bool:
        if n == 0:
            return True
        before = {**today, lane: today.get(lane, 0) + n - 1}
        return policy.decide(lane, lane_spent=before, calls=1, total_spent=total + n - 1, at=at).allowed

    if fits(requests):
        return requests
    low, high = 0, requests
    while high - low > 1:
        mid = (low + high) // 2
        low, high = (mid, high) if fits(mid) else (low, mid)
    return low
