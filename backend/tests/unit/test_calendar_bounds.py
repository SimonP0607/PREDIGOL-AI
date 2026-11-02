"""Plan F0, defect 10: rest and congestion read from an incomplete calendar are bounds, and only claims that survive an
incomplete calendar are made.

The matches the platform knows are those of the competitions it follows. A team that also played a cup or a continental
tie it does not follow has a real rest shorter than the recorded one and more matches than the recorded count."""

from __future__ import annotations

import itertools

from fbi.ai import context as ctx


def test_short_rest_survives_an_incomplete_calendar() -> None:
    assert ctx.rest_flags_recorded(2.5, 6.0) == ["home_short_rest"]
    assert ctx.rest_flags_recorded(7.0, 2.0) == ["away_short_rest"]
    assert ctx.rest_flags_recorded(2.0, 2.5) == ["home_short_rest", "away_short_rest"]
    assert ctx.rest_flags_recorded(None, 2.0) == ["away_short_rest"]


def test_a_gap_between_the_two_sides_is_not_claimed() -> None:
    """3.5 against 7.0 looks like a three-day disadvantage, but the 7.0 may be 3.0 once the cup is counted."""
    assert ctx.rest_flags(3.5, 7.0) == ["home_rest_disadvantage"], "the complete-calendar reading, unchanged"
    assert ctx.rest_flags_recorded(3.5, 7.0) == []
    assert ctx.rest_flags_recorded(2.5, 6.0) == ["home_short_rest"], "only the short rest of the side that is short"


def test_the_boundary_and_the_unknowns() -> None:
    assert ctx.rest_flags_recorded(3.0, 3.0) == [] and ctx.rest_flags_recorded(2.99, 9.0) == ["home_short_rest"]
    assert ctx.rest_flags_recorded(None, None) == []


def test_it_never_claims_more_than_the_complete_reading_and_never_a_disadvantage() -> None:
    values = [None, 0.5, 2.0, 2.99, 3.0, 3.5, 6.0, 9.5, 20.0]
    for home, away in itertools.product(values, values):
        recorded = ctx.rest_flags_recorded(home, away)
        assert set(recorded) <= set(ctx.rest_flags(home, away)), (home, away)
        assert not any(f.endswith("rest_disadvantage") for f in recorded), (home, away)


def test_the_calendar_block_says_what_the_numbers_are() -> None:
    cal = ctx.CALENDAR_SCOPE
    assert cal["scope"] == "tracked_competitions" and cal["complete"] is None
    assert cal["rest_days"] == "at_most" and cal["matches_last_14d"] == "at_least" and cal["next_match"] == "known_only"
    assert "competitions" in cal["note"]
