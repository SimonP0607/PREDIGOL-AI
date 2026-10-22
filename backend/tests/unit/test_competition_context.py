"""``fbi.competitions.context``, the pure part: what a match's place in its competition says BEFORE it is played (plan F2).

The database reader is in ``tests/integration/test_competition_context.py`` (with the leak tests: the stored winner and aggregate
are poisoned and nothing may move). Here: the arithmetic of a second leg, the formats a tie shows from the first match, and the
one classifier of round labels behind the coarse stage the AI packet has always carried."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.competitions import context as cx

D0 = datetime(2026, 2, 17, 20, tzinfo=UTC)
HOME, AWAY = 10, 20
"""The two sides of the match being played: HOME hosts it."""


def leg(fixture_id: int, day: int, home: int, away: int, goals: tuple[int, int] | None, *, status: str = "FT",
        n: int | None = None, extra_time: bool = False) -> cx.EarlierLeg:
    return cx.EarlierLeg(fixture_id=fixture_id, leg=n, kickoff_at=D0 + timedelta(days=day), home_team_id=home,
                         away_team_id=away, status=status, goals_home=None if goals is None else goals[0],
                         goals_away=None if goals is None else goals[1], extra_time=extra_time)


# ── the second leg of a two-legged tie ──────────────────────────────────────


@pytest.mark.parametrize(("first_leg", "lead", "ahead_if_margin_at_least", "level_if", "behind_if_margin_at_most"), [
    # the first leg was played at AWAY's ground, so HOME's goals are the second number
    ((0, 2), 2, -1, -2, -3),   # HOME won away by two: it stays ahead unless it loses by 2 or more... level at -2
    ((1, 1), 0, 1, 0, -1),     # level: a win needed, a draw leaves it level
    ((2, 1), -1, 2, 1, 0),     # HOME lost away by one: it must win by two to be ahead after 90 minutes; by one it is level
    ((4, 0), -4, 5, 4, 3),
])
def test_what_the_first_ninety_minutes_do_to_the_aggregate(first_leg: tuple[int, int], lead: int,
                                                           ahead_if_margin_at_least: int, level_if: int,
                                                           behind_if_margin_at_most: int) -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(1, -7, AWAY, HOME, first_leg, n=1)])

    assert tie.aggregate == (first_leg[1], first_leg[0])
    assert tie.aggregate[0] - tie.aggregate[1] == lead
    assert tie.outlook == {"kind": "second_leg", "home_side_ahead_if_home_margin_at_least": ahead_if_margin_at_least,
                           "level_if_home_margin_is": level_if,
                           "away_side_ahead_if_home_margin_at_most": behind_if_margin_at_most,
                           "if_level": "competition_rules"}
    # the three statements agree with the arithmetic for every margin the match could end on
    for margin in range(-6, 7):
        total = lead + margin
        assert (margin >= tie.outlook["home_side_ahead_if_home_margin_at_least"]) == (total > 0)
        assert (margin == tie.outlook["level_if_home_margin_is"]) == (total == 0)
        assert (margin <= tie.outlook["away_side_ahead_if_home_margin_at_most"]) == (total < 0)


def test_the_first_leg_is_read_from_the_point_of_view_of_the_side_that_hosts_the_second() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(7, -7, AWAY, HOME, (3, 1), n=1)])

    only = tie.previous[0]
    assert (only.fixture_id, only.leg, only.home_side_was) == (7, 1, "away")
    assert (only.goals_home_side, only.goals_away_side) == (1, 3)
    assert only.as_json()["kickoff_at"] == (D0 - timedelta(days=7)).isoformat()
    assert (tie.format, tie.leg, tie.legs, tie.without_result) == ("two_legged", 2, 2, 0)


def test_a_first_leg_whose_result_is_not_recorded_leaves_the_aggregate_unknown_not_zero() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(1, -7, AWAY, HOME, None, status="NS", n=1)])

    assert (tie.previous, tie.without_result, tie.aggregate) == ((), 1, None)
    assert tie.outlook == {"kind": "second_leg", "aggregate": "unknown"}


@pytest.mark.parametrize("status", ["PST", "CANC", "ABD", "1H", "NS"])
def test_a_leg_that_was_not_played_to_a_result_is_not_counted_even_with_goals_stored(status: str) -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(1, -7, AWAY, HOME, (2, 0), status=status, n=1)])

    assert tie.aggregate is None and tie.without_result == 1


def test_an_awarded_leg_with_a_score_counts_and_one_without_does_not() -> None:
    awarded = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                           earlier=[leg(1, -7, AWAY, HOME, (0, 3), status="AWD", n=1)])
    walkover = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                            earlier=[leg(1, -7, AWAY, HOME, None, status="WO", n=1)])

    assert awarded.aggregate == (3, 0)
    assert walkover.aggregate is None and walkover.without_result == 1


def test_a_leg_between_other_sides_is_never_claimed_to_belong_to_the_tie() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(1, -7, 99, HOME, (2, 0), n=1)])

    assert tie.previous == () and tie.without_result == 1 and tie.aggregate is None


def test_a_leg_listed_twice_counts_once() -> None:
    first = leg(1, -7, AWAY, HOME, (1, 0), n=1)

    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged", earlier=[first, first])

    assert tie.aggregate == (0, 1) and len(tie.previous) == 1


def test_a_leg_that_went_to_extra_time_says_so() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(1, -7, AWAY, HOME, (1, 2), status="AET", n=1, extra_time=True)])

    assert tie.previous[0].after_extra_time is True and tie.aggregate == (2, 1)


# ── what the first match of a tie can show ──────────────────────────────────


def test_the_first_leg_of_a_two_legged_tie_knows_it_is_the_first_of_two() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=1, stored_format="two_legged", earlier=[])

    assert (tie.format, tie.leg, tie.legs, tie.aggregate, tie.previous) == ("two_legged", 1, 2, None, ())
    assert tie.outlook == {"kind": "first_leg"}


@pytest.mark.parametrize("stored", ["replay", "series"])
def test_the_first_match_of_a_tie_that_needed_a_replay_or_a_third_game_shows_a_single_match(stored: str) -> None:
    """A replay (or the game of a series that follows the first) exists only because the first match was not decisive: the
    stored format would tell the reader how the match about to be played ends. It is not shown."""
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=1, stored_format=stored, earlier=[])

    assert (tie.format, tie.legs) == ("single", 1)
    assert tie.outlook == {"kind": "single_match"}


def test_a_replay_knows_it_is_one_and_what_the_first_match_was() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="replay",
                       earlier=[leg(1, -10, AWAY, HOME, (1, 1), n=1)])

    assert (tie.format, tie.legs, tie.aggregate) == ("replay", 2, (1, 1))
    assert tie.outlook == {"kind": "replay", "decides_the_tie": True}


def test_a_game_of_a_series_counts_the_wins_so_far() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=3, stored_format="series",
                       earlier=[leg(1, -6, HOME, AWAY, (2, 0), n=1), leg(2, -3, AWAY, HOME, (1, 0), n=2)])

    assert tie.format == "series" and tie.legs is None
    assert tie.outlook == {"kind": "series", "game": 3, "wins_home_side": 1, "wins_away_side": 1, "draws": 0,
                           "complete": True}


def test_a_single_match_has_no_aggregate_and_says_so() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=1, stored_format="single", earlier=[])

    assert (tie.format, tie.legs, tie.aggregate, tie.outlook) == ("single", 1, None, {"kind": "single_match"})


def test_an_unknown_stored_format_is_a_single_match_not_a_guess() -> None:
    assert cx.known_format("not_a_bracket", 1) == "single"
    assert cx.known_format("", 2) == "single"


# ── the json that goes into a packet ────────────────────────────────────────


def test_a_phase_is_json_with_its_version_and_the_note_that_says_how_to_read_it() -> None:
    tie = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged",
                       earlier=[leg(5, -7, AWAY, HOME, (2, 1), n=1)])
    phase = cx.Phase(cx.StageOf("Quarter-finals", "knockout", "knockout", "quarter_final"), tie)

    out = phase.as_json()

    assert out["version"] == cx.VERSION == "phase-v1"
    assert (out["stage"], out["kind"], out["role"], out["round_key"]) == ("Quarter-finals", "knockout", "knockout",
                                                                         "quarter_final")
    assert "replay_stage" not in out
    assert out["tie"]["aggregate_before"] == {"home_side": 1, "away_side": 2}
    assert out["tie"]["previous"][0]["goals_home_side"] == 1
    assert out["tie"]["note"] == cx.NOTE and "not assumed" in cx.NOTE
    assert cx.Phase(cx.StageOf("Group Stage", "league", "group", None), None).as_json()["tie"] is None
    assert cx.Phase(cx.StageOf("1st Round Replays", "knockout", "knockout", "round_1", replay=True),
                    None).as_json()["replay_stage"] is True


# ── the one classifier of round labels ──────────────────────────────────────


@pytest.mark.parametrize(("label", "coarse"), [
    (None, "unknown"), ("", "unknown"), ("   ", "unknown"),
    ("Final", "final"), ("Apertura - Final", "final"), ("Champions League - Final", "final"),
    ("Semi-finals", "knockout"), ("Quarter-finals", "knockout"), ("Round of 16", "knockout"), ("8th Finals", "knockout"),
    ("1/8-finals", "knockout"), ("Play-offs", "knockout"), ("3rd Qualifying Round", "knockout"),
    ("Preliminary Round", "knockout"), ("3rd Place Final", "knockout"),
    ("Group Stage - 1", "group"), ("Group A - 3", "group"),
    ("Regular Season - 12", "league"), ("Clausura - 7", "league"), ("Apertura", "league"), ("Final Round - 3", "league"),
    ("Friendlies 1", "league"),
    ("R60310", "unknown"),
])
def test_the_coarse_stage_comes_from_the_one_classifier(label: str | None, coarse: str) -> None:
    assert cx.coarse_stage(label) == coarse


def test_a_label_is_read_with_its_match_day_stripped() -> None:
    reading = cx.reading_of("Regular Season - 12")

    assert reading is not None
    assert (reading.stage, reading.kind, reading.numbered) == ("Regular Season", "league", True)
    assert cx.reading_of(None) is None and cx.reading_of(" ") is None
