"""Which side of a match a man was on (plan F3, ``fbi.people.sides``): when a squad sheet is the other side's, and how the statistics and
the sheets are put together into the team a man was in. The mistake being corrected is the provider's: in 202 matches it gave each team
the other's squad sheet while the statistics of the same match were right."""

from __future__ import annotations

import random
from datetime import date

import pytest

from fbi.people import sides
from fbi.people.player_history import MatchRow, placed_matches

DAY = date(2026, 3, 1)
HOME_TEAM, AWAY_TEAM = 10, 20


def row(man: int, side: str, match: int = 1) -> MatchRow:
    return (man, match, DAY, side, HOME_TEAM, AWAY_TEAM)


def team_of(result: list[tuple[int, int, date, int]], man: int, match: int = 1) -> int | None:
    found = [team for m, f, _, team in result if (m, f) == (man, match)]
    return found[0] if found else None


def test_the_version_and_the_thresholds_of_the_rule_are_the_ones_the_data_was_measured_with() -> None:
    # 404 of 274,813 sheets are crossed, on all but one of their men; nothing lies between 10 % and 90 % of disagreement (production, 22 Oct 2026)
    assert (sides.VERSION, sides.MIN_MEN, sides.APART_PERCENT) == ("sides-v1", 5, 80)


@pytest.mark.parametrize(("men", "apart", "crossed"), [
    (22, 22, True), (22, 21, True), (22, 18, True), (20, 16, True), (20, 15, False), (10, 8, True), (10, 7, False),
    (5, 5, True), (5, 4, True), (5, 3, False), (5, 0, False),
    (4, 4, False), (1, 1, False), (0, 0, False),   # too few men in the statistics to say anything
])
def test_a_sheet_is_crossed_when_enough_of_its_men_are_in_the_statistics_on_the_other_side(men: int, apart: int, crossed: bool) -> None:
    assert sides.is_crossed(men, apart) is crossed


def test_the_other_side_of_a_match() -> None:
    assert (sides.other("home"), sides.other("away")) == ("away", "home")
    assert sides.SIDES == ("home", "away")
    with pytest.raises(KeyError):
        sides.other("neutral")


def test_a_sheet_and_statistics_that_agree_place_every_man_on_his_side() -> None:
    sheet = [row(1, "home"), row(2, "away")]
    statistics = [row(1, "home"), row(2, "away")]
    result, nowhere = placed_matches(sheet, statistics, frozenset())
    assert nowhere == 0 and team_of(result, 1) == HOME_TEAM and team_of(result, 2) == AWAY_TEAM and len(result) == 2


def test_the_statistics_win_over_the_sheet_for_a_man_they_name() -> None:
    result, nowhere = placed_matches([row(1, "home")], [row(1, "away")], frozenset())
    assert nowhere == 0 and result == [(1, 1, DAY, AWAY_TEAM)]


def test_a_man_only_the_sheet_names_is_on_the_side_of_his_sheet_and_one_only_the_statistics_name_is_where_they_say() -> None:
    result, nowhere = placed_matches([row(1, "home")], [row(2, "away")], frozenset())
    assert nowhere == 0 and sorted(result) == [(1, 1, DAY, HOME_TEAM), (2, 1, DAY, AWAY_TEAM)]


def test_a_crossed_sheet_is_read_as_the_other_sides_for_the_men_the_statistics_do_not_name() -> None:
    # the sheet that says "home" is really the away team's: its bench (not in the statistics) is the away team's too
    sheet = [row(1, "home"), row(2, "home"), row(3, "away"), row(4, "away")]
    statistics = [row(1, "away")]   # one of the eleven who played
    result, nowhere = placed_matches(sheet, statistics, frozenset({(1, "home"), (1, "away")}))
    assert nowhere == 0
    assert (team_of(result, 1), team_of(result, 2), team_of(result, 3), team_of(result, 4)) == (AWAY_TEAM, AWAY_TEAM, HOME_TEAM, HOME_TEAM)


