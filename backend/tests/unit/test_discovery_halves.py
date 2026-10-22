"""Plan F0, defect 11: a bet on ONE HALF of a statistic is not settle-able with the statistic's match total.

The market discovery engine read "Corners Over Under - First Half" as corners and judged it settle-able with the coverage of
the corners of the whole match (96 %), when nothing we store gives corners by half. discovery-v2 asks for the statistic BY
HALF; the platform keeps corners, shots, saves, fouls and offsides only as totals of the match, so those bets are not
modelable; cards by half could come from the events but that coverage is not measured, so they stay candidates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.intel import discovery

AT = datetime(2032, 9, 20, tzinfo=UTC)
# What a good week of data looks like: every statistic of the MATCH is covered, the half-time score too.
COVERAGE = {"goals": 1.0, "corners": 0.97, "cards": 0.95, "shots": 0.93, "saves": 0.9, "fouls": 0.92, "offsides": 0.9,
            "halftime": 0.979, "players": 0.6}

CORNERS_BY_HALF = [
    "Total Corners (1st Half)",
    "Corners Over Under - First Half",
    "Corners 1x2 (First Half)",
    "Home Corners Over/Under (2nd Half)",
    "Corners Asian Handicap 1H",
]


def _stats(name: str) -> discovery.BetStats:
    """A bet that is offered everywhere, by five bookmakers, for 150 matches: price, coverage and volume all pass."""
    return discovery.BetStats(name=name, fixtures=set(range(150)), books_per_fixture=[5] * 150, lines={"Over 4.5"},
                              competitions={1})


def _judge(name: str, bid: int = 900) -> tuple[str, dict[str, dict[str, object]], dict[str, object], str]:
    return discovery.criteria_for(bid, _stats(name), catalogue={"first_seen_at": AT - timedelta(days=40)}, active={},
                                  n_fixtures=200, coverage=COVERAGE, at=AT, fixtures_by_competition={1: 160})


@pytest.mark.parametrize("name", CORNERS_BY_HALF)
def test_corners_of_one_half_need_corners_by_half_and_cannot_be_modelled(name: str) -> None:
    assert discovery.classify(name) == ("corners_by_half", "not_modelable")


def test_the_match_total_is_still_the_match_total() -> None:
    assert discovery.classify("Corners Over Under") == ("corners", "new_model")
    assert discovery.classify("Home Corners Over/Under") == ("corners", "new_model")
    assert discovery.classify("Cards Over/Under") == ("cards", "new_model")
    assert discovery.classify("Total Shots") == ("shots", "new_model")


@pytest.mark.parametrize("name", CORNERS_BY_HALF)
def test_a_first_half_corners_bet_is_not_settleable_however_well_the_match_total_is_covered(name: str) -> None:
    status, criteria, metrics, proposal = _judge(name)
    assert criteria["settle_data"]["ok"] is False, "the 97 % of the match total does not settle a half"
    assert criteria["settle_data"]["value"] == {"data": "corners_by_half", "coverage": None}
    assert status == "NOT_MODELABLE" and "por mitad" in proposal and "no se puede liquidar" in proposal
    assert metrics["data"] == "corners_by_half"


def test_the_full_match_corners_market_is_unchanged() -> None:
    status, criteria, _, proposal = _judge("Corners Over Under")
    assert criteria["settle_data"]["ok"] is True and status == "RESEARCH" and "corners" in proposal


@pytest.mark.parametrize("name", ["Total Shots 1H", "Shots on Target 2nd Half", "Fouls Over Under 1st half",
                                  "Offsides (First Half)", "Goalkeeper Saves (1st Half)"])
def test_no_statistic_that_is_stored_as_a_match_total_is_settled_by_half(name: str) -> None:
    data, how = discovery.classify(name)
    assert data is not None and data.endswith("_by_half") and how == "not_modelable"
    status, criteria, _, _ = _judge(name)
    assert status == "NOT_MODELABLE" and criteria["settle_data"]["ok"] is False


@pytest.mark.parametrize("name", ["Yellow Over/Under (1st Half)", "Yellow Over/Under (2nd Half)",
                                  "Home Team Total Cards (2H)"])
def test_cards_by_half_wait_for_their_own_coverage(name: str) -> None:
    """Cards of a half could be counted from the events, but nothing here measures that: a candidate, never research."""
    assert discovery.classify(name) == ("cards_by_half", "new_model")
    status, criteria, _, proposal = _judge(name)
    assert status == "CANDIDATE" and criteria["settle_data"]["ok"] is False and "settle_data" in proposal


def test_yellow_cards_are_cards_not_goals_by_half() -> None:
    """'Yellow Over/Under (1st Half)' has no 'card' in its name: it used to fall through to the half-time GOALS rule and was
    judged by the coverage of the half-time score (97.9 %). 'Yellow Over/Under' fell through every rule."""
    assert discovery.classify("Yellow Over/Under (1st Half)")[0] != "halftime"
    assert discovery.classify("Yellow Over/Under") == ("cards", "new_model")
    assert discovery.classify("Yellow Double Chance") == ("cards", "new_model")


@pytest.mark.parametrize("name", ["Goals Over/Under First Half", "Both Teams Score - First Half",
                                  "Asian Handicap First Half", "Double Chance - First Half", "Odd/Even - Second Half",
                                  "HT/FT Double", "Highest Scoring Half"])
def test_goals_by_half_do_settle_with_the_half_time_score(name: str) -> None:
    assert discovery.classify(name) == ("halftime", "new_model")
    status, criteria, _, _ = _judge(name)
    assert criteria["settle_data"]["ok"] is True and status == "RESEARCH"


def test_coverage_of_the_match_total_never_stands_in_for_the_half() -> None:
    """Even a perfect corners coverage leaves a first-half corners bet unsettle-able: the key 'corners_by_half' is not
    measured anywhere."""
    perfect = {**COVERAGE, "corners": 1.0}
    assert "corners_by_half" not in perfect
    _, criteria, _, _ = discovery.criteria_for(
        901, _stats("Total Corners (1st Half)"), catalogue={"first_seen_at": AT - timedelta(days=40)}, active={},
        n_fixtures=200, coverage=perfect, at=AT, fixtures_by_competition={1: 160})
    assert criteria["settle_data"]["ok"] is False


def test_the_version_names_the_fix() -> None:
    assert discovery.VERSION == "discovery-v2"
