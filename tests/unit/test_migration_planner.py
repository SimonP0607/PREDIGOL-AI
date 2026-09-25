"""The migration is priced before a request is spent - and the price follows the facts.

Coverage the provider denies is not requested; seasons it does not list are not
planned; seasons already stored cost no fixtures request; and the one assumption
that changes the order of magnitude (/fixtures?ids= batching) is explicit.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from fbi.migration.capacity import live_budget, recommend, scenarios
from fbi.migration.config import ConfigError, load_migration_config, load_plans
from fbi.migration.planner import COVERAGE_UNVERIFIED, COVERAGE_VERIFIED, plan_migration


class DictFacts:
    def __init__(self, stored=None, coverage=None, listed=None) -> None:
        self.stored = stored or {}
        self.cov = coverage or {}
        self.listed = listed or {}

    def stored_fixtures(self, league_id: int, season: int) -> int:
        return self.stored.get((league_id, season), 0)

    def coverage(self, league_id: int, season: int):
        return self.cov.get((league_id, season))

    def seasons_listed(self, league_id: int):
        return self.listed.get(league_id)


FULL = {"events": True, "lineups": True, "statistics_fixtures": True, "statistics_players": True,
        "standings": True, "players": True, "top_scorers": True, "top_assists": True, "top_cards": True,
        "injuries": True, "predictions": True, "odds": False}


@pytest.fixture(scope="module")
def cfg():
    return load_migration_config()


def season(plan, league, s):
    return next(x for x in plan.seasons if x.league_id == league and x.season == s)


def test_the_config_is_complete_and_seasons_run_newest_first(cfg) -> None:
    assert cfg.seasons()[0] == cfg.current_season and len(cfg.seasons()) == cfg.target_depth + 1
    assert {c.tier for c in cfg.competitions} == {1, 2, 3}
    assert cfg.endpoints["odds_history"].classification == "NOT_AVAILABLE"
    assert cfg.endpoints["predictions"].classification == "NOT_NEEDED"
    assert [p.name for p in load_plans().plans] == ["Free", "Pro", "Ultra", "Mega"]


def test_a_season_already_stored_costs_no_fixtures_request_but_still_needs_details(cfg) -> None:
    facts = DictFacts(stored={(39, 2024): 380})
    plan = plan_migration(cfg, facts, tiers={1}, seasons=[2024])
    pl = season(plan, 39, 2024)
    kinds = {u.kind: u.requests for u in pl.units}
    assert "fixtures_season" not in kinds and pl.fixtures_source == "database"
    assert kinds["fixture_details"] == 19, "380 fixtures in batches of 20"


def test_coverage_decides_what_is_requested(cfg) -> None:
    no_stats = {**FULL, "events": False, "lineups": False, "statistics_fixtures": False,
                "statistics_players": False, "injuries": False}
    facts = DictFacts(coverage={(39, 2019): no_stats, (39, 2023): FULL})
    plan = plan_migration(cfg, facts, tiers={1}, seasons=[2023, 2019])
    old, new = season(plan, 39, 2019), season(plan, 39, 2023)
    assert {u.kind for u in old.units} == {"fixtures_season", "standings_season", "teams_season"}
    assert any("coverage" in s for s in old.skipped)
    assert old.coverage == COVERAGE_VERIFIED
    assert {"fixture_details", "injuries_season"} <= {u.kind for u in new.units}


def test_a_season_the_provider_does_not_list_is_not_planned(cfg) -> None:
    facts = DictFacts(listed={39: {2024, 2023}})
    plan = plan_migration(cfg, facts, tiers={1}, seasons=[2024, 2023, 2018])
    assert sorted(s.season for s in plan.seasons if s.league_id == 39) == [2023, 2024]
    others = [s for s in plan.seasons if s.league_id != 39]
    assert others and all(s.coverage == COVERAGE_UNVERIFIED for s in others)


def test_injuries_are_not_requested_before_the_provider_has_them(cfg) -> None:
    plan = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2019])
    s = season(plan, 39, 2019)
    assert "injuries_season" not in {u.kind for u in s.units}


def test_without_ids_batching_detail_costs_four_requests_per_fixture(cfg) -> None:
    with_ids = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2023])
    without = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2023], ids_batching=False)
    a = with_ids.requests_by_kind()["fixture_details"]
    b = without.requests_by_kind()["fixture_details"]
    assert b == 4 * with_ids.fixtures and a == sum(-(-s.fixtures // 20) for s in with_ids.seasons)
    assert any("ids" in n for n in without.notes)


def test_optional_endpoints_are_only_priced_when_asked(cfg) -> None:
    base = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2023])
    opt = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2023], with_optional=True)
    assert "players_season" not in base.requests_by_kind()
    assert opt.requests_by_kind()["players_season"] == 6 * 36


def test_the_plan_hash_changes_with_the_plan(cfg) -> None:
    a = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2023])
    b = plan_migration(cfg, DictFacts(), tiers={1}, seasons=[2023])
    c = plan_migration(cfg, DictFacts(), tiers={1, 2}, seasons=[2023])
    assert a.plan_hash() == b.plan_hash() != c.plan_hash()


def test_the_recommendation_is_the_cheapest_plan_that_fits(cfg) -> None:
    cat = load_plans()
    live = live_budget(cfg)
    small = plan_migration(cfg, DictFacts(), tiers={1, 2, 3})
    rec = recommend(scenarios(small, cfg, cat, live, max_backfill_days=cfg.max_backfill_days))
    assert rec is not None and rec.plan.name == "Pro"
    big = plan_migration(cfg, DictFacts(), tiers={1, 2, 3}, ids_batching=False)
    month = scenarios(big, cfg, cat, live, max_backfill_days=30)
    by = {s.plan.name: s for s in month}
    assert not by["Free"].fits and not by["Pro"].fits and by["Ultra"].fits
    assert recommend(month).plan.name == "Ultra", "a month allowed: the cheaper plan that fits"  # type: ignore[union-attr]
    fortnight = scenarios(big, cfg, cat, live, max_backfill_days=10)
    assert recommend(fortnight).plan.name == "Mega", "ten days allowed: only the bigger quota fits"  # type: ignore[union-attr]


def test_live_needs_grow_with_the_tiers_captured(cfg) -> None:
    one = live_budget(cfg, {1})
    two = live_budget(cfg, {1, 2})
    tiers_1_2 = len(cfg.tier_competitions({1, 2}))
    assert two.peak_total > one.peak_total > 0 and two.leagues == tiers_1_2 and one.leagues == 6
    assert one.peak["odds_prematch"] == pytest.approx(one.peak_fixtures_per_day * cfg.live.prematch_windows)


def test_free_never_fits_a_paid_migration(cfg) -> None:
    plan = plan_migration(cfg, DictFacts(), tiers={1})
    free = next(s for s in scenarios(plan, cfg, load_plans(), live_budget(cfg), max_backfill_days=14)
                if s.plan.name == "Free")
    assert not free.fits


def test_a_tier_without_competitions_is_a_config_error(cfg, tmp_path) -> None:
    import yaml

    raw = dict(cfg.raw)
    raw["tiers"] = {1: {"name": "empty", "competitions": []}}
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError):
        load_migration_config(path)


def test_budget_fractions_are_validated(cfg, tmp_path) -> None:
    import yaml

    raw = dict(cfg.raw)
    raw["budget"] = {**raw["budget"], "live_reserve_fraction": 1.5}
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError):
        load_migration_config(path)
    assert replace(cfg, buffer_fraction=0.25).buffer_fraction == 0.25
