"""RP-2.2: the coherent ladder of lines (``ladder-projection-v1``). Pure: figures in, figures out."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.forecasting import battery, ladder
from fbi.forecasting.battery import Figure

# a real distribution of goals: total T ~ a fixed pmf; difference d ~ a fixed pmf
TOTAL = {0: 0.08, 1: 0.2, 2: 0.26, 3: 0.22, 4: 0.13, 5: 0.07, 6: 0.04}
DIFF = {-3: 0.04, -2: 0.09, -1: 0.2, 0: 0.27, 1: 0.2, 2: 0.14, 3: 0.06}
OU_LINES = [
    Decimal(x) for x in ("0.5", "0.75", "1", "1.25", "1.5", "2", "2.25", "2.5", "3", "3.5", "4.5")
]
AH_LINES = [
    Decimal(x) for x in ("-1.5", "-1.25", "-1", "-0.5", "-0.25", "0", "0.25", "0.5", "1", "1.5")
]


def _over(pmf: dict[int, float], line: Decimal) -> tuple[float, float]:
    """(win, push) of Over (or Home) for a half, whole or quarter line, the quarter being half the stake on each neighbour."""
    if abs(line * 4) % 2 == 1:
        a, b = _over(pmf, line - Decimal("0.25")), _over(pmf, line + Decimal("0.25"))
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    return sum(p for k, p in pmf.items() if k > line), sum(p for k, p in pmf.items() if k == line)


def _home(line: Decimal) -> tuple[float, float]:
    """Home at handicap ``line``: wins when the difference plus the handicap is positive."""
    if abs(line * 4) % 2 == 1:
        a, b = _home(line - Decimal("0.25")), _home(line + Decimal("0.25"))
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    return sum(p for k, p in DIFF.items() if k + line > 0), sum(
        p for k, p in DIFF.items() if k + line == 0
    )


def coherent() -> list[Figure]:
    return [
        Figure(
            f.market,
            f.selection,
            f.line,
            round(f.win, 9),
            round(f.push, 9),
            None if f.lo is None else round(f.lo, 9),
            None if f.hi is None else round(f.hi, 9),
        )
        for f in _raw()
    ]


def _raw() -> list[Figure]:
    out: list[Figure] = []
    for line in OU_LINES:
        w, p = _over(TOTAL, line)
        out += [
            Figure("OU", "Over", line, w, p, w - 0.05, w + 0.05),
            Figure("OU", "Under", line, 1 - w - p, p, 1 - w - p - 0.05, 1 - w - p + 0.05),
        ]
    for line in AH_LINES:
        w, p = _home(line)
        away_w = 1 - w - p
        out += [
            Figure("AH", "Home", line, w, p, w - 0.05, w + 0.05),
            Figure("AH", "Away", -line, away_w, p, away_w - 0.05, away_w + 0.05),
        ]
    home = sum(p for k, p in DIFF.items() if k > 0)
    draw = DIFF[0]
    out += [
        Figure("1X2", "Home", Decimal(0), home),
        Figure("1X2", "Draw", Decimal(0), draw),
        Figure("1X2", "Away", Decimal(0), 1 - home - draw),
    ]
    return out


def by(figs: list[Figure]) -> dict[tuple[str, str, Decimal], Figure]:
    return {f.key: f for f in figs}


def test_the_figures_of_a_real_distribution_are_already_coherent() -> None:
    assert battery.check(coherent()).publishable, battery.check(coherent()).violations
    for mode in ladder.MODES:
        p = ladder.project(coherent(), mode=mode)
        assert p.figures == tuple(sorted(coherent(), key=lambda f: f.key)), (
            "a coherent set comes back exactly as it was"
        )
        assert p.moved() == 0
        assert ladder.project(p.figures, mode=mode).figures == p.figures, (
            "projecting twice is projecting once"
        )


def test_pava_is_the_closest_monotone_sequence() -> None:
    assert ladder.pava([3.0, 2.0, 1.0], [1, 1, 1], increasing=False) == [3.0, 2.0, 1.0]
    assert ladder.pava([1.0, 3.0, 2.0], [1, 1, 1], increasing=False) == [
        1.0,
        2.0,
        2.0,
    ] or ladder.pava([1.0, 3.0, 2.0], [1, 1, 1], increasing=False) == [2.0, 2.0, 2.0]
    got = ladder.pava([0.4, 0.6, 0.5], [1, 1, 1], increasing=False)
    assert got == pytest.approx([0.5, 0.5, 0.5]), (
        "a violation pools the neighbours that break the order, keeping their weighted mean"
    )
    assert ladder.pava([0.1, 0.3, 0.2], [1, 1, 1], increasing=True) == pytest.approx(
        [0.1, 0.25, 0.25]
    )
    heavy = ladder.pava([0.9, 0.2, 0.3], [1000.0, 1.0, 1.0], increasing=False)
    assert heavy[0] == pytest.approx(0.9) and heavy[1] == heavy[2], (
        "a figure with a huge weight stays where it is"
    )


def broken() -> list[Figure]:
    """The same distribution with 1.0 and 1.5 calibrated on their own: more than 1.0 is told below more than 1.5 (impossible)."""
    figs = by(coherent())
    for sel in ("Over", "Under"):
        f = figs[("OU", sel, Decimal("1.5"))]
        w = 0.80 if sel == "Over" else 0.15
        figs[f.key] = Figure("OU", sel, Decimal("1.5"), w, 0.0, w - 0.05, w + 0.05)
    return list(figs.values())


@pytest.mark.parametrize("mode", ladder.MODES)
def test_a_ladder_that_contradicts_itself_becomes_publishable(mode: ladder.Mode) -> None:
    bad = broken()
    assert not battery.check(bad).publishable
    p = ladder.project(bad, mode=mode)
    rep = battery.check(p.figures)
    assert (
        rep.by_test()[3] == 0
        and rep.by_test()[7] == 0
        and rep.by_test()[1] == 0
        and rep.by_test()[8] == 0
    ), rep.violations
    out = by(list(p.figures))
    assert out[("OU", "Over", Decimal("1.5"))].win == pytest.approx(
        out[("OU", "Over", Decimal("1.5"))].win
    )
    over = [
        out[("OU", "Over", line)].win
        for line in (Decimal("0.5"), Decimal("1.5"), Decimal("2.5"), Decimal("3.5"))
    ]
    assert over == sorted(over, reverse=True), "the half lines go down as the line goes up"


@pytest.mark.parametrize("mode", ladder.MODES)
def test_under_is_what_over_leaves_and_the_other_side_of_a_handicap_is_the_opposite_line(
    mode: ladder.Mode,
) -> None:
    out = by(list(ladder.project(broken(), mode=mode).figures))
    for line in OU_LINES:
        o, u = out[("OU", "Over", line)], out[("OU", "Under", line)]
        assert o.win + o.push + u.win == pytest.approx(1.0, abs=1e-9)
        assert o.push == pytest.approx(u.push, abs=1e-9)
    for line in AH_LINES:
        h, a = out[("AH", "Home", line)], out[("AH", "Away", -line)]
        assert h.win + h.push + a.win == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("mode", ladder.MODES)
def test_a_whole_line_is_read_off_its_half_line_neighbours(mode: ladder.Mode) -> None:
    out = by(list(ladder.project(broken(), mode=mode).figures))
    lo, hi = out[("OU", "Over", Decimal("2.5"))].win, out[("OU", "Over", Decimal("1.5"))].win
    f = out[("OU", "Over", Decimal("2"))]
    assert f.win == pytest.approx(lo) and f.push == pytest.approx(hi - lo), (
        "over 2 wins when the goals pass 2.5 and is returned on exactly 2"
    )


@pytest.mark.parametrize("mode", ladder.MODES)
def test_the_one_x_two_pins_down_the_handicap_that_it_names(mode: ladder.Mode) -> None:
    figs = by(broken())
    # the handicap -0.5 is the home win and +0.5 home plus draw (test 4): a stored figure that disagrees is taken to the 1X2, never the 1X2 to it
    home = figs[("1X2", "Home", Decimal(0))].win
    figs[("AH", "Home", Decimal("-0.5"))] = Figure("AH", "Home", Decimal("-0.5"), home + 0.03, 0.0)
    figs[("AH", "Away", Decimal("0.5"))] = Figure(
        "AH", "Away", Decimal("0.5"), 1 - home - 0.03, 0.0
    )
    out = by(list(ladder.project(list(figs.values()), mode=mode).figures))
    assert out[("1X2", "Home", Decimal(0))].win == home, "the 1X2 does not move"
    assert out[("AH", "Home", Decimal("-0.5"))].win == pytest.approx(home, abs=1e-6)
    assert battery.check(list(out.values())).by_test()[4] == 0


@pytest.mark.parametrize("mode", ladder.MODES)
def test_the_interval_stretches_to_hold_the_figure_and_no_probability_is_scaled(
    mode: ladder.Mode,
) -> None:
    p = ladder.project(broken(), mode=mode)
    for f in p.figures:
        if f.lo is not None and f.hi is not None:
            assert f.lo <= f.win <= f.hi
    for line in OU_LINES:
        f = by(list(p.figures))[("OU", "Over", line)]
        assert f.win >= 0.0 and f.win + f.push <= 1.0 + 1e-12


def test_a_line_without_its_neighbours_keeps_its_figure_and_is_counted() -> None:
    figs = [
        f
        for f in coherent()
        if not (f.market == "OU" and f.line in (Decimal("2.5"), Decimal("3.5")))
    ]
    p = ladder.project(figs, mode="half")
    kinds = {m.key: m.kind for m in p.moves}
    assert kinds[("OU", "Over", Decimal("3"))] == "kept", (
        "whole line 3 needs 2.5 and 3.5: both are gone"
    )
    assert (
        by(list(p.figures))[("OU", "Over", Decimal("3"))] == by(figs)[("OU", "Over", Decimal("3"))]
    )
    pooled = ladder.project(figs, mode="pooled")
    assert {m.key: m.kind for m in pooled.moves}[("OU", "Over", Decimal("3"))] == "derived", (
        "pooled: the whole line itself tells the two half lines it sits between"
    )
    assert (
        by(list(pooled.figures))[("OU", "Over", Decimal("3"))]
        == by(figs)[("OU", "Over", Decimal("3"))]
    )


def test_a_market_with_fewer_than_two_half_lines_is_not_a_ladder() -> None:
    one = [
        Figure("OU", "Over", Decimal("2.5"), 0.5, 0.0),
        Figure("OU", "Under", Decimal("2.5"), 0.5, 0.0),
    ]
    p = ladder.project(one, mode="half")
    assert p.figures == tuple(sorted(one, key=lambda f: f.key)) and p.moves == ()


def test_pooled_reads_a_whole_line_as_two_half_lines_and_half_does_not() -> None:
    # only a whole line and one half line are told: half has one half line (no ladder); pooled has three nodes
    figs = [
        Figure("OU", "Over", Decimal("2.5"), 0.40, 0.0),
        Figure("OU", "Over", Decimal("2"), 0.55, 0.20),
        Figure("OU", "Over", Decimal("3"), 0.30, 0.10),
    ]
    assert ladder.project(figs, mode="half").moves == ()
    pooled = ladder.project(figs, mode="pooled")
    assert pooled.moves, "the whole lines say something about the half lines"


def test_the_shifts_are_reported_without_the_lines_that_were_kept() -> None:
    p = ladder.project(broken(), mode="pooled")
    s = ladder.shifts([p])
    assert (
        0.0 < s["share_moved"] < 1.0 and s["max_shift"] >= s["p90_shift"] >= s["median_shift"] > 0.0
    )
    assert set(ladder.by_market([p])) <= {"OU", "AH"}
    assert ladder.shifts([ladder.project(coherent())])["moved"] == 0.0


def test_the_projection_never_reads_the_outcome_or_changes_the_input() -> None:
    before = broken()
    snapshot = list(before)
    ladder.project(before, mode="pooled")
    assert before == snapshot
