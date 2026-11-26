"""The eight coherence tests (RP-2.2): a set that comes from one distribution of goals passes all of them, and each test catches what it is for."""

from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal

import pytest

from fbi.forecasting import battery as b

D = Decimal
GOALS = range(0, 16)


def pois(mean: float) -> list[float]:
    return [math.exp(-mean) * mean**k / math.factorial(k) for k in GOALS]


def line_pair(win: float, push: float) -> tuple[float, float]:
    return win, push


def figures(home: float = 1.5, away: float = 1.1, *, halves: bool = False) -> list[b.Figure]:
    """Every market of one match from independent Poisson goals (and, with ``halves``, from independent halves)."""
    ph, pa = pois(home), pois(away)
    out: list[b.Figure] = []

    def add(market: str, sel: str, line: D, win: float, push: float = 0.0) -> None:
        out.append(b.Figure(market, sel, line, win, push))

    joint = {(i, j): ph[i] * pa[j] for i in GOALS for j in GOALS}
    h = sum(p for (i, j), p in joint.items() if i > j)
    d = sum(p for (i, j), p in joint.items() if i == j)
    a = sum(p for (i, j), p in joint.items() if i < j)
    for sel, p in (("Home", h), ("Draw", d), ("Away", a)):
        add("1X2", sel, D(0), p)
    add("DC", "1X", D(0), h + d)
    add("DC", "X2", D(0), d + a)
    add("DC", "12", D(0), h + a)
    add("DNB", "Home", D(0), h, d)
    add("DNB", "Away", D(0), a, d)

    def whole_or_half(diff: dict[int, float], line: D) -> tuple[float, float]:
        win = sum(p for g, p in diff.items() if g + line > 0)
        push = sum(p for g, p in diff.items() if g + line == 0)
        return win, push

    def asian(diff: dict[int, float], line: D) -> tuple[float, float]:
        if abs(line * 4) % 2 == 1:
            (w1, p1), (w2, p2) = whole_or_half(diff, line + D("0.25")), whole_or_half(diff, line - D("0.25"))
            return (w1 + w2) / 2, (p1 + p2) / 2
        return whole_or_half(diff, line)

    home_diff: dict[int, float] = {}
    for (i, j), p in joint.items():
        home_diff[i - j] = home_diff.get(i - j, 0.0) + p
    away_diff = {-g: p for g, p in home_diff.items()}
    for q in range(-8, 9):
        line = D(q) / 4
        add("AH", "Home", line, *asian(home_diff, line))
        add("AH", "Away", line, *asian(away_diff, line))

    total: dict[int, float] = {}
    for (i, j), p in joint.items():
        total[i + j] = total.get(i + j, 0.0) + p
    for line in (D("0.5"), D("1.5"), D("2.5"), D("3.5"), D("4.5")):
        over = sum(p for g, p in total.items() if g > line)
        add("OU", "Over", line, over)
        add("OU", "Under", line, 1.0 - over)
        for market, ps in (("OU_HOME", ph), ("OU_AWAY", pa)):
            o = sum(p for g, p in zip(GOALS, ps, strict=True) if g > line)
            add(market, "Over", line, o)
            add(market, "Under", line, 1.0 - o)
    btts = sum(p for (i, j), p in joint.items() if i > 0 and j > 0)
    add("BTTS", "Yes", D(0), btts)
    add("BTTS", "No", D(0), 1.0 - btts)
    if halves:
        first, second = pois((home + away) / 2), pois((home + away) / 2)
        both: dict[int, float] = {}
        for i in GOALS:
            for j in GOALS:
                both[i + j] = both.get(i + j, 0.0) + first[i] * second[j]
        for line in (D("0.5"), D("1.5"), D("2.5")):
            o1 = sum(p for g, p in zip(GOALS, first, strict=True) if g > line)
            o2 = sum(p for g, p in zip(GOALS, second, strict=True) if g > line)
            of = sum(p for g, p in both.items() if g > line)
            out = [f for f in out if not (f.market == "OU" and f.line == line)]
            add("OU", "Over", line, of)
            add("OU", "Under", line, 1.0 - of)
            add("OU_1H", "Over", line, o1)
            add("OU_1H", "Under", line, 1.0 - o1)
            add("OU_2H", "Over", line, o2)
            add("OU_2H", "Under", line, 1.0 - o2)
    return out


