"""How many requests live operation needs per day, and what each plan leaves for history.

The live model counts what the worker would actually call for the live tiers,
on an average day and on the busiest day of a week:

* odds: one /odds request per fixture per pre-match window, plus one
  near-close /odds/live request;
* lineups: /fixtures?ids= polls before kick-off, one per kick-off slot (up to 20
  fixtures each);
* post-match detail: one /fixtures?ids= per kick-off slot once finished;
* injuries and standings: one request per league per day;
* the standing syncs (fixtures and results by date - one date call covers every
  league).

A plan fits when the busiest live day, plus the buffer, stays inside the part
of the quota not reserved, and the backfill finishes within the days allowed.
The recommendation is the cheapest plan that fits - not the largest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fbi.migration.config import ApiPlan, MigrationConfig, PlanCatalogue
from fbi.migration.planner import MigrationPlan


@dataclass(frozen=True, slots=True)
class LiveBudget:
    tiers: tuple[int, ...]
    leagues: int
    fixtures_per_season: int
    avg_fixtures_per_day: float
    peak_fixtures_per_day: float
    avg: dict[str, float]
    peak: dict[str, float]

    @property
    def avg_total(self) -> float:
        return sum(self.avg.values())

    @property
    def peak_total(self) -> float:
        return sum(self.peak.values())


def _day(cfg: MigrationConfig, n: float, leagues: int) -> dict[str, float]:
    lv = cfg.live
    slots = math.ceil(n / 5) if n > 0 else 0
    return {
        "odds_prematch": n * lv.prematch_windows,
        "odds_near_close": n * lv.near_close,
        "lineups": float(max(math.ceil(n / 20), slots) * lv.lineup_polls) if n > 0 else 0.0,
        "post_match_details": float(max(math.ceil(n / 20), slots) * lv.post_match_details) if n > 0 else 0.0,
        "injuries": float(leagues * lv.injuries_daily_per_league),
        "standings": float(leagues * lv.standings_daily_per_league),
        "fixture_and_result_syncs": float(lv.standing_syncs_daily),
    }


def live_budget(cfg: MigrationConfig, tiers: set[int] | None = None) -> LiveBudget:
    chosen = set(tiers if tiers is not None else cfg.live.tiers)
    comps = cfg.tier_competitions(chosen)
    per_season = sum(c.fixtures for c in comps)
    avg = per_season / cfg.live.season_days
    peak = avg * 7 * cfg.live.peak_share_of_week
    return LiveBudget(tuple(sorted(chosen)), len(comps), per_season, avg, peak,
                      _day(cfg, avg, len(comps)), _day(cfg, peak, len(comps)))


@dataclass(frozen=True, slots=True)
class Scenario:
    plan: ApiPlan
    backfill_requests: int
    """With the buffer applied."""
    live_avg: float
    live_peak: float
    available_per_day: float
    backfill_days: float | None
    live_headroom_pct: float
    live_fits: bool
    backfill_fits: bool
    minutes_per_backfill_day: float

    @property
    def fits(self) -> bool:
        return self.live_fits and self.backfill_fits


def scenarios(plan: MigrationPlan, cfg: MigrationConfig, catalogue: PlanCatalogue, live: LiveBudget, *,
              max_backfill_days: float) -> list[Scenario]:
    out: list[Scenario] = []
    buffer = cfg.buffer_fraction
    need = math.ceil(plan.requests * (1 + buffer))
    for p in catalogue.plans:
        q = float(p.requests_per_day)
        usable = q * (1 - cfg.live_reserve_fraction)
        live_peak = live.peak_total * (1 + buffer)
        available = usable - live.avg_total * (1 + buffer)
        days = need / available if available > 0 else None
        headroom = (q - live_peak) / q * 100.0
        out.append(Scenario(
            plan=p, backfill_requests=need, live_avg=live.avg_total, live_peak=live.peak_total,
            available_per_day=max(available, 0.0), backfill_days=days, live_headroom_pct=headroom,
            live_fits=live_peak <= usable, backfill_fits=days is not None and days <= max_backfill_days,
            minutes_per_backfill_day=(min(available, need) / p.requests_per_minute) if available > 0 else 0.0,
        ))
    return out


def recommend(options: list[Scenario]) -> Scenario | None:
    """The cheapest plan that fits live operation and the backfill window."""
    fitting = [s for s in options if s.fits]
    return min(fitting, key=lambda s: (s.plan.price_month, s.plan.requests_per_day)) if fitting else None
