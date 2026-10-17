"""The capacity report's arithmetic: percentiles, categories, the candidate score and the scenarios."""

from __future__ import annotations

from itertools import pairwise

from scripts.capacity_report import Candidate, category_of, percentiles, scenarios, score


def test_percentiles_on_a_short_history_say_how_short_it_is() -> None:
    p = percentiles([2716.0, 3769.0, 6133.0, 6134.0, 29418.0])
    assert p["n_days"] == 5 and p["median"] == 6133.0 and p["max"] == 29418.0 and p["min"] == 2716.0
    assert percentiles([])["median"] is None


def test_a_job_that_reads_several_endpoints_is_split_by_them() -> None:
    shares = {"reference_refresh": {"/players/profiles": 0.5, "/standings": 0.25, "/odds/mapping": 0.25}}
    assert category_of("reference_refresh", shares) == {"players": 0.5, "standings": 0.25, "odds_prematch": 0.25}
    assert category_of("truth_v2_golden", {}) == {"audits": 1.0}
    assert category_of("odds_capture", {}) == {"odds_prematch": 1.0}


def candidate(name: str, country: str, mapped: int, **flags: bool) -> Candidate:
    base = dict.fromkeys(("events", "lineups", "statistics_fixtures", "statistics_players", "standings"), True)
    return Candidate(1, 2026, name, country, "League", mapped, {**base, **flags}, 6, 6)


def test_a_deep_senior_league_in_a_betting_market_outscores_a_youth_one() -> None:
    senior, youth = candidate("Segunda Division", "Spain", 40), candidate("Primavera 1", "Italy", 40)
    for c in (senior, youth):
        score(c, 40)
    assert senior.score > youth.score and youth.components["interest"] < 0.5


def test_more_leagues_cost_more_on_every_day_type() -> None:
    model = {"fixed_per_day": 2000, "per_league_per_day": 30.0, "per_fixture": 15.0}
    measured = {"fixtures_per_day": {"a": 40, "b": 60, "c": 200}, "tracked_competitions": 124}
    cands = [candidate(f"L{i}", "Spain", 14) for i in range(80)]
    rows = scenarios(model, measured, cands)
    assert [r["added_leagues"] for r in rows] == [0, 25, 50, 75]
    for a, b in pairwise(rows):
        for day in ("normal", "busy", "p95", "worst"):
            assert b[day]["requests"] > a[day]["requests"]
    assert rows[0]["worst"]["requests"] > rows[0]["normal"]["requests"]
