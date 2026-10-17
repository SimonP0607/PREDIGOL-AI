"""Choosing competitions on evidence, and recording what was left out.

The rule: do not add leagues to make a number go up. So the tier of a competition
is a function of its coverage depth, and a competition that fails the bar is
recorded as excluded with the count that excluded it - not silently dropped.
"""

from __future__ import annotations

import pytest

from fbi.migration.selection import (
    MIN_FULL_DETAIL_SEASONS,
    REFERENCE_SET,
    Candidate,
    SelectionReport,
)


def candidate(**over: object) -> Candidate:
    base: dict[str, object] = {
        "provider_league_id": 9001, "name": "A League", "country": "Nowhere",
        "league_type": "League", "seasons_listed": 10, "full_detail_seasons": 10,
        "seasons_with_odds": 1, "seasons_with_standings": 10, "seasons_with_injuries": 5,
        "oldest_season": 2016, "newest_season": 2026, "has_current": True,
    }
    base.update(over)
    return Candidate(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("full_detail", "tier"),
    [(13, 2), (8, 2), (7, 3), (5, 3), (4, 4), (3, 4), (2, None), (1, None), (0, None)],
)
def test_the_tier_is_the_depth_of_full_detail_coverage(full_detail: int, tier: int | None) -> None:
    """Depth, not prestige. It is what decides how much a competition can contribute
    to a model, and it is the one axis the provider gives us honestly."""
    assert candidate(full_detail_seasons=full_detail).tier == tier


def test_the_reference_set_keeps_tier_one_whatever_the_bands_say() -> None:
    """The rest of the platform is calibrated against these six."""
    for league_id in REFERENCE_SET:
        assert candidate(provider_league_id=league_id, full_detail_seasons=3).tier == 1
        assert "reference set" in candidate(provider_league_id=league_id).reason


def test_an_excluded_competition_says_what_excluded_it() -> None:
    """A decision that can be re-read does not have to be re-argued."""
    thin = candidate(full_detail_seasons=1, seasons_listed=9)
    assert not thin.is_selected
    assert "only 1 season(s) with full detail" in thin.reason
    assert str(MIN_FULL_DETAIL_SEASONS) in thin.reason


def test_a_selected_competition_says_why_it_qualified() -> None:
    deep = candidate(full_detail_seasons=12, seasons_listed=17)
    assert "tier 2" in deep.reason and "12 of 17" in deep.reason


def test_a_cup_is_judged_on_the_same_evidence_as_a_league() -> None:
    """Cup fixtures are few, so the modelling value comes from the same statistics
    being present - there is no reason to apply a softer bar."""
    assert candidate(league_type="Cup", full_detail_seasons=12).tier == 2
    assert candidate(league_type="Cup", full_detail_seasons=2).tier is None


def test_only_full_detail_seasons_are_counted_as_work() -> None:
    """A season with fixtures and no statistics is a scoreline, not a dataset, and
    planning it as if it were would overstate what the migration buys."""
    report = SelectionReport(candidates=[
        candidate(provider_league_id=1, seasons_listed=17, full_detail_seasons=12),
        candidate(provider_league_id=2, seasons_listed=17, full_detail_seasons=4),
        candidate(provider_league_id=3, seasons_listed=17, full_detail_seasons=1),
    ])
    assert report.league_seasons_to_migrate == 16, "12 + 4; the third is excluded entirely"
    assert len(report.selected) == 2 and len(report.excluded) == 1


def test_the_bands_are_ordered_and_cover_every_selected_competition() -> None:
    report = SelectionReport(candidates=[candidate(provider_league_id=i, full_detail_seasons=d)
                                         for i, d in enumerate((12, 9, 6, 5, 4, 3, 2), start=9001)])
    by_tier = report.by_tier()
    assert list(by_tier) == sorted(by_tier), "tiers come out in order"
    assert sum(len(cs) for cs in by_tier.values()) == len(report.selected)
    assert by_tier[2] and by_tier[3] and by_tier[4]


def test_the_deepest_competition_comes_first_inside_a_tier() -> None:
    report = SelectionReport(candidates=[
        candidate(provider_league_id=9001, full_detail_seasons=8),
        candidate(provider_league_id=9002, full_detail_seasons=13),
    ])
    assert [c.provider_league_id for c in report.by_tier()[2]] == [9002, 9001]
