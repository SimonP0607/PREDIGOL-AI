"""RP-6.2: a trend becomes a citable fact only with its league reference and its sample, weighs by distance to that reference in standard
errors, and the fact for and against are chosen by code in a fixed order."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from fbi.stats import facts as f
from fbi.stats import reading as rd

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def trend(key: str, hits: int, n: int, league: Any, *, family: str = "goles", line: float | None = 2.5) -> dict[str, Any]:
    pct = round(100 * hits / n)
    return {"key": key, "family": family, "rule_key": "goals_ft@v1", "line": line, "hits": hits, "n": n, "pct": pct,
            "wilson_low": max(0, pct - 20), "wilson_high": min(100, pct + 20), "league_pct": league, "deviation_pts": 0, "fixture_ids": []}


def document(team: int, items: list[dict[str, Any]], *, computed_at: datetime = NOW) -> rd.Document:
    row = {"kind": "team", "entity_id": team, "competition_season_id": 7, "scope": "season", "context": "all", "calc_version": "stats-docs-v1",
           "sample": 20, "doc": {"figures": [], "trends": {"items": items}}, "computed_at": computed_at}
    return rd.document_of(row)


def test_the_audit_case_8_of_10_against_a_league_of_56_percent() -> None:
    """H20: after 8 of 10 over 2.5 the next one is over 58.8 % of the time, the league's 56.1 %: the streak is real but small beside its sample."""
    w = f.weight_of(8, 10, 56)
    assert w == pytest.approx((0.8 - 0.56) / math.sqrt(0.56 * 0.44 / 10))
    assert 1.5 < w < 1.6, "less than two standard errors from the league: a streak, not yet a fact that decides anything"
    assert f.weight_of(80, 100, 56) > 4 * f.weight_of(8, 10, 56) / 1.5, "the same rate on ten times the matches weighs far more"


def test_a_trend_without_the_league_reference_is_not_a_fact() -> None:
    doc = document(1, [trend("over_2_5", 8, 10, {"missing_reason": "sin_datos"}), trend("btts", 7, 10, 52)])
    facts, left = f.facts_of(doc)
    assert [x.key for x in facts] == ["btts"]
    assert left == [{"team_id": 1, "key": "over_2_5", "reason": f.NO_REFERENCE}]


def test_a_small_sample_is_left_out_with_its_reason() -> None:
    doc = document(1, [trend("over_2_5", 2, 2, 56)])
    facts, left = f.facts_of(doc)
    assert facts == [] and left[0]["reason"] == f.SMALL_SAMPLE and left[0]["n"] == 2
    assert f.MIN_SAMPLE >= 3, "the minimum is the one the statistics pages already use"


def test_a_fact_carries_the_five_things_and_its_source() -> None:
    facts, _ = f.facts_of(document(5, [trend("over_2_5", 8, 10, 56)]))
    j = facts[0].as_json()
    assert j["rate"] == 0.8 and j["n"] == 10 and j["hits"] == 8                       # rate and sample
    assert j["period"] == {"scope": "season", "context": "all"}                         # period
    assert j["league_pct"] == 56                                                         # reference
    assert j["wilson_pct"] == [60, 100]                                                  # interval
    assert j["source"]["document_id"] == "stat:team:5:7:season:all:stats-docs-v1" and j["source"]["computed_at"].startswith("2026-11-26")


def test_the_fact_for_and_against_are_chosen_by_code_and_the_order_is_fixed() -> None:
    home = document(1, [trend("over_2_5", 8, 10, 56), trend("btts", 3, 10, 52)])       # over: +1.53; btts: below the league
    away = document(2, [trend("over_2_5", 4, 10, 56), trend("btts", 6, 10, 52)])      # over: below; btts: slightly above
    out = f.for_match([home, away])
    over = out["chosen"]["over_2_5"]
    assert over[f.FOR]["team_id"] == 1 and over[f.AGAINST]["team_id"] == 2
    btts = out["chosen"]["btts"]
    assert btts[f.FOR]["team_id"] == 2 and btts[f.AGAINST]["team_id"] == 1
    assert f.for_match([away, home])["chosen"] == out["chosen"], "the order of the documents does not change the choice"


def test_a_tie_in_weight_goes_to_the_lower_team_id() -> None:
    a = document(9, [trend("over_2_5", 8, 10, 56)])
    b = document(3, [trend("over_2_5", 8, 10, 56)])
    assert f.for_match([a, b])["chosen"]["over_2_5"][f.FOR]["team_id"] == 3


def test_there_is_no_fact_against_when_nobody_is_below_the_league() -> None:
    both = f.for_match([document(1, [trend("over_2_5", 8, 10, 56)]), document(2, [trend("over_2_5", 7, 10, 56)])])
    assert both["chosen"]["over_2_5"][f.AGAINST] is None


def test_a_missing_or_future_document_is_not_read_and_says_so() -> None:
    late = rd.document_of({"kind": "team", "entity_id": 4, "competition_season_id": 7, "scope": "season", "context": "all",
                           "calc_version": "stats-docs-v1", "sample": 20, "doc": {"trends": {"items": [trend("over_2_5", 8, 10, 56)]}},
                           "computed_at": datetime(2026, 12, 1, tzinfo=UTC)}, as_of=NOW)
    out = f.for_match([late])
    assert out["facts"] == [] and out["left_out"] == [{"team_id": 4, "key": None, "reason": f.NO_DOCUMENT}]


def test_the_percentile_is_mid_rank_and_needs_enough_teams() -> None:
    peers = [40, 45, 50, 50, 55, 60, 65, 70, 75, 80]
    assert f.percentile_of(80, peers) == 95 and f.percentile_of(40, peers) == 5
    assert f.percentile_of(50, peers) == 30, "ties count half"
    assert f.percentile_of(50, peers[:5]) is None, "five teams are not a league"


def test_the_percentile_travels_with_the_fact_when_the_peers_are_given() -> None:
    peers = {"over_2_5": [40, 45, 50, 50, 55, 60, 65, 70, 75, 80]}
    facts, _ = f.facts_of(document(1, [trend("over_2_5", 8, 10, 56)]), peers=peers)
    assert facts[0].percentile == 95
    facts, _ = f.facts_of(document(1, [trend("over_2_5", 8, 10, 56)]))
    assert facts[0].percentile is None


def test_a_document_row_reads_its_trends_and_a_row_without_counts_is_skipped() -> None:
    doc = document(1, [trend("over_2_5", 8, 10, 56), {"key": "btts"}, {"key": "win", "hits": 3, "n": 0}])
    assert [t.key for t in doc.trends] == ["over_2_5"] and doc.trends[0].league_pct == 56
    assert rd.trends_of({"trends": {"items": [], "missing_reason": "sin_datos"}}) == ()
    assert rd.trends_of({}) == ()
