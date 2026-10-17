"""The model and the settlement engine must agree about what a line means.

Two independent implementations of the same convention: ``fbi.models.lines``
computes the probability a bet wins from the score matrix, and
``fbi.picks.settlement`` decides what a bet paid out given a score. They were
written for different purposes and they never call each other. If they disagree
about a line, the system prices one bet and settles a different one - which
would show up as a backtest that looks profitable and a ledger that is not, with
nothing in the code obviously wrong.

So the probabilities are checked against the settlement engine run over every
score the matrix gives weight to. That is not a sample or a simulation: it is the
exact expectation, summed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.models.lines import asian_handicap, double_chance, over_under
from fbi.models.scoring import dc_tau, poisson_matrix
from fbi.picks.settlement import Status, market_outcome, profit

MATRIX = dc_tau(poisson_matrix(1.55, 1.20), 1.55, 1.20, -0.04)

WIN_SHARE = {
    Status.WIN: 1.0,
    Status.HALF_WIN: 0.5,
    Status.PUSH: 0.0,
    Status.HALF_LOSS: 0.0,
    Status.LOSS: 0.0,
}
"""The fraction of the stake that is WON, per settlement status."""

PUSH_SHARE = {
    Status.WIN: 0.0,
    Status.HALF_WIN: 0.5,
    Status.PUSH: 1.0,
    Status.HALF_LOSS: 0.5,
    Status.LOSS: 0.0,
}
"""The fraction of the stake RETURNED. A quarter line that half-wins has half
its stake returned, which is exactly why the averaged pair in lines.py carries
half the whole leg's push probability."""


def settled_expectation(
    market: str, selection: str, line: Decimal
) -> tuple[float, float]:
    """(win share, push share) summed over the whole score distribution, using
    the settlement engine to decide each score."""
    m = MATRIX / MATRIX.sum()
    win = push = 0.0
    for home in range(m.shape[0]):
        for away in range(m.shape[1]):
            p = float(m[home, away])
            if p <= 0:
                continue
            status = market_outcome(market, selection, line, home, away)
            win += p * WIN_SHARE[status]
            push += p * PUSH_SHARE[status]
    return win, push


AH_LINES = ["-2.5", "-2", "-1.75", "-1.5", "-1.25", "-1", "-0.75", "-0.5",
            "-0.25", "0", "0.25", "0.5", "0.75", "1", "1.5", "2", "2.5"]
OU_LINES = ["0.5", "0.75", "1", "1.25", "1.5", "1.75", "2", "2.25", "2.5",
            "2.75", "3", "3.25", "3.5", "4", "4.5", "5", "5.5", "6.5"]


@pytest.mark.parametrize("selection", ["Home", "Away"])
@pytest.mark.parametrize("line", AH_LINES)
def test_asian_handicap_probability_matches_what_settlement_pays(
    selection: str, line: str
) -> None:
    want_win, want_push = settled_expectation("AH", selection, Decimal(line))
    got = asian_handicap(MATRIX, selection=selection, line=Decimal(line))
    assert got.win == pytest.approx(want_win, abs=1e-12), f"{selection} {line}"
    assert got.push == pytest.approx(want_push, abs=1e-12), f"{selection} {line}"


@pytest.mark.parametrize("selection", ["Over", "Under"])
@pytest.mark.parametrize("line", OU_LINES)
def test_over_under_probability_matches_what_settlement_pays(
    selection: str, line: str
) -> None:
    want_win, want_push = settled_expectation("OU", selection, Decimal(line))
    got = over_under(MATRIX, selection=selection, line=Decimal(line))
    assert got.win == pytest.approx(want_win, abs=1e-12), f"{selection} {line}"
    assert got.push == pytest.approx(want_push, abs=1e-12), f"{selection} {line}"


@pytest.mark.parametrize("selection", ["1X", "X2", "12"])
def test_double_chance_probability_matches_what_settlement_pays(selection: str) -> None:
    want_win, want_push = settled_expectation("DC", selection, Decimal(0))
    got = double_chance(MATRIX)[selection]
    assert got == pytest.approx(want_win, abs=1e-12)
    assert want_push == 0.0, "Double Chance cannot push"


@pytest.mark.parametrize("line", ["-0.75", "-0.25", "0.25", "1.75"])
def test_the_quarter_line_convention_is_the_same_on_both_sides(line: str) -> None:
    """The case that matters most: 44% of our stored Asian Handicap series.

    The settlement engine splits at +/-0.25 and settles the two halves; lines.py
    averages the two legs' probabilities. If either had the split backwards, the
    numbers below would differ.
    """
    for selection in ("Home", "Away"):
        want_win, want_push = settled_expectation("AH", selection, Decimal(line))
        got = asian_handicap(MATRIX, selection=selection, line=Decimal(line))
        assert got.win == pytest.approx(want_win, abs=1e-12), f"{selection} {line}"
        assert got.push == pytest.approx(want_push, abs=1e-12), f"{selection} {line}"


@pytest.mark.parametrize("line", ["-1", "-0.75", "-0.5", "0"])
def test_the_fair_price_is_the_one_that_breaks_even_when_settled(line: str) -> None:
    """The end-to-end check: price the bet at the model's fair odds, settle it
    over every score, and the profit must come to zero.

    This is what "fair" has to mean. If the push were ignored in the price, this
    sum would be positive - the error would read as an edge that is not there.
    """
    from fbi.models.lines import fair_odds

    outcome = asian_handicap(MATRIX, selection="Home", line=Decimal(line))
    fair = fair_odds(outcome)
    assert fair is not None
    odds = fair.quantize(Decimal("0.00000001"))

    m = MATRIX / MATRIX.sum()
    expected = Decimal(0)
    for home in range(m.shape[0]):
        for away in range(m.shape[1]):
            p = Decimal(str(float(m[home, away])))
            if p <= 0:
                continue
            status = market_outcome("AH", "Home", Decimal(line), home, away)
            expected += p * profit(status, odds, Decimal(1))
    assert abs(expected) < Decimal("0.0005"), f"{line}: {expected}"
