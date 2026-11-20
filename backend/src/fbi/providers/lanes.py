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


DEFAULT_LANES: tuple[Lane, ...] = (
    Lane("directo", 1, 15_000, True, ("live_match_capture", "live_odds_capture"), "Directo"),
    Lane("cuotas", 2, 10_000, True, ("odds_capture", "odds_book_refresh", "final_prematch"), "Cuotas"),
    Lane("alineaciones", 3, 1_500, True, ("prematch_lineups", "lineup_watch"), "Alineaciones"),
    Lane("resultados", 4, 1_500, True, ("results_sync", "results_repair", "post_match_detail"), "Resultados"),
    Lane("calendario", 5, 1_500, False, ("fixtures_sync", "catalogue_refresh", "seasons_refresh", "teams_sync"),
         "Calendario y prioritarias"),
    Lane("estadisticas_contexto", 6, 3_000, False, ("context_refresh", "context_due", "context_refresh_manual"),
         "Estadísticas y contexto"),
    Lane("referencia", 7, 15_000, False, ("reference_refresh",), "Jugadores y referencia"),
    Lane("historicos", 8, 8_000, False, ("historical_backfill", "historical_odds_import", "raw_backfill_season_stats"),
         "Históricos"),
    Lane("ampliacion", 9, 5_000, False, ("league_probe", "league_expansion", "plan_probe", "window_probe", "capacity_probe",
                                         "odds_flag_probe", "half_probe"), "Ampliación"),
    Lane("reparacion", 10, 1_500, False, ("reprocess_fixture_venues",), "Reparación"),
    Lane(NO_LANE, 11, 2_000, False, (), "Sin carril"),
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
    """``ok`` or why not: ``lane_ceiling``."""
    lane_spent: int
    ceiling: int


@dataclass(frozen=True, slots=True)
class LanePolicy:
    """The table in force. ``decide`` is the rule for one request; it never waits and never reads anything."""

    lanes: tuple[Lane, ...] = DEFAULT_LANES

    def __post_init__(self) -> None:
        object.__setattr__(self, "lanes", _check(self.lanes))

    @classmethod
    def from_settings(cls, ceilings_text: str = "") -> tuple[LanePolicy, list[str]]:
        overrides, ignored = parse_ceilings(ceilings_text)
        lanes = tuple(replace(lane, ceiling=overrides.get(lane.name, lane.ceiling)) for lane in DEFAULT_LANES)
        return cls(lanes), ignored

    def lane(self, name: str) -> Lane:
        for lane in self.lanes:
            if lane.name == name:
                return lane
        return self.lane(NO_LANE)

    @property
    def ceilings(self) -> dict[str, int]:
        return {lane.name: lane.ceiling for lane in self.lanes}

    def decide(self, lane_name: str, *, lane_spent: Mapping[str, int], calls: int = 1) -> LaneDecision:
        """May ``calls`` more requests of ``lane_name`` go out, given what each lane has spent today?

        Only the lane's own count decides here: a lane is refused when it would pass its ceiling, never because another lane spent
        - so the matches in play are never held back by a sweep. A lane name the table does not know counts as ``sin_carril``."""
        lane = self.lane(lane_name)
        spent = int(lane_spent.get(lane.name, 0))
        if spent + calls > lane.ceiling:
            return LaneDecision(lane.name, False, "lane_ceiling", spent, lane.ceiling)
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


def replay(rows: Iterable[tuple[str, int, str, int]], policy: LanePolicy) -> list[LaneDay]:
    """Replay measured requests through the lanes: ``rows`` are (day, hour, job, requests), in any order; each (day, hour) is
    applied in time order, job by job, as if its requests went out one after another. Returns, per day, what each lane asked for
    and what the lanes would have refused."""
    by_slot: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for day, hour, job, requests in rows:
        if requests > 0:
            by_slot.setdefault((day, int(hour)), []).append((job, int(requests)))
    days: dict[str, LaneDay] = {}
    spent: dict[str, dict[str, int]] = {}
    for (day, _hour) in sorted(by_slot):
        result = days.setdefault(day, LaneDay(day, {}, {}))
        today = spent.setdefault(day, {})
        for job, requests in sorted(by_slot[(day, _hour)]):
            lane = policy.lane(LANE_OF_JOB.get(job, NO_LANE)).name
            result.spent[lane] = result.spent.get(lane, 0) + requests
            room = max(0, policy.lane(lane).ceiling - today.get(lane, 0))
            taken = min(room, requests)
            today[lane] = today.get(lane, 0) + taken
            result.refused[lane] = result.refused.get(lane, 0) + (requests - taken)
    return [days[d] for d in sorted(days)]
