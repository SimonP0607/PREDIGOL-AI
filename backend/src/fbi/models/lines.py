"""Every line the market quotes, priced from the score matrix we already compute.

The goal model produces a full joint distribution over (home goals, away goals).
Until now seven numbers were read off it - 1X2, Over/Under 2.5, Both Teams Score
- while the capture stores far more than that:

    market  rows     distinct lines   priced by the model
    OU      10,240   26               1  (2.5)
    AH       8,841   45               0
    DC       1,444    1               0

So 91% of the Over/Under series, all 8,841 Asian Handicap prices and all 1,444
Double Chance prices had no model number to compare against. They were being
captured and stored and never used. Nothing new has to be fitted to fix that:
every one of these markets is an exact function of the same matrix.

PUSHES ARE NOT OPTIONAL HERE
----------------------------
Measured over our own stored prices:

    AH   quarter lines 4,309 rows   half lines 2,405   whole lines 2,127
    OU   half lines    5,013 rows   quarter    3,410   whole       1,817

A whole line can push - Over 3.0 with exactly three goals returns the stake -
and a quarter line is two half-stake bets, one of which can push. Only the half
lines are clean two-way bets. Pricing just those would use 27% of the Asian
Handicap series and throw the rest away, so every function here returns a
``LineOutcome`` carrying BOTH probabilities, and the EV arithmetic that consumes
it accounts for the stake returned.

A QUARTER LINE COLLAPSES EXACTLY
--------------------------------
A quarter line such as -0.25 is half a stake at 0.0 and half at -0.5, so its
expected value is the mean of the two legs' expected values:

    EV = ½[w_a(d-1) - (1-w_a-u_a)] + ½[w_b(d-1) - (1-w_b-u_b)]
       = w̄(d-1) - (1 - w̄ - ū)        where w̄ = (w_a+w_b)/2, ū = (u_a+u_b)/2

The averaged pair reproduces the split bet's EV exactly, so a quarter line needs
no special representation downstream - just its own (win, push) pair, with half
the whole leg's push probability. That is not an approximation; the algebra is
above.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "LineOutcome",
    "asian_handicap",
    "double_chance",
    "fair_odds",
    "margin_distribution",
    "over_under",
    "quarter_legs",
    "total_distribution",
]


@dataclass(frozen=True, slots=True)
class LineOutcome:
    """What one side of one line does: win, get the stake back, or lose.

    ``win + push + lose`` is 1 up to the matrix's truncated tail, which the
    caller can see in ``MarketProbabilities.truncated_mass``.
    """

    win: float
    push: float

    @property
    def lose(self) -> float:
        return max(0.0, 1.0 - self.win - self.push)

    @property
    def conditional_win(self) -> float:
        """Win probability given the bet is settled at all.

        This is what the FAIR PRICE is the reciprocal of: a push returns the
        stake, so it is not a loss the price has to cover. Not the number to
        compute expected value per unit STAKED with - for that the push
        probability is needed too, which is why both are carried.
        """
        settled = 1.0 - self.push
        return self.win / settled if settled > 0 else 0.0

    @property
    def pushes(self) -> bool:
        return self.push > 0


def margin_distribution(matrix: NDArray[np.float64]) -> dict[int, float]:
    """P(home goals - away goals = k), from the normalised score matrix.

    The handicap markets are a statement about this distribution and nothing
    else, which is why they need no new model - only this projection.
    """
    total = float(matrix.sum())
    m = matrix / total if total > 0 else matrix
    n = m.shape[0]
    out: dict[int, float] = {}
    for k in range(-(n - 1), n):
        value = float(np.trace(m, offset=-k))
        if value > 0:
            out[k] = value
    return out


def total_distribution(matrix: NDArray[np.float64]) -> dict[int, float]:
    """P(home goals + away goals = k)."""
    total = float(matrix.sum())
    m = matrix / total if total > 0 else matrix
    n = m.shape[0]
    out: dict[int, float] = {}
    for k in range(2 * (n - 1) + 1):
        lo = max(0, k - (n - 1))
        hi = min(k, n - 1)
        value = float(sum(m[i, k - i] for i in range(lo, hi + 1)))
        if value > 0:
            out[k] = value
    return out


def double_chance(matrix: NDArray[np.float64]) -> dict[str, float]:
    """1X, X2 and 12, exactly - they are sums of the 1X2 probabilities.

    No new modelling of any kind: a Double Chance price is a statement about
    the same three outcomes the model already produces. 1,444 stored prices had
    nothing to compare against for want of three additions.
    """
    total = float(matrix.sum())
    m = matrix / total if total > 0 else matrix
    home = float(np.tril(m, -1).sum())
    draw = float(np.trace(m))
    away = float(np.triu(m, 1).sum())
    return {"1X": home + draw, "X2": draw + away, "12": home + away}


def quarter_legs(line: Decimal) -> tuple[Decimal, Decimal] | None:
    """The two half-stake legs of a quarter line, or None if it is not one.

    -0.25 is half a stake at 0.0 and half at -0.5; -0.75 is -1.0 and -0.5.
    """
    frac = abs(line) % Decimal(1)
    if frac not in (Decimal("0.25"), Decimal("0.75")):
        return None
    return line - Decimal("0.25"), line + Decimal("0.25")


def asian_handicap(
    matrix: NDArray[np.float64], *, selection: str, line: Decimal
) -> LineOutcome:
    """One side of an Asian Handicap, at any line the market quotes.

    ``line`` is the handicap that applies to ``selection`` - the convention the
    rest of the system stores, settled by measurement: read that way every pair
    in the raw store devigs to 1.090, read as a per-side signed handicap the
    same pairs devig to 0.47, which is impossible.

    So the bet is on ``margin + line``, where margin is from the selection's
    point of view: positive wins, zero returns the stake, negative loses.
    """
    side = selection.strip().lower()
    if side not in ("home", "away"):
        raise ValueError(f"an Asian Handicap has a home and an away side, not {selection!r}")

    legs = quarter_legs(line)
    if legs is not None:
        a, b = (asian_handicap(matrix, selection=selection, line=x) for x in legs)
        return LineOutcome((a.win + b.win) / 2, (a.push + b.push) / 2)

    margins = margin_distribution(matrix)
    win = push = 0.0
    for margin, p in margins.items():
        own = margin if side == "home" else -margin
        adjusted = Decimal(own) + line
        if adjusted > 0:
            win += p
        elif adjusted == 0:
            push += p
    return LineOutcome(win, push)


def over_under(
    matrix: NDArray[np.float64], *, selection: str, line: Decimal
) -> LineOutcome:
    """Over or Under total goals, at any line - including whole and quarter ones.

    The model priced 2.5 and only 2.5, which is 934 of 10,240 stored Over/Under
    prices. Every other line is the same sum over the same matrix.
    """
    side = selection.strip().lower()
    if side not in ("over", "under"):
        raise ValueError(f"an Over/Under has an over and an under side, not {selection!r}")

    legs = quarter_legs(line)
    if legs is not None:
        a, b = (over_under(matrix, selection=selection, line=x) for x in legs)
        return LineOutcome((a.win + b.win) / 2, (a.push + b.push) / 2)

    totals = total_distribution(matrix)
    win = push = 0.0
    for goals, p in totals.items():
        diff = Decimal(goals) - line
        if diff == 0:
            push += p
        elif (diff > 0) == (side == "over"):
            win += p
    return LineOutcome(win, push)


def fair_odds(outcome: LineOutcome) -> Decimal | None:
    """The price at which this bet breaks even, pushes included.

    ``(1 - push) / win``. A push returns the stake, so it is not a loss the
    price has to cover - which is exactly why a pushable bet's fair price is
    SHORTER than 1/win, and treating the two as the same would overstate the
    edge on every whole and quarter line we quote.
    """
    if outcome.win <= 0:
        return None
    return Decimal(str((1.0 - outcome.push) / outcome.win))
