"""Team and player statistics truth: parsing the provider, recomputing ours, judging who is wrong."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.truth.v2 import players as pl
from fbi.truth.v2 import team_history as th
from fbi.truth.v2 import team_stats as ts

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def team_body(played: tuple[int, int, int], wins: int, draws: int, loses: int, gf: int, ga: int) -> dict[str, Any]:
    def side(total: int) -> dict[str, int]:
        return {"home": 0, "away": 0, "total": total}

    return {"response": {
        "fixtures": {"played": {"home": played[0], "away": played[1], "total": played[2]}, "wins": side(wins),
                     "draws": side(draws), "loses": side(loses)},
        "goals": {"for": {"total": side(gf)}, "against": {"total": side(ga)}},
        "clean_sheet": side(0), "failed_to_score": side(0), "form": "W"}}


def game(at_home: bool, gh: int, ga: int, days: int = 3) -> dict[str, Any]:
    return {"at_home": at_home, "goals_home": gh, "goals_away": ga, "kickoff_at": NOW - timedelta(days=days)}


def test_team_figures_recompute_the_providers_way() -> None:
    ours = ts.recompute([game(True, 2, 0), game(False, 1, 1), game(False, 3, 1)])
    assert ours.get("played") == 3 and ours.get("played", "home") == 1
    assert (ours.get("wins"), ours.get("draws"), ours.get("loses")) == (1, 1, 1)
    assert (ours.get("goals_for"), ours.get("goals_against")) == (4, 4)
    assert ours.get("clean_sheet") == 1 and ours.get("failed_to_score") == 0
    assert ours.form == "WDL"


def test_fewer_games_than_the_provider_is_ours_missing() -> None:
    a = ts.audit_team(team_body((1, 1, 2), 2, 0, 0, 4, 0), [game(True, 2, 0)], league=39, season=2026, team=50,
                      name="X", at=NOW)
    assert a.verdict == "ours_missing"
    assert ts.evidence(a, None)[0].issue_type == "MISSING_BACKFILL"


def test_more_games_than_the_provider_is_its_lag_then_staleness() -> None:
    body = team_body((1, 0, 1), 1, 0, 0, 2, 0)
    recent = ts.audit_team(body, [game(True, 2, 0, 5), game(False, 0, 0, 0)], league=39, season=2026, team=50,
                           name="X", at=NOW)
    assert recent.verdict == "provider_lag_expected"
    old = ts.audit_team(body, [game(True, 2, 0, 5), game(False, 0, 0, 2)], league=39, season=2026, team=50,
                        name="X", at=NOW)
    assert old.verdict == "provider_behind"
    assert ts.evidence(old, None)[0].at_fault == "provider"


def test_the_team_page_record_mixing_competitions_is_a_product_scope_issue() -> None:
    a = ts.audit_team(None, [], league=39, season=2026, team=50, name="X", at=NOW,
                      product={"played": 338, "competitions": 6, "seasons": 9})
    ev = ts.scope_evidence([a])
    assert ev is not None and ev.issue_type == "PRODUCT_SCOPE" and ev.at_fault == "predigol"
    # the page since 4 Oct: one competition and season as the headline, the lifetime labelled apart
    fixed = ts.audit_team(None, [], league=39, season=2026, team=50, name="X", at=NOW,
                          product={"played": 5, "scope": "competition_season", "competitions": 1,
                                   "lifetime_played": 491, "lifetime_scope": "all"})
    assert ts.scope_evidence([fixed]) is None


def test_thin_histories_are_classified_against_tracked_seasons() -> None:
    team = {"provider_team_id": 7, "name": "Club U19", "fixtures": 3, "is_national": False, "country": "X"}
    leagues = {"response": [{"league": {"id": 39}, "seasons": [{"year": 2024}, {"year": 2025}]},
                            {"league": {"id": 999}, "seasons": [{"year": 2025}]}]}
    v = th.classify(team, leagues, tracked={39}, held={(39, 2025): 1}, ours_by_cs={(39, 2025): 3}, dups=[])
    assert v.kind == "youth"
    assert v.label == "SEASON_NOT_MIGRATED" and v.not_migrated == ["39/2024"]
    v2 = th.classify(team, leagues, tracked={39}, held={(39, 2024): 1, (39, 2025): 2}, ours_by_cs={(39, 2025): 3},
                     dups=[])
    assert v2.label == "MISSING_BACKFILL"
    v3 = th.classify(team, {"response": []}, tracked={39}, held={}, ours_by_cs={}, dups=[])
    assert v3.label == "PROVIDER_COVERAGE"
    v4 = th.classify(team, leagues, tracked={1}, held={}, ours_by_cs={}, dups=[])
    assert v4.label == "REAL_LOW_HISTORY"
    assert th.classify(team, leagues, tracked={39}, held={}, ours_by_cs={}, dups=[8]).label == "IDENTITY_MAPPING_ERROR"


def test_same_name_same_country_rows_are_duplicates() -> None:
    teams = [{"provider_team_id": 1, "name": "Atlético Nacional", "country": "Colombia"},
             {"provider_team_id": 2, "name": "Atletico Nacional", "country": "Colombia"},
             {"provider_team_id": 3, "name": "Atletico Nacional", "country": "Panama"}]
    assert th.duplicates(teams) == {1: [2], 2: [1]}
    assert th.kind_of("Chelsea W", False) == "women" and th.kind_of("Spain U21", True) == "youth"
    assert th.kind_of("Real Madrid II", False) == "reserve" and th.kind_of("Colombia", True) == "national"


def player_body(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"response": [{"player": {"id": 1100, "name": "E. Haaland"}, "statistics": list(blocks)}]}


def block(team: int, league: int, apps: int, lineups: int, minutes: int, goals: int, assists: int | None,
          rating: str = "7.4") -> dict[str, Any]:
    return {"team": {"id": team, "name": f"T{team}"}, "league": {"id": league, "name": f"L{league}", "season": 2026},
            "games": {"appearences": apps, "lineups": lineups, "minutes": minutes, "rating": rating},
            "goals": {"total": goals, "assists": assists}, "cards": {"yellow": 1, "yellowred": 0, "red": 0},
            "substitutes": {"bench": 2}}


def ours(team: int, league: int, apps: int, lineups: int, minutes: int, goals: int, assists: int) -> dict[str, Any]:
    return {"team": team, "team_name": f"T{team}", "league": league, "league_name": f"L{league}", "season": 2026,
            "appearances": apps, "lineups": lineups, "minutes": minutes, "goals": goals, "assists": assists,
            "yellow": 1, "red": 0, "bench": 2, "avg_match_rating": 7.1}


def test_provider_player_blocks_are_per_team_and_league() -> None:
    _, blocks = pl.api_blocks(player_body(block(50, 39, 6, 6, 540, 8, None), block(50, 2, 2, 2, 180, 3, 1)))
    assert [(b.team, b.league, b.goals, b.assists) for b in blocks] == [(50, 39, 8, None), (50, 2, 3, 1)]


def test_player_blocks_judged_with_minutes_slack_and_rating_never_compared() -> None:
    _, (b,) = pl.api_blocks(player_body(block(50, 39, 6, 6, 540, 8, 0, rating="9.1")))
    assert pl.judge_block(b, ours(50, 39, 6, 6, 535, 8, 0)).verdict == "ok"
    assert pl.judge_block(b, ours(50, 39, 5, 5, 450, 7, 0)).verdict == "ours_missing"
    assert pl.judge_block(b, ours(50, 39, 7, 7, 630, 9, 0)).verdict == "provider_behind"
    v = pl.judge_block(b, ours(50, 39, 6, 6, 540, 7, 0))
    assert v.verdict == "stats_mismatch" and v.differences == {"goals": (8, 7)}
    assert pl.judge_block(None, ours(50, 39, 1, 1, 90, 0, 0)).verdict == "not_at_provider"


def test_a_national_team_shown_as_the_players_team_is_flagged() -> None:
    ev = pl.player_evidence(386828, "Lamine Yamal", [], {"team": "Spain", "team_is_national": True},
                            {"id": 529, "name": "Barcelona"}, None)
    assert [e.issue_type for e in ev] == ["PRODUCT_SCOPE"]
    assert "Barcelona" in ev[0].claim


def test_apps_counting_unused_substitutes_is_flagged_once() -> None:
    rows = [{"player": 1, "name": "A", "product": {"apps": 30, "bench_rows": 4, "competitions": 3}},
            {"player": 2, "name": "B", "product": {"apps": 10, "bench_rows": 0, "competitions": 1}}]
    ev = {e.key: e for e in pl.product_evidence(rows)}
    assert set(ev) == {"player_stats:product:apps_counts_bench", "player_stats:product:window_scope"}


def test_a_shootout_counted_as_a_result_is_the_providers_rule_not_a_mismatch() -> None:
    drawn = {"at_home": True, "goals_home": 1, "goals_away": 1, "pen_home": 3, "pen_away": 4,
             "kickoff_at": NOW - timedelta(days=30)}
    one = {"home": 1, "away": 0, "total": 1}
    none = {"home": 0, "away": 0, "total": 0}
    body = {"response": {"fixtures": {"played": one, "wins": none, "draws": none, "loses": one},  # a loss, 1-2
                         "goals": {"for": {"total": one}, "against": {"total": {"home": 2, "away": 0, "total": 2}}},
                         "clean_sheet": none, "failed_to_score": none}}
    a = ts.audit_team(body, [drawn], league=547, season=2025, team=505, name="Inter", at=NOW)
    assert a.verdict == "shootout_rule"
    ev = ts.shootout_evidence([a])
    assert ev is not None and ev.issue_type == "PROVIDER_DEFINED_METRIC" and ev.status == "ACCEPTED"


def test_why_our_side_lacks_a_block_is_named() -> None:
    def v(verdict: str, league: int = 10, season: int = 2026, gaps: int = 0,
          diffs: dict[str, tuple[Any, Any]] | None = None, fetched: bool = False) -> pl.BlockVerdict:
        b = pl.BlockVerdict(1, "T", league, "L", season, verdict, None, None, differences=diffs or {})
        b.gaps = {"finished": 5, "without_player_rows": gaps, "never_fetched": 0 if fetched else gaps,
                  "empty_at_provider": gaps if fetched else 0}
        return b

    assert pl.refine(v("not_in_db", league=999), tracked={10}, migrated=set()).verdict == "untracked"
    assert pl.refine(v("not_in_db"), tracked={10}, migrated=set()).verdict == "season_not_migrated"
    assert pl.refine(v("ours_missing", gaps=4), tracked={10}, migrated={(10, 2026)}).verdict == "details_missing"
    # asked for, and the provider's players block came back empty: its coverage, not our backfill
    fetched = pl.refine(v("ours_missing", gaps=4, fetched=True), tracked={10}, migrated={(10, 2026)})
    assert fetched.verdict == "provider_no_match_rows"
    ev = pl.player_evidence(1, "P", [fetched], {}, None, None)
    assert [(e.issue_type, e.at_fault) for e in ev] == [("PROVIDER_COVERAGE", "provider")]
    assert pl.refine(v("ours_missing"), tracked={10}, migrated={(10, 2026)}).verdict == "player_rows_missing"
    assert pl.refine(v("stats_mismatch", diffs={"lineups": (7, 6)}), tracked={10},
                     migrated={(10, 2026)}).verdict == "starts_definition"
    assert pl.refine(v("stats_mismatch", diffs={"lineups": (7, 6), "goals": (2, 1)}), tracked={10},
                     migrated={(10, 2026)}).verdict == "stats_mismatch"


def test_identity_duplicates_report_every_group_not_the_examples() -> None:
    from fbi.truth.v2 import identity as idn

    examples = [{"full_name": f"p{i}", "birth_date": "2000-01-01", "ids": [i, i + 1000], "groups_total": 155,
                 "rows_total": 311} for i in range(50)]
    ev = {e.key: e for e in idn.evidence({"player_duplicates": examples}, {}, NOW)}
    assert "155 people" in ev["identity:player_duplicates"].claim and "311 rows" in ev["identity:player_duplicates"].claim


def test_re_reading_the_matches_says_who_differs() -> None:
    items = [{"fixture": {"id": 1}, "players": [{"team": {"id": 529}, "players": [
                 {"player": {"id": 1496}, "statistics": [{"games": {"minutes": 90, "substitute": False},
                                                          "goals": {"total": 2, "assists": 0},
                                                          "cards": {"yellow": 1, "red": 0}}]},
                 {"player": {"id": 7}, "statistics": [{"games": {"minutes": 90, "substitute": False}}]}]}]},
             {"fixture": {"id": 2}, "players": [{"team": {"id": 529}, "players": [
                 {"player": {"id": 1496}, "statistics": [{"games": {"minutes": None, "substitute": True},
                                                          "goals": {"total": None}, "cards": {}}]}]}]}]
    rows = pl.provider_match_rows(items, 1496)
    assert [r["fixture"] for r in rows] == [1, 2]
    fresh = pl.match_line(rows)
    assert fresh == {"appearances": 1, "lineups": 1, "minutes": 90, "goals": 2, "assists": 0, "yellow": 1, "red": 0}

    def block() -> pl.BlockVerdict:
        return pl.BlockVerdict(529, "Barcelona", 556, "Super Cup", 2025, "stats_mismatch",
                               {"goals": 1}, {"goals": 2}, differences={"goals": (1, 2)})

    same = pl.settle(block(), fresh, dict(fresh), 2)
    assert same.verdict == "provider_aggregate_differs" and same.recheck["fixtures"] == 2
    ev = pl.player_evidence(1496, "Raphinha", [same], {}, None, None)
    assert [(e.issue_type, e.at_fault) for e in ev] == [("PLAYER_STATS_MISMATCH", "provider")]
    older = pl.settle(block(), fresh, {**fresh, "goals": 1}, 2)
    assert older.verdict == "ours_stale"
    assert [(e.issue_type, e.at_fault) for e in pl.player_evidence(1496, "R", [older], {}, None, None)] == [
        ("STALE_ENTITY", "predigol")]