def swap(fs: list[b.Figure], key: tuple[str, str, D], **changes: float | None) -> list[b.Figure]:
    return [replace(f, **changes) if f.key == key else f for f in fs]  # type: ignore[arg-type]


def broken_tests(fs: list[b.Figure]) -> set[int]:
    return {v.test for v in b.check(fs).violations}


def test_a_set_from_one_distribution_passes_all_eight() -> None:
    r = b.check(figures())
    assert r.violations == ()
    assert r.publishable
    assert all(r.ran[t] > 0 for t in (1, 2, 3, 4, 5, 7)) and r.ran[6] == 0 and r.ran[8] == 0


def test_halves_run_the_sixth_test_and_pass() -> None:
    r = b.check(figures(halves=True))
    assert r.violations == ()
    assert r.ran[6] > 0


def test_complementary_events_must_add_up_to_one() -> None:
    fs = swap(figures(), ("OU", "Over", D("2.5")), win=0.70)
    assert 1 in broken_tests(fs)
    fs = swap(figures(), ("BTTS", "No", D(0)), win=0.01)
    assert 1 in broken_tests(fs)


def test_a_double_chance_and_the_result_it_leaves_out_add_up_to_one() -> None:
    fs = swap(figures(), ("DC", "1X", D(0)), win=0.99)
    assert {1, 4} <= broken_tests(fs)


def test_the_returned_stake_must_match_on_both_sides() -> None:
    fs = swap(figures(), ("AH", "Away", D("0.0")), push=0.9)
    assert 1 in broken_tests(fs)


def test_exhaustive_results_must_add_up_to_one() -> None:
    fs = swap(figures(), ("1X2", "Draw", D(0)), win=0.5)
    assert 2 in broken_tests(fs)


def test_lines_are_monotone_strictly() -> None:
    fs = figures()
    over_15 = next(f for f in fs if f.key == ("OU", "Over", D("1.5")))
    assert 3 in broken_tests(swap(fs, ("OU", "Over", D("2.5")), win=over_15.win + 0.0001))
    flat = swap(fs, ("OU", "Over", D("2.5")), win=over_15.win)  # equal to the neighbour is not a violation of monotonicity
    assert not [v for v in b.check(flat).violations if v.test == 3 and v.rule == "monotone_lines" and "Over" in v.detail and "OU" in v.detail]
    assert 3 in broken_tests(swap(fs, ("AH", "Home", D("0.5")), win=0.01))  # a bigger handicap never wins less


def test_handicap_lines_rise_for_both_sides() -> None:
    fs = swap(figures(), ("AH", "Away", D("1.0")), win=0.0)
    assert 3 in broken_tests(fs)


def test_result_double_chance_and_handicap_must_coincide() -> None:
    assert 4 in broken_tests(swap(figures(), ("AH", "Home", D("-0.5")), win=0.1))
    assert 4 in broken_tests(swap(figures(), ("DNB", "Home", D(0)), win=0.6))
    assert 4 in broken_tests(swap(figures(), ("DNB", "Away", D(0)), push=0.6))
    assert 4 in broken_tests(swap(figures(), ("AH", "Away", D("0.5")), win=0.9))


def test_the_tolerance_of_the_exact_tests_is_one_millionth() -> None:
    inside = swap(figures(), ("DC", "12", D(0)), win=next(f for f in figures() if f.key == ("DC", "12", D(0))).win + 0.0000005)
    assert 4 not in broken_tests(inside)
    outside = swap(figures(), ("DC", "12", D(0)), win=next(f for f in figures() if f.key == ("DC", "12", D(0))).win + 0.000002)
    assert 4 in broken_tests(outside)


def test_a_total_cannot_be_below_what_a_team_scores_alone() -> None:
    fs = figures()
    team = next(f for f in fs if f.key == ("OU_HOME", "Over", D("1.5")))
    assert 5 in broken_tests(swap(fs, ("OU", "Over", D("1.5")), win=team.win - 0.01))


