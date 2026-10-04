"""Intervals for every line the market quotes, from the goal model's parameter draws.

The seven fixed rows have carried a 90% interval since they were introduced: 200 draws
from the Laplace approximation of the fit, each projected through the score matrix. The
quoted lines (every Asian Handicap, Over/Under and Double Chance line priced) did not -
``fbi.models.quoted`` left them NULL on purpose rather than repeat the point estimate as a
bound. A NULL lower bound then meant those lines could not be ranked by their pessimistic
probability at all (``fbi.picks.daily``), while they were 4 of the first day's 5
evaluation picks.

The arithmetic is the scalar one in ``fbi.models.lines``, done for all draws at once: per
fixture the draws' score matrices are built once, their margin and total distributions
once, and every line is a sum over those - so 70 lines cost about what one did. A test
holds this path equal to the scalar one, quarter lines and pushes included.

What is bounded is the UNCONDITIONAL win probability (what the predictions table stores
for a line; the pick engine conditions on the bet settling).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from fbi.models.goals import INTERVAL_LEVEL, GoalModel
from fbi.models.lines import quarter_legs
from fbi.models.scoring import matrices_batch

Triple = tuple[str, str, Decimal]


@dataclass(frozen=True, slots=True)
class Distributions:
    """Per draw: P(margin = k) for k in -G..G (index k + G), P(total = t) for t in 0..2G."""

    margins: NDArray[np.float64]
    totals: NDArray[np.float64]
    g: int

    @property
    def home(self) -> NDArray[np.float64]:
        return self.margins[:, self.g + 1:].sum(axis=1)

    @property
    def draw(self) -> NDArray[np.float64]:
        return self.margins[:, self.g]

    @property
    def away(self) -> NDArray[np.float64]:
        return self.margins[:, :self.g].sum(axis=1)


def distributions(matrices: NDArray[np.float64]) -> Distributions:
    """Margin and total distributions of a batch of normalised score matrices (n, G+1, G+1)."""
    g = matrices.shape[1] - 1
    margins = np.stack([np.trace(matrices, offset=-k, axis1=1, axis2=2) for k in range(-g, g + 1)], axis=1)
    flipped = np.flip(matrices, axis=2)
    totals = np.stack([np.trace(flipped, offset=g - t, axis1=1, axis2=2) for t in range(2 * g + 1)], axis=1)
    return Distributions(margins, totals, g)


def _ah(d: Distributions, side: str, line: Decimal) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    legs = quarter_legs(line)
    if legs is not None:
        (wa, pa), (wb, pb) = (_ah(d, side, x) for x in legs)
        return (wa + wb) / 2, (pa + pb) / 2
    k = np.arange(-d.g, d.g + 1)
    own = k if side == "home" else -k
    adjusted = own + float(line)
    win = d.margins[:, adjusted > 0].sum(axis=1)
    push = d.margins[:, adjusted == 0].sum(axis=1)
    return win, push


def _ou(d: Distributions, side: str, line: Decimal) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    legs = quarter_legs(line)
    if legs is not None:
        (wa, pa), (wb, pb) = (_ou(d, side, x) for x in legs)
        return (wa + wb) / 2, (pa + pb) / 2
    t = np.arange(2 * d.g + 1)
    diff = t - float(line)
    win = d.totals[:, (diff > 0) if side == "over" else (diff < 0)].sum(axis=1)
    push = d.totals[:, diff == 0].sum(axis=1)
    return win, push


def outcome_batch(d: Distributions, market_key: str, selection: str, line: Decimal
                  ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """(win, push) per draw for one side of one line. Raises ValueError on an unknown selection."""
    side = selection.strip().lower()
    if market_key == "AH":
        if side not in ("home", "away"):
            raise ValueError(f"an Asian Handicap has a home and an away side, not {selection!r}")
        return _ah(d, side, line)
    if market_key == "OU":
        if side not in ("over", "under"):
            raise ValueError(f"an Over/Under has an over and an under side, not {selection!r}")
        return _ou(d, side, line)
    if market_key == "DC":
        sums = {"1X": d.home + d.draw, "X2": d.draw + d.away, "12": d.home + d.away}
        if selection not in sums:
            raise ValueError(f"unknown Double Chance selection {selection!r}")
        return sums[selection], np.zeros_like(d.draw)
    raise ValueError(f"no line arithmetic for market {market_key!r}")


def line_intervals(model: GoalModel, home_id: int, away_id: int, triples: Sequence[Triple], *,
                   neutral: bool = False, draws: int = 200, level: float = INTERVAL_LEVEL
                   ) -> dict[Triple, tuple[float, float]] | None:
    """(lo, hi) of the unconditional win probability per quoted triple, or None when the fit has no
    covariance (an honest "no interval"). A triple that cannot be priced is left out."""
    drawn = model.lambda_draws(home_id, away_id, neutral=neutral, draws=draws)
    if drawn is None:
        return None
    d = distributions(matrices_batch(*drawn))
    q = (1 - level) / 2
    out: dict[Triple, tuple[float, float]] = {}
    for triple in triples:
        try:
            win, _ = outcome_batch(d, *triple)
        except ValueError:
            continue
        out[triple] = (float(np.quantile(win, q)), float(np.quantile(win, 1 - q)))
    return out