def test_only_the_sheet_that_is_crossed_is_turned_round() -> None:
    sheet = [row(1, "home"), row(2, "away")]
    result, _ = placed_matches(sheet, [], frozenset({(1, "home")}))
    assert (team_of(result, 1), team_of(result, 2)) == (AWAY_TEAM, AWAY_TEAM), "the sheet is turned by its (match, side), the other is not"
    result, _ = placed_matches(sheet, [], frozenset({(2, "home")}))     # another match's sheet
    assert (team_of(result, 1), team_of(result, 2)) == (HOME_TEAM, AWAY_TEAM)


def test_a_man_in_both_sheets_and_not_in_the_statistics_is_nowhere() -> None:
    sheet = [row(1, "home"), row(1, "away"), row(2, "home")]
    result, nowhere = placed_matches(sheet, [], frozenset())
    assert nowhere == 1 and result == [(2, 1, DAY, HOME_TEAM)]
    # ...but the statistics place him when they name him
    result, nowhere = placed_matches(sheet, [row(1, "away")], frozenset())
    assert nowhere == 0 and sorted(result) == [(1, 1, DAY, AWAY_TEAM), (2, 1, DAY, HOME_TEAM)]


def test_a_man_in_both_sheets_of_a_match_whose_sheets_are_crossed_stays_in_both() -> None:
    result, nowhere = placed_matches([row(1, "home"), row(1, "away")], [], frozenset({(1, "home"), (1, "away")}))
    assert nowhere == 1 and result == []


def test_a_match_with_no_statistics_keeps_its_sheet() -> None:
    sheet = [row(n, "home") for n in range(1, 12)] + [row(n, "away") for n in range(12, 23)]
    result, nowhere = placed_matches(sheet, [], frozenset())
    assert nowhere == 0 and all(team_of(result, n) == (HOME_TEAM if n < 12 else AWAY_TEAM) for n in range(1, 23))


def test_the_same_man_in_two_matches_is_placed_in_each_by_its_own_facts() -> None:
    sheet = [row(1, "home", match=1), row(1, "away", match=2)]
    result, nowhere = placed_matches(sheet, [row(1, "home", match=2)], frozenset({(1, "home")}))
    # match 1: his sheet is crossed -> away; match 2: the statistics say home
    assert nowhere == 0 and sorted(result) == [(1, 1, DAY, AWAY_TEAM), (1, 2, DAY, HOME_TEAM)]


def test_the_result_does_not_depend_on_the_order_of_the_rows() -> None:
    rng = random.Random(2026)
    for _ in range(200):
        sheet = [row(rng.randrange(1, 30), rng.choice(sides.SIDES), rng.randrange(1, 4)) for _ in range(rng.randrange(0, 40))]
        statistics = [row(rng.randrange(1, 30), rng.choice(sides.SIDES), rng.randrange(1, 4)) for _ in range(rng.randrange(0, 25))]
        crossed = frozenset((rng.randrange(1, 4), rng.choice(sides.SIDES)) for _ in range(rng.randrange(0, 3)))
        expected = placed_matches(sheet, statistics, crossed)
        shuffled_sheet, shuffled_statistics = sheet[:], statistics[:]
        rng.shuffle(shuffled_sheet)
        rng.shuffle(shuffled_statistics)
        assert placed_matches(shuffled_sheet, shuffled_statistics, crossed) == expected


def test_whatever_the_sheets_say_the_statistics_decide_the_men_they_name() -> None:
    rng = random.Random(7)
    for _ in range(200):
        sheet = [row(rng.randrange(1, 30), rng.choice(sides.SIDES)) for _ in range(rng.randrange(0, 40))]
        by_stats = {rng.randrange(1, 30): rng.choice(sides.SIDES) for _ in range(rng.randrange(0, 20))}
        crossed = frozenset(rng.sample([(1, "home"), (1, "away")], rng.randrange(0, 3)))
        result, _ = placed_matches(sheet, [row(m, s) for m, s in by_stats.items()], crossed)
        for man, side in by_stats.items():
            assert team_of(result, man) == (HOME_TEAM if side == "home" else AWAY_TEAM)
