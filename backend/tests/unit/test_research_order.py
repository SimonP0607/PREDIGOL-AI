"""RP-5.4: the research goes by the importance of the match (levels A to D), the pick candidate only breaks ties, level A is researched 48 and 24
hours before and every level A match is chosen before any level B one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.ai import research_order as ro
from fbi.ai.day import DayFixture

NOW = datetime(2026, 11, 28, 12, tzinfo=UTC)


def fx(fid: int, *, league: int | None, tier: int | None = 3, market: bool = True, hours: float = 30, ctype: str = "domestic_league") -> DayFixture:
    return DayFixture(fid, NOW + timedelta(hours=hours), 1, "C", None, tier, "H", "A", market, NOW if market else None, 12 if market else None,
                      0.0, False, league)


def test_the_owners_priority_competitions_are_level_a_with_or_without_a_market() -> None:
    assert ro.level_of(fx(1, league=2)) == "A"                      # Champions League, group 1
    assert ro.level_of(fx(2, league=13, market=False)) == "A"       # Libertadores, group 2, no price yet
    assert ro.level_of(fx(3, league=1)) == "A"                      # World Cup, group 3 (national teams)


def test_the_primera_a_of_colombia_is_level_a_by_decision_d2() -> None:
    assert ro.level_of(fx(4, league=239, tier=2)) == "A"
    assert ro.level_of(fx(5, league=240, tier=2)) == "B", "the second division of Colombia is not on the list"


def test_the_rest_of_tier_1_and_2_and_the_followed_matches_are_level_b() -> None:
    assert ro.level_of(fx(6, league=99, tier=1)) == "B"
    assert ro.level_of(fx(7, league=99, tier=2)) == "B"
    assert ro.level_of(fx(8, league=99, tier=4), followers=3) == "B"


def test_the_other_matches_with_a_market_are_c_and_those_without_market_or_followers_are_d() -> None:
    assert ro.level_of(fx(9, league=99, tier=4)) == "C"
    assert ro.level_of(fx(10, league=99, tier=4, market=False)) == "D"
    assert ro.level_of(fx(11, league=99, tier=4, market=False), followers=1) == "B"


def test_the_candidate_no_longer_orders_the_search_it_only_breaks_ties_inside_a_level() -> None:
    a_without = ro.Ranked(fx(1, league=239), "A")
    b_with_candidate = ro.Ranked(fx(2, league=99, tier=1), "B")
    keys = sorted([(ro.order_key(b_with_candidate, candidate=9.0), 2), (ro.order_key(a_without), 1)])
    assert [k[1] for k in keys] == [1, 2], "a level A match without a pick candidate comes before a level B match with one"
    x, y = ro.Ranked(fx(3, league=99, tier=1), "B"), ro.Ranked(fx(4, league=99, tier=1), "B")
    assert ro.order_key(y, candidate=2.0) < ro.order_key(x, candidate=1.0), "inside a level the candidate does break the tie"
    assert ro.order_key(x, novelty=1) < ro.order_key(y, candidate=9.0), "novelty goes before the candidate"
    assert ro.order_key(x, followers=5) < ro.order_key(y, followers=4)


def test_choose_takes_every_level_a_before_level_b_and_never_level_d() -> None:
    fixtures = ro.ranked([fx(1, league=99, tier=1), fx(2, league=239), fx(3, league=2), fx(4, league=99, tier=4, market=False),
                          fx(5, league=99, tier=4)])
    got = ro.choose(fixtures, 3, candidates={1: 5.0})
    assert {r.fixture.fixture_id for r in got[:2]} == {2, 3}
    assert got[2].fixture.fixture_id == 1 and all(r.level != "D" for r in ro.choose(fixtures, 10))
    assert ro.level_a_unsearched(fixtures, {r.fixture.fixture_id for r in got}) == []
    assert ro.level_a_unsearched(fixtures, {3}) == [2]


def test_level_a_is_researched_at_48_and_24_hours_and_never_twice() -> None:
    k = NOW + timedelta(hours=47)
    assert ro.due_anticipation("A", k, at=NOW, done=set()) == "t48"
    assert ro.due_anticipation("A", k, at=NOW, done={"t48"}) is None
    assert ro.due_anticipation("A", NOW + timedelta(hours=20), at=NOW, done={"t48"}) == "t24"
    assert ro.due_anticipation("A", NOW + timedelta(hours=20), at=NOW, done={"t48", "t24"}) is None
    assert ro.due_anticipation("A", NOW + timedelta(hours=60), at=NOW, done=set()) is None, "not yet 48 hours from the match"
    assert ro.due_anticipation("B", NOW + timedelta(hours=20), at=NOW, done=set()) is None
    assert ro.due_anticipation("A", NOW - timedelta(hours=1), at=NOW, done=set()) is None


def test_the_coverage_counts_by_level_what_was_searched_and_what_the_new_order_would_search() -> None:
    fixtures = ro.ranked([fx(1, league=2), fx(2, league=239), fx(3, league=99, tier=1), fx(4, league=99, tier=4, market=False)])
    cov = ro.coverage(fixtures, searched={3}, chosen={1, 2})
    assert cov["A"] == {"matches": 2, "searched": 0, "would_search": 2}
    assert cov["B"] == {"matches": 1, "searched": 1, "would_search": 0}
    assert cov["D"] == {"matches": 1, "searched": 0, "would_search": 0}
    assert "would_search" not in ro.coverage(fixtures, searched=set())["A"]
