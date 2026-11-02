"""A live reading the table cannot hold is told apart before it reaches the INSERT (``LiveMatchState.impossible``).

On 25 Oct 2026, at 01:00 UTC, when the clocks changed, the provider sent minutes 59 short: -2 in a second half, -38, -37
and -44 in first halves, one match per minute. The table's CHECK refused the row and the whole batch of 19 matches rolled
back, four minutes running. The limits here are the table's own (migration 0041); the integration test next to this one
pins them to the database itself."""

from __future__ import annotations

import pytest

from fbi.ingestion.live_match import MINUTE_MAX, SMALLINT_MAX, LiveMatchState, iter_live_states


def state(*, elapsed: int | None = 10, extra: int | None = None, home: int | None = 0,
          away: int | None = 0) -> LiveMatchState:
    return LiveMatchState(5, "1H", elapsed, extra, home, away)


@pytest.mark.parametrize("elapsed", [None, 0, 1, 45, 90, 120, MINUTE_MAX])
def test_every_minute_a_match_can_have_is_storable(elapsed: int | None) -> None:
    assert state(elapsed=elapsed).impossible() is None


@pytest.mark.parametrize("elapsed", [-1, -2, -37, -38, -44, MINUTE_MAX + 1, SMALLINT_MAX, SMALLINT_MAX + 1])
def test_the_minutes_of_the_day_the_clocks_changed_and_the_ones_past_the_limit_are_impossible(elapsed: int) -> None:
    assert state(elapsed=elapsed).impossible() == f"elapsed {elapsed}"


@pytest.mark.parametrize("extra", [None, 0, 1, 8, 30, SMALLINT_MAX])
def test_every_added_time_is_storable(extra: int | None) -> None:
    assert state(extra=extra).impossible() is None


@pytest.mark.parametrize("extra", [-1, -60, SMALLINT_MAX + 1])
def test_a_negative_added_time_is_impossible_although_the_table_would_take_it(extra: int) -> None:
    assert state(extra=extra).impossible() == f"extra {extra}"


@pytest.mark.parametrize("goals", [None, 0, 1, 7, 12, SMALLINT_MAX])
def test_every_score_is_storable(goals: int | None) -> None:
    assert state(home=goals, away=goals).impossible() is None


@pytest.mark.parametrize("goals", [-1, -5, SMALLINT_MAX + 1])
def test_a_score_below_nothing_or_past_the_column_is_impossible_on_either_side(goals: int) -> None:
    assert state(home=goals).impossible() == f"goals_home {goals}"
    assert state(away=goals).impossible() == f"goals_away {goals}"


def test_the_first_thing_wrong_is_the_one_said() -> None:
    assert state(elapsed=-3, extra=-1, home=-1, away=-1).impossible() == "elapsed -3"
    assert state(extra=-1, home=-1, away=-1).impossible() == "extra -1"
    assert state(home=-1, away=-1).impossible() == "goals_home -1"


def test_a_reading_with_nothing_to_say_is_not_impossible() -> None:
    """Not started, no minute, no score: nothing the table could refuse."""
    assert LiveMatchState(5, "NS", None, None, None, None).impossible() is None


@pytest.mark.parametrize(("elapsed", "reading"), [(-38, "elapsed -38"), ("-38", "elapsed -38"), (63, None), ("63", None)])
def test_the_reading_the_provider_sent_reaches_the_check_as_it_sent_it(elapsed: int | str, reading: str | None) -> None:
    """The parser does not clean the minute: it accepts a negative one, as an integer or as a string, and the check is
    what stops it (a clean-up in the parser would hide from the run's notes that the provider sent it)."""
    body = {"response": [{"fixture": {"id": 5, "status": {"short": "1H", "elapsed": elapsed, "extra": None}},
                          "goals": {"home": 0, "away": 0}}]}
    (read,) = iter_live_states(body)
    assert read.elapsed == int(elapsed)
    assert read.impossible() == reading
