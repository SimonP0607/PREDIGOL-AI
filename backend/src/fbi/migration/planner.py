"""Price a historical migration before spending a request.

For every (competition, season, unit kind) in the chosen tiers the planner
decides whether the unit is needed and what it costs:

* the provider's coverage flags (raw.league_coverage) decide what exists - a
  season without statistics coverage is not queried for statistics, and a
  season the provider does not list is not planned at all. Without flags
  (they come from one /leagues call, not made yet) the unit is planned and
  marked UNVERIFIED;
* our database decides what is already stored - a season whose fixtures are
  complete here costs no fixtures request;
* the fixture count comes from our database when it has the season, from the
  config estimate otherwise, and is replaced by the provider's own count when
  the fixtures unit runs.

``ids_batching`` is the one assumption that changes the order of magnitude:
/fixtures?ids= returns events, lineups, statistics and players for up to 20
fixtures in one request (documented), but one official post says "when
available for your plan". Without it the same detail costs four requests per
fixture. The plan is computed both ways until a real request settles it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Protocol

from fbi.migration.config import CompetitionSpec, MigrationConfig

COVERAGE_VERIFIED = "verified"
COVERAGE_UNVERIFIED = "unverified"
COVERAGE_ABSENT = "absent"


class Facts(Protocol):
    """What the planner reads about the present. A database implementation lives
    in fbi.migration.facts; tests use a dict."""

    def stored_fixtures(self, league_id: int, season: int) -> int:
        """Finished fixtures with a result stored for this competition-season."""

    def coverage(self, league_id: int, season: int) -> dict[str, bool | None] | None:
        """The provider's flags, or None when never observed."""

    def seasons_listed(self, league_id: int) -> set[int] | None:
        """Seasons the provider lists for the league, or None when never observed."""


@dataclass(frozen=True, slots=True)
class UnitCost:
    kind: str
    requests: int
    storage_kb: float
    why: str


@dataclass
class SeasonPlan:
    tier: int
    league_id: int
    name: str
    season: int
    fixtures: int
    fixtures_source: str
    coverage: str
    units: list[UnitCost] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def requests(self) -> int:
        return sum(u.requests for u in self.units)

    @property
    def storage_kb(self) -> float:
        return sum(u.storage_kb for u in self.units)


@dataclass
class Depth:
    name: str
    tier: int
    seasons: list[int] = field(default_factory=list)
    verified: int = 0
    unverified: int = 0


@dataclass
class MigrationPlan:
    tiers: tuple[int, ...]
    ids_batching: bool
    with_optional: bool
    seasons: list[SeasonPlan]
    global_units: list[UnitCost]
    notes: list[str] = field(default_factory=list)

    @property
    def requests(self) -> int:
        return sum(s.requests for s in self.seasons) + sum(u.requests for u in self.global_units)

    def requests_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for u in self.global_units:
            out[u.kind] += u.requests
        for s in self.seasons:
            for u in s.units:
                out[u.kind] += u.requests
        return dict(out)

    def requests_by_tier(self) -> dict[int, int]:
        out: dict[int, int] = defaultdict(int)
        for s in self.seasons:
            out[s.tier] += s.requests
        return dict(out)

    @property
    def fixtures(self) -> int:
        return sum(s.fixtures for s in self.seasons)

    @property
    def raw_storage_kb(self) -> float:
        return sum(s.storage_kb for s in self.seasons) + sum(u.storage_kb for u in self.global_units)

    def depth(self) -> dict[int, Depth]:
        """Per competition: seasons planned and how their coverage is known."""
        out: dict[int, Depth] = {}
        for s in self.seasons:
            d = out.setdefault(s.league_id, Depth(s.name, s.tier))
            d.seasons.append(s.season)
            if s.coverage == COVERAGE_VERIFIED:
                d.verified += 1
            else:
                d.unverified += 1
        return out

    def as_dict(self) -> dict[str, object]:
        return {
            "tiers": list(self.tiers), "ids_batching": self.ids_batching, "with_optional": self.with_optional,
            "requests": self.requests, "fixtures": self.fixtures, "raw_storage_kb": round(self.raw_storage_kb, 1),
            "requests_by_kind": self.requests_by_kind(), "requests_by_tier": self.requests_by_tier(),
            "league_seasons": len(self.seasons), "notes": self.notes,
            "seasons": [{**{k: v for k, v in asdict(s).items() if k != "units"}, "requests": s.requests,
                         "units": [asdict(u) for u in s.units]} for s in self.seasons],
            "global_units": [asdict(u) for u in self.global_units],
        }

    def plan_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True, default=str).encode()).hexdigest()


