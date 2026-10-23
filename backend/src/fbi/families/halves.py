"""The bets on the goals of a half, derived from two fitted halves (plan F10).

A match is two halves. The first half and the second half each get their own fit (``fit.fit_family`` on ``goals_1h`` and on ``goals_2h``: a
second half has more goals than a first, and a different home effect, so one fit cannot stand for both). Everything the provider prices
around the halves is a function of the two predictions:

    one half .... the total of the half, the goals of a side in the half, the result of the half, draw no bet, double chance, both teams
                  score, odd/even, the Asian handicap of the half
    two halves .. HT/FT, the highest scoring half (of the match and of each side), and the full-time distribution IF the halves are added up

THE ASSUMPTION, STATED. Given the strengths of the two teams, the goals of the first half and the goals of the second are taken as
independent, and so are the two sides within a half (a Poisson or negative-binomial count each). A match that is 2-0 at half-time is played
differently afterwards, so the real halves are not independent; how far this matters is measured on the matches (``evaluate_halves``), and
the derived bets stay RESEARCH until that measure and the price history (F1) say otherwise. Nothing here knows a clock or a database.

"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

from fbi.families.counts import convolve, normalised
from fbi.families.derive import both_score, count_line, odd_total, result
from fbi.families.fit import Prediction

SIGNS: Final = ("1", "X", "2")
"""Home leads, level, away leads: the three outcomes of a half and of a full time, in the order a ``HT/FT`` label is written ("1/X")."""
HTFT_LABELS: Final = tuple(f"{ht}/{ft}" for ht in SIGNS for ft in SIGNS)


def goal_difference(home: NDArray[np.float64], away: NDArray[np.float64]) -> tuple[NDArray[np.float64], int]:
    """The distribution of home minus away for two independent counts: ``(pmf, offset)``, where ``pmf[i]`` is P(difference = i - offset)."""
    h, a = normalised(home), normalised(away)
    return np.asarray(np.convolve(h, a[::-1]), dtype=np.float64), a.size - 1


def half_time_full_time(first: Prediction, second: Prediction) -> dict[str, float]:
    """P(the half-time result and the full-time result are ``ht/ft``) for the nine labels of ``HTFT_LABELS``; they add up to 1.

    The score at full time is the score at half-time plus the goals of the second half, so the full-time difference is the sum of the
    differences of the two halves; with the halves independent the nine cells are read from the outer product of the two distributions.
    """
    d1, o1 = goal_difference(first.pmf_home, first.pmf_away)
    d2, o2 = goal_difference(second.pmf_home, second.pmf_away)
    diff1 = np.arange(d1.size) - o1
    diff2 = np.arange(d2.size) - o2
    joint = np.outer(d1, d2)
    total = diff1[:, None] + diff2[None, :]
    # np.sign gives +1 (home leads), 0, -1; SIGNS is written home-first: 1, X, 2
    code = {1: "1", 0: "X", -1: "2"}
    out = dict.fromkeys(HTFT_LABELS, 0.0)
    for s_value, s_label in code.items():
        rows = np.sign(diff1) == s_value
        for t_value, t_label in code.items():
            out[f"{s_label}/{t_label}"] = float(joint[rows[:, None] & (np.sign(total) == t_value)].sum())
    mass = sum(out.values())
    return {k: v / mass for k, v in out.items()}


def highest_scoring_half(first: NDArray[np.float64], second: NDArray[np.float64]) -> tuple[float, float, float]:
    """P(more in the first half), P(the same), P(more in the second half) for two independent counts: the total of the match, or one side."""
    f, s = normalised(first), normalised(second)
    joint = np.outer(f, s)
    return float(np.tril(joint, -1).sum()), float(np.trace(joint)), float(np.triu(joint, 1).sum())


def full_time(first: Prediction, second: Prediction) -> Prediction:
    """The full-time distributions IF the two halves are added up (the means add; the counts of independent halves convolve)."""
    return Prediction(
        first.mean_home + second.mean_home,
        first.mean_away + second.mean_away,
        normalised(convolve(normalised(first.pmf_home), normalised(second.pmf_home))),
        normalised(convolve(normalised(first.pmf_away), normalised(second.pmf_away))),
        normalised(convolve(normalised(first.pmf_total), normalised(second.pmf_total))),
    )


TOTAL_LINES: Final = (0.5, 1.5, 2.5)
"""The lines of the totals of a half that the standard menu prices (a half rarely has more than two goals)."""


def menu(first: Prediction, second: Prediction) -> dict[str, float]:
    """The standard menu of derived probabilities, flat and with stable keys (this is what is graded and, later, stored).

    ``ht_1/x/2`` the result of the first half; ``h2_1/x/2`` of the second; ``btts_1h/2h``; ``ou_1h_<line>`` and ``ou_2h_<line>`` the
    probability of OVER; ``odd_1h/2h``; ``best_first/tie/second`` the highest scoring half; ``htft_1_x`` the nine HT/FT cells.
    """
    out: dict[str, float] = {}
    for tag, pred in (("ht", first), ("h2", second)):
        for label, p in zip(SIGNS, result(pred), strict=True):
            out[f"{tag}_{label.lower()}"] = p
    out["btts_1h"], out["btts_2h"] = both_score(first), both_score(second)
    for tag, pred in (("1h", first), ("2h", second)):
        for line in TOTAL_LINES:
            out[f"ou_{tag}_{line}"] = count_line(pred.pmf_total, line).over
        out[f"odd_{tag}"] = odd_total(pred)
    out["best_first"], out["best_tie"], out["best_second"] = highest_scoring_half(first.pmf_total, second.pmf_total)
    for label, p in half_time_full_time(first, second).items():
        out["htft_" + label.lower().replace("/", "_")] = p
    return out
