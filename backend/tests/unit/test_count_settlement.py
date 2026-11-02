"""Plan F11 - how a bet on a count of the match (corners, cards, the goals of a half) settles once the count is known."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.market.rules import RULES_BY_KEY, RULES_BY_MEASURE
from fbi.picks.count_settlement import count_outcome, halves_outcome, settle_numbers
from fbi.picks.settlement import Status

D = Decimal


@pytest.mark.parametrize(("selection", "line", "expected"), [
    ("Over", "9.5", Status.WIN), ("Under", "9.5", Status.LOSS),
    ("Over", "10.5", Status.LOSS), ("Under", "10.5", Status.WIN),
    ("Over", "10", Status.PUSH), ("Under", "10", Status.PUSH),
    ("Over", "10.25", Status.HALF_LOSS), ("Under", "10.25", Status.HALF_WIN),
    ("Over", "9.75", Status.HALF_WIN), ("Under", "9.75", Status.HALF_LOSS),
])
def test_the_total_of_a_match_is_graded_against_a_line_and_a_quarter_line_is_two_half_stakes(selection: str, line: str, expected: Status) -> None:
    assert count_outcome("over_under", "match", selection, D(line), 6, 4) is expected


def test_a_line_on_one_side_reads_only_that_side() -> None:
    assert count_outcome("over_under", "home", "Over", D("5.5"), 6, 4) is Status.WIN
    assert count_outcome("over_under", "away", "Over", D("5.5"), 6, 4) is Status.LOSS
    assert count_outcome("over_under", "away", "Under", D("4.5"), 6, 4) is Status.WIN


def test_odd_and_even() -> None:
    assert count_outcome("odd_even", "match", "Even", D(0), 6, 4) is Status.WIN
    assert count_outcome("odd_even", "match", "Odd", D(0), 6, 4) is Status.LOSS
    assert count_outcome("odd_even", "home", "Even", D(0), 6, 4) is Status.WIN
    assert count_outcome("odd_even", "away", "Odd", D(0), 6, 5) is Status.WIN


def test_who_has_more_and_double_chance() -> None:
    assert count_outcome("one_x_two", "match", "Home", D(0), 7, 4) is Status.WIN
    assert count_outcome("one_x_two", "match", "Draw", D(0), 5, 5) is Status.WIN
    assert count_outcome("one_x_two", "match", "Away", D(0), 7, 4) is Status.LOSS
    assert count_outcome("double_chance", "match", "1X", D(0), 5, 5) is Status.WIN
    assert count_outcome("double_chance", "match", "12", D(0), 5, 5) is Status.LOSS
    assert count_outcome("double_chance", "match", "X2", D(0), 3, 8) is Status.WIN


def test_draw_no_bet_gives_the_stake_back_when_the_counts_are_level() -> None:
    assert count_outcome("draw_no_bet", "match", "Home", D(0), 4, 4) is Status.PUSH
    assert count_outcome("draw_no_bet", "match", "Away", D(0), 4, 4) is Status.PUSH
    assert count_outcome("draw_no_bet", "match", "Home", D(0), 5, 4) is Status.WIN
    assert count_outcome("draw_no_bet", "match", "Away", D(0), 5, 4) is Status.LOSS
    with pytest.raises(ValueError, match="draw-no-bet"):
        count_outcome("draw_no_bet", "match", "Draw", D(0), 5, 4)


def test_both_teams_score_in_a_period_and_the_handicap_on_counts() -> None:
    assert count_outcome("both_teams_score", "match", "No", D(0), 1, 0) is Status.WIN
    assert count_outcome("both_teams_score", "match", "Yes", D(0), 1, 1) is Status.WIN
    assert count_outcome("asian_handicap", "match", "Home", D("-1.5"), 7, 5) is Status.WIN
    assert count_outcome("asian_handicap", "match", "Home", D("-2"), 7, 5) is Status.PUSH
    assert count_outcome("asian_handicap", "match", "Home", D("-2.25"), 7, 5) is Status.HALF_LOSS
    assert count_outcome("asian_handicap", "match", "Away", D("1.75"), 7, 5) is Status.HALF_LOSS
    assert count_outcome("asian_handicap", "match", "Away", D("2.25"), 7, 5) is Status.HALF_WIN
    assert count_outcome("asian_handicap", "match", "Away", D("2.5"), 7, 5) is Status.WIN


def test_half_time_full_time_reads_the_two_halves() -> None:
    first, second = (1, 0), (0, 1)  # ahead at the break, level at the end
    assert halves_outcome("half_time_full_time", "match", "Home/Draw", first, second) is Status.WIN
    for lost in ("Home/Home", "Draw/Draw", "Away/Away", "Draw/Home"):
        assert halves_outcome("half_time_full_time", "match", lost, first, second) is Status.LOSS
    assert halves_outcome("half_time_full_time", "match", "Draw/Away", (0, 0), (0, 2)) is Status.WIN
    with pytest.raises(ValueError, match="HT/FT"):
        halves_outcome("half_time_full_time", "match", "Home", first, second)


def test_the_highest_scoring_half_of_the_match_and_of_each_side() -> None:
    assert halves_outcome("highest_scoring_half", "match", "2nd Half", (1, 0), (0, 2)) is Status.WIN
    assert halves_outcome("highest_scoring_half", "match", "1st Half", (2, 1), (0, 1)) is Status.WIN
    assert halves_outcome("highest_scoring_half", "match", "Draw", (1, 1), (2, 0)) is Status.WIN
    assert halves_outcome("highest_scoring_half", "home", "1st Half", (2, 1), (0, 3)) is Status.WIN
    assert halves_outcome("highest_scoring_half", "away", "2nd Half", (2, 1), (0, 3)) is Status.WIN
    with pytest.raises(ValueError, match="highest-scoring-half"):
        halves_outcome("highest_scoring_half", "match", "Home", (1, 0), (0, 2))


def test_a_kind_a_subject_or_a_selection_it_does_not_know_is_an_error_not_a_loss() -> None:
    with pytest.raises(ValueError, match="no settlement"):
        count_outcome("correct_score", "match", "1-0", D(0), 1, 0)
    with pytest.raises(ValueError, match="not graded here"):
        count_outcome("over_under", "player", "Over", D("0.5"), 1, 0)
    with pytest.raises(ValueError, match="compares the two sides"):
        count_outcome("one_x_two", "home", "Home", D(0), 1, 0)
    with pytest.raises(ValueError, match="selection"):
        count_outcome("over_under", "match", "Maybe", D("2.5"), 1, 0)


def test_the_rule_says_which_columns_are_read_and_a_missing_count_is_never_a_zero() -> None:
    rule = RULES_BY_KEY["corners_ft@v1"]
    values = {"corners_ft_home": 6, "corners_ft_away": 5, "yellow_ft_home": 1}
    assert settle_numbers(rule, "over_under", "match", "Over", D("10.5"), values) is Status.WIN
    assert settle_numbers(rule, "over_under", "match", "Under", D("10.5"), values) is Status.LOSS
    assert settle_numbers(rule, "one_x_two", "match", "Home", D(0), values) is Status.WIN
    assert settle_numbers(rule, "over_under", "match", "Under", D("1.5"), {**values, "corners_ft_away": None}) is None, "unknown is not zero"
    assert settle_numbers(rule, "over_under", "match", "Under", D("1.5"), {"corners_ft_home": 6}) is None, "a column the row lacks is unknown"


def test_a_rule_that_cannot_grade_grades_nothing() -> None:
    no_data = RULES_BY_KEY["corners_1h@v1"]
    assert not no_data.liquidable
    assert settle_numbers(no_data, "over_under", "match", "Over", D("4.5"), {"corners_ft_home": 9, "corners_ft_away": 9}) is None


def test_the_rule_of_both_halves_reads_four_numbers() -> None:
    rule = RULES_BY_MEASURE["goals_halves"]
    values = {"goals_1h_home": 1, "goals_1h_away": 0, "goals_2h_home": 0, "goals_2h_away": 1}
    assert settle_numbers(rule, "half_time_full_time", "match", "Home/Draw", D(0), values) is Status.WIN
    assert settle_numbers(rule, "highest_scoring_half", "match", "Draw", D(0), values) is Status.WIN
    assert settle_numbers(rule, "half_time_full_time", "match", "Home/Draw", D(0), {**values, "goals_2h_away": None}) is None


def test_every_rule_that_grades_reads_a_pair_of_counts_or_the_four_of_the_halves() -> None:
    for rule in RULES_BY_KEY.values():
        if rule.liquidable:
            assert len(rule.columns) == (4 if rule.measure == "goals_halves" else 2), rule.key