def _covered(flags: dict[str, bool | None] | None, keys: tuple[str, ...]) -> bool | None:
    """True/False from the provider's flags (any of ``keys``), None when unknown."""
    if flags is None or not keys:
        return None
    values = [flags.get(k) for k in keys]
    if any(v is True for v in values):
        return True
    if all(v is False for v in values):
        return False
    return None


def plan_migration(cfg: MigrationConfig, facts: Facts, *, tiers: set[int], ids_batching: bool = True,
                   with_optional: bool = False, seasons: list[int] | None = None) -> MigrationPlan:
    kb = cfg.storage_kb
    wanted = seasons if seasons is not None else cfg.seasons()
    plan = MigrationPlan(tuple(sorted(tiers)), ids_batching, with_optional, [], [])
    plan.global_units.append(UnitCost("league_coverage", 1, kb.get("coverage_kb", 0.0),
                                      "one /leagues call: every league, every season, its coverage flags"))
    for comp in cfg.tier_competitions(tiers):
        listed = facts.seasons_listed(comp.league_id)
        for season in wanted:
            sp = _season_plan(cfg, facts, comp, season, listed, ids_batching=ids_batching,
                              with_optional=with_optional)
            if sp is not None:
                plan.seasons.append(sp)
    if not ids_batching:
        plan.notes.append("detail priced at 4 requests per fixture: /fixtures?ids= batching assumed unavailable")
    unverified = sum(1 for s in plan.seasons if s.coverage != COVERAGE_VERIFIED)
    if unverified:
        plan.notes.append(f"{unverified} league-season(s) planned without provider coverage flags (UNVERIFIED): "
                          "the first unit of the migration (/leagues) replaces the assumption with the flags")
    return plan


def _season_plan(cfg: MigrationConfig, facts: Facts, comp: CompetitionSpec, season: int, listed: set[int] | None,
                 *, ids_batching: bool, with_optional: bool) -> SeasonPlan | None:
    if listed is not None and season not in listed:
        return None  # the provider does not have this season: nothing to plan, nothing to invent
    flags = facts.coverage(comp.league_id, season)
    coverage = COVERAGE_VERIFIED if flags is not None else COVERAGE_UNVERIFIED
    stored = facts.stored_fixtures(comp.league_id, season)
    complete_here = stored >= 0.9 * comp.fixtures and season != cfg.current_season
    n = stored if complete_here else comp.fixtures
    sp = SeasonPlan(comp.tier, comp.league_id, comp.name, season, n,
                    "database" if complete_here else "estimate", coverage)
    kb, ep = cfg.storage_kb, cfg.endpoints
    if complete_here:
        sp.skipped.append(f"fixtures_season: {stored} finished fixtures already stored")
    else:
        sp.units.append(UnitCost("fixtures_season", 1, kb.get("fixtures_season_kb", 0.0), ep["fixtures_season"].why))
    det = ep["fixture_details"]
    has_detail = _covered(flags, det.requires_coverage)
    if has_detail is False:
        sp.skipped.append("fixture_details: provider coverage has no events, lineups or statistics")
    else:
        batch = det.batch or 20
        requests = math.ceil(n / batch) if ids_batching else n * (det.per_fixture_without_batching or 4)
        sp.units.append(UnitCost("fixture_details", requests, n * kb.get("details_per_fixture_kb", 0.0), det.why))
    for kind, size_key in (("standings_season", "standings_kb"), ("injuries_season", "injuries_kb"),
                           ("teams_season", "teams_kb")):
        spec = ep[kind]
        if spec.since_season is not None and season < spec.since_season:
            sp.skipped.append(f"{kind}: the provider has no data before {spec.since_season}")
            continue
        if _covered(flags, spec.requires_coverage) is False:
            sp.skipped.append(f"{kind}: not in the provider's coverage for this season")
            continue
        sp.units.append(UnitCost(kind, 1, kb.get(size_key, 0.0), spec.why))
    pl = ep["players_season"]
    if with_optional and _covered(flags, pl.requires_coverage) is not False:
        pages = pl.pages_estimate or 36
        sp.units.append(UnitCost("players_season", pages, pages * kb.get("players_page_kb", 0.0), pl.why))
    return sp