def test_the_looser_tolerance_of_totals_and_teams_is_a_thousandth() -> None:
    fs = figures()
    team = next(f for f in fs if f.key == ("OU_HOME", "Over", D("1.5")))
    near = swap(fs, ("OU", "Over", D("1.5")), win=team.win - 0.0005)
    assert not [v for v in b.check(near).violations if v.test == 5]
    far = swap(fs, ("OU", "Over", D("1.5")), win=team.win - 0.002)
    assert [v for v in b.check(far).violations if v.test == 5]


def test_a_total_cannot_pass_more_than_the_two_teams_together_would() -> None:
    fs = swap(figures(), ("OU", "Over", D("2.5")), win=0.99)  # needs one team at 2 or more goals: they are far from adding up to that
    assert 5 in broken_tests(fs)


def test_halves_and_the_match_must_coincide() -> None:
    fs = figures(halves=True)
    half = next(f for f in fs if f.key == ("OU_1H", "Over", D("1.5")))
    assert 6 in broken_tests(swap(fs, ("OU", "Over", D("1.5")), win=half.win - 0.01))
    # over 2.5 in the match needs a half with two goals or more: it cannot exceed what the two halves give at 1.5
    assert 6 in broken_tests(swap(fs, ("OU", "Over", D("2.5")), win=0.9))
    assert 6 not in broken_tests(fs)


def test_asian_states_of_a_quarter_line_are_a_distribution_and_pay_the_stored_figure() -> None:
    fs = figures()
    easier = next(f for f in fs if f.key == ("AH", "Home", D("0.25")))
    harder = next(f for f in fs if f.key == ("AH", "Home", D("-0.25")))
    # the nested neighbours: the harder line cannot win more than the easier one, so the half states would go negative
    assert 7 in broken_tests(swap(fs, ("AH", "Home", D("0.0")), win=0.9))  # 0.25 sits between -0.25 and 0.0: not a distribution
    states = b.quarter_states(easier, harder)
    assert sum(states.values()) == pytest.approx(1.0)
    assert states["push"] == 0.0
    assert states["win"] == harder.win and states["loss"] == pytest.approx(easier.lose)


def test_a_figure_that_is_not_what_its_states_pay_is_caught() -> None:
    fs = figures()
    stored = next(f for f in fs if f.key == ("AH", "Home", D("-0.25")))
    assert 7 in broken_tests(swap(fs, ("AH", "Home", D("-0.25")), win=stored.win + 0.01))


def test_a_whole_line_with_more_than_one_of_win_and_push_is_not_a_distribution() -> None:
    assert 7 in broken_tests(swap(figures(), ("AH", "Home", D("0.0")), win=0.8, push=0.4))


def test_the_interval_must_contain_the_figure_strictly() -> None:
    fs = figures()
    f = next(x for x in fs if x.key == ("OU", "Over", D("2.5")))
    assert not broken_tests(swap(fs, f.key, lo=f.win - 0.1, hi=f.win + 0.1))
    assert not broken_tests(swap(fs, f.key, lo=f.win, hi=f.win))  # touching an end is inside
    assert 8 in broken_tests(swap(fs, f.key, lo=f.win + 0.0000001, hi=f.win + 0.1))  # strict: not even a millionth of a margin
    assert 8 in broken_tests(swap(fs, f.key, lo=f.win - 0.1, hi=f.win - 0.0000001))
    assert 8 in broken_tests(swap(fs, f.key, lo=f.win - 0.1, hi=None))


def test_a_test_with_nothing_to_compare_runs_zero_comparisons_and_never_passes_by_absence() -> None:
    r = b.check([b.Figure("OU", "Over", D("2.5"), 0.5)])
    assert r.violations == ()
    assert r.ran == dict.fromkeys(range(1, 9), 0) | {3: 0}
    assert b.check([]).publishable


def test_a_violation_keeps_the_set_from_being_published_and_changes_no_figure() -> None:
    fs = swap(figures(), ("1X2", "Draw", D(0)), win=0.5)
    before = list(fs)
    assert not b.publishable(fs)
    assert fs == before
    doc = b.check(fs).as_json()
    assert doc["publishable"] is False and doc["version"] == b.VERSION
    assert b.check(fs).by_test()[2] == 1
