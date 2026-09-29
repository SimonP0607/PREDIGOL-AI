"""The migration and plan configuration, read from config/migration.yaml and
config/api_plans.yaml. Validated on load: a tier without competitions, a plan
without a quota or an endpoint without a classification is an error, not a
default."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_FILE = ROOT / "config" / "migration.yaml"
PLANS_FILE = ROOT / "config" / "api_plans.yaml"

CLASSIFICATIONS = ("MODEL_REQUIRED", "PRODUCT_REQUIRED", "OPTIONAL", "NOT_NEEDED", "NOT_AVAILABLE")
UNIT_KINDS = ("league_coverage", "fixtures_season", "fixture_details", "standings_season", "injuries_season",
              "teams_season", "players_season")
"""Kinds that become units in raw.backfill_tasks, in execution order."""


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    key: str
    path: str
    classification: str
    why: str
    batch: int | None = None
    per_fixture_without_batching: int | None = None
    requires_coverage: tuple[str, ...] = ()
    since_season: int | None = None
    since_season_is_partial: bool = False
    """The earliest season is a tail, not a whole year. /injuries measures this:
    season 2020 (2020/21) returned 3,100 absences against 13,774 for 2021, because
    the provider's April-2021 cut-off falls inside 2020/21. Coverage for that
    season must therefore never be reported as complete."""
    pages_estimate: int | None = None


@dataclass(frozen=True, slots=True)
class CompetitionSpec:
    tier: int
    league_id: int
    name: str
    fixtures: int


@dataclass(frozen=True, slots=True)
class LiveSpec:
    tiers: tuple[int, ...]
    season_days: int
    peak_share_of_week: float
    prematch_windows: int
    near_close: int
    lineup_polls: int
    post_match_details: int
    injuries_daily_per_league: int
    standing_syncs_daily: int
    standings_daily_per_league: int


@dataclass(frozen=True, slots=True)
class MigrationConfig:
    current_season: int
    target_depth: int
    include_current: bool
    live_reserve_fraction: float
    buffer_fraction: float
    max_backfill_days: float
    endpoints: dict[str, EndpointSpec]
    tiers: dict[int, str]
    competitions: tuple[CompetitionSpec, ...]
    live: LiveSpec
    storage_kb: dict[str, float]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def seasons(self) -> list[int]:
        """Completed seasons, newest first, then the current one if included."""
        past = [self.current_season - k for k in range(1, self.target_depth + 1)]
        return ([self.current_season] if self.include_current else []) + past

    def tier_competitions(self, tiers: set[int]) -> list[CompetitionSpec]:
        return [c for c in self.competitions if c.tier in tiers]


@dataclass(frozen=True, slots=True)
class ApiPlan:
    name: str
    requests_per_day: int
    requests_per_minute: int
    price_month: float
    history: str


@dataclass(frozen=True, slots=True)
class PlanCatalogue:
    checked_on: str
    currency: str
    plans: tuple[ApiPlan, ...]

    def get(self, name: str) -> ApiPlan:
        for p in self.plans:
            if p.name.lower() == name.lower():
                return p
        raise ConfigError(f"unknown plan {name!r}")


def _req(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ConfigError(f"{where}: '{key}' is required")
    return d[key]


def load_migration_config(path: Path = MIGRATION_FILE) -> MigrationConfig:
    raw = yaml.safe_load(path.read_text())
    seasons, budget = _req(raw, "seasons", "migration"), _req(raw, "budget", "migration")
    endpoints: dict[str, EndpointSpec] = {}
    for key, e in _req(raw, "endpoints", "migration").items():
        cls = _req(e, "classification", f"endpoint {key}")
        if cls not in CLASSIFICATIONS:
            raise ConfigError(f"endpoint {key}: classification {cls!r} is not one of {CLASSIFICATIONS}")
        endpoints[key] = EndpointSpec(key, str(_req(e, "path", key)), cls, str(e.get("why", "")), e.get("batch"),
                                      e.get("per_fixture_without_batching"),
                                      tuple(e.get("requires_coverage") or ()), e.get("since_season"),
                                      bool(e.get("since_season_is_partial", False)),
                                      e.get("pages_estimate"))
    for kind in UNIT_KINDS:
        if kind not in endpoints:
            raise ConfigError(f"endpoint {kind} is missing from the migration config")
    comps: list[CompetitionSpec] = []
    tiers: dict[int, str] = {}
    seen: set[int] = set()
    for tier, t in _req(raw, "tiers", "migration").items():
        tiers[int(tier)] = str(t.get("name", f"Tier {tier}"))
        items = t.get("competitions") or []
        if not items:
            raise ConfigError(f"tier {tier} has no competitions")
        for c in items:
            lid = int(_req(c, "league_id", f"tier {tier}"))
            if lid in seen:
                raise ConfigError(f"league {lid} appears in more than one tier")
            seen.add(lid)
            fixtures = int(_req(c, "fixtures", f"league {lid}"))
            if fixtures <= 0:
                raise ConfigError(f"league {lid}: fixtures estimate must be positive")
            comps.append(CompetitionSpec(int(tier), lid, str(c.get("name", lid)), fixtures))
    lv = _req(raw, "live", "migration")
    live = LiveSpec(tuple(int(x) for x in lv["tiers"]), int(lv["season_days"]), float(lv["peak_share_of_week"]),
                    int(lv["prematch_windows"]), int(lv["near_close"]), int(lv["lineup_polls"]),
                    int(lv["post_match_details"]), int(lv["injuries_daily_per_league"]),
                    int(lv["standing_syncs_daily"]), int(lv["standings_daily_per_league"]))
    reserve, buffer = float(budget["live_reserve_fraction"]), float(budget["buffer_fraction"])
    if not (0 <= reserve < 1 and 0 <= buffer <= 1):
        raise ConfigError("budget fractions must be in [0, 1)")
    return MigrationConfig(int(seasons["current"]), int(seasons["target_depth"]), bool(seasons["include_current"]),
                           reserve, buffer, float(budget.get("max_backfill_days", 14)), endpoints, tiers,
                           tuple(comps), live,
                           {k: float(v) for k, v in (raw.get("storage") or {}).items()}, raw)


def load_plans(path: Path = PLANS_FILE) -> PlanCatalogue:
    raw = yaml.safe_load(path.read_text())
    plans = []
    for p in _req(raw, "plans", "api_plans"):
        per_day = int(_req(p, "requests_per_day", "plan"))
        if per_day <= 0:
            raise ConfigError(f"plan {p.get('name')}: requests_per_day must be positive")
        plans.append(ApiPlan(str(p["name"]), per_day, int(p["requests_per_minute"]), float(p["price_month"]),
                             str(p.get("history", ""))))
    return PlanCatalogue(str(raw.get("checked_on", "")), str(raw.get("currency", "USD")), tuple(plans))
