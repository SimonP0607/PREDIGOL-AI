"""The bets on ONE count, derived from its distribution (plan F10): the total, a side's own count, who has more, the handicap.

Whatever the count is - the goals of a half, the corners of the match, the cards - the provider prices the same few shapes around it, and each
is a function of the two distributions (home count, away count; ``fit.Prediction`` holds them and the distribution of their total):

    over/under ....... the total of the match, or the count of one side (``count_line`` on ``pmf_total`` / ``pmf_home`` / ``pmf_away``)
    who has more ..... the "1X2" of the count (``result``), draw no bet, double chance
    handicap ......... the home side with a number of units added against the away side (``asian_handicap``)
    both / odd-even .. both sides at least once (``both_score``), an odd total (``odd_total``)

The two sides are taken as independent given the strengths of the teams: the statement of the assumption for goals is in ``halves``; for corners
and cards it is measured the same way on the matches before any of these bets is ever priced.

A QUARTER LINE (x.25, x.75) is two half-stakes on the neighbouring lines. The ``Line`` it returns is the stake-weighted one: ``over`` is the
share of the stake that wins, ``push`` the share returned, ``under`` the share that loses, so a half-win counts as half a win and half a push.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from fbi.families.counts import Line, difference_probs, handicap_probs, normalised, over_under
from fbi.families.fit import Prediction


def split_line(line: float) -> tuple[tuple[float, float], ...]:
    """The (line, share of the stake) pairs a line is made of: one for a whole or half line, two for a quarter line."""
    twice = line * 2.0
    if float(twice).is_integer():
        return ((line, 1.0),)
    lo = math.floor(twice) / 2.0
    return ((lo, 0.5), (lo + 0.5, 0.5))


def _weighted(parts: Sequence[tuple[Line, float]]) -> Line:
    over = sum(w * p.over for p, w in parts)
    push = sum(w * p.push for p, w in parts)
    under = sum(w * p.under for p, w in parts)
    return Line(over, push, max(0.0, under))


def count_line(pmf: NDArray[np.float64], line: float) -> Line:
    """Over/Under ``line`` on a count (the total of a half, or the goals of one side in it); quarter lines are split."""
    return _weighted([(over_under(pmf, ln), w) for ln, w in split_line(line)])


def asian_handicap(pred: Prediction, line: float) -> Line:
    """The home side with ``line`` goals added against the away side, over one half: ``over`` is the home side's share, ``under`` the away's."""
    home, away = normalised(pred.pmf_home), normalised(pred.pmf_away)
    return _weighted([(handicap_probs(home, away, ln), w) for ln, w in split_line(line)])


def result(pred: Prediction) -> tuple[float, float, float]:
    """P(home leads), P(level), P(away leads) at the end of the half."""
    return difference_probs(pred.pmf_home, pred.pmf_away)


def draw_no_bet(pred: Prediction) -> tuple[float, float]:
    """The result of the half with the draw returned: P(home | not level), P(away | not level)."""
    home, _, away = result(pred)
    decided = home + away
    if decided <= 0.0:
        raise ValueError("a half that cannot be decided")
    return home / decided, away / decided


def double_chance(pred: Prediction) -> tuple[float, float, float]:
    """Home or level (1X), level or away (X2), home or away (12)."""
    home, level, away = result(pred)
    return home + level, level + away, home + away


def both_score(pred: Prediction) -> float:
    """P(both sides score in the half): independent sides, so the product of the two chances of scoring at least once."""
    return (1.0 - float(normalised(pred.pmf_home)[0])) * (1.0 - float(normalised(pred.pmf_away)[0]))


def odd_total(pred: Prediction) -> float:
    """P(an odd number of goals in the half)."""
    pmf = normalised(pred.pmf_total)
    return float(pmf[1::2].sum())
