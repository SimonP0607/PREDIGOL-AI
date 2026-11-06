"""BE-003 (comp-priority-v1): the owner's competitions first among the picks of the day - only an order."""

from __future__ import annotations

import random

import pytest

from fbi.intel import day_priority as dp


@pytest.mark.parametrize(("league", "group"), [
    (2, 1), (39, 1), (140, 1), (78, 1), (61, 1), (94, 1), (135, 1),
    (3, 2), (848, 2), (13, 2), (11, 2), (16, 2), (17, 2), (15, 2), (1168, 2),
    (1, 3), (4, 3), (9, 3), (22, 3), (7, 3), (5, 3), (536, 3), (29, 3), (30, 3), (31, 3), (32, 3), (33, 3), (34, 3),
    (37, 3),
    (40, 4), (88, 4), (239, 4), (18, 4), (6, 4), (10, 4), (None, 4),
], ids=str)
def test_the_group_of_each_competition(league: int | None, group: int) -> None:
    assert dp.group_of(league) == group


def test_no_competition_is_in_two_groups() -> None:
    seen = [league for leagues in dp.GROUPS.values() for league in leagues]
    assert len(seen) == len(set(seen))
    assert set(dp.GROUPS) == {1, 2, 3} and dp.DEFAULT_GROUP == 4
    assert dp.VERSION == "comp-priority-v1"


Row = tuple[str, int | None, float]


def order(rows: list[Row]) -> list[str]:
    return [r[0] for r in dp.order_for_day(rows, league=lambda r: r[1], score=lambda r: r[2])]


def test_group_first_then_score() -> None:
    rows: list[Row] = [("colombia", 239, 90.0), ("qualifier", 32, 70.0), ("libertadores", 13, 60.0),
                       ("ucl-low", 2, 55.0), ("ucl-high", 2, 75.0), ("laliga", 140, 65.0)]
    assert order(rows) == ["ucl-high", "laliga", "ucl-low", "libertadores", "qualifier", "colombia"]


def test_without_priority_competitions_the_order_is_the_previous_one() -> None:
    """daily-set-v6 sorted by -score with Python's stable sort; so does the new order when every row is in group 4,
    ties included."""
    rnd = random.Random(3)
    rows: list[Row] = [(f"s{i}", rnd.choice([40, 88, 239, 262, None]), float(rnd.choice([70, 75, 75, 80, 86])))
                       for i in range(40)]
    assert order(rows) == [r[0] for r in sorted(rows, key=lambda r: -r[2])]


def test_it_only_orders() -> None:
    rows: list[Row] = [("a", 2, 70.0), ("b", 239, 80.0), ("c", 1, 60.0)]
    out = dp.order_for_day(rows, league=lambda r: r[1], score=lambda r: r[2])
    assert sorted(out) == sorted(rows) and all(any(x is y for y in rows) for x in out)
