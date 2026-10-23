"""The probabilities of a family, laid out as the markets the provider prices (plan F10): a key of the catalogue, a line, and the outcomes
in the words the price tables use.

A forecast of a market is one probability per OUTCOME, all of them at one instant and adding up to one (the forecast table of F5). The
families know distributions; this module turns them into those sets:

    key          the market key of the catalogue (``fbi.market.catalogue``: ``OU_1H``, ``1X2_2H``, ``HTFT``, ``CORNERS_OU``, ``CARDS_OU_HOME`` ...)
    line         the line of the market (0 when the market has none), half lines only: a whole or a quarter line is a stake on the neighbours
    outcomes     (selection, probability) in the vocabulary of ``market.odds_quotes`` (``fbi.odds.quote_parse``): Home/Draw/Away, Over/Under,
                 Yes/No, 1X/12/X2, and the provider's own text for HT/FT ("Home/Draw") and the highest scoring half ("1st Half")

Only the markets that the catalogue knows are produced (``available``): a family never invents a key. Odd/even and the Asian handicap of a half
are left out on purpose: the first has no informational value (plan, matrix of markets) and the second stores a handicap per outcome that
the forecast table has no column for yet.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from fbi.families import derive, halves
from fbi.families.counts import normalised
from fbi.families.fit import Prediction

CLIP: Final = 1e-6
"""A stated probability is never 0 or 1: the table refuses them and no distribution here is that sure."""

WORDS: Final = {"1": "Home", "X": "Draw", "2": "Away"}
HALF_WORDS: Final = {"first": "1st Half", "tie": "Draw", "second": "2nd Half"}


@dataclass(frozen=True, slots=True)
class MarketProbs:
    """One market of one match: its key, its line and the probability of each outcome (adding up to 1)."""

    market_key: str
    line: float
    outcomes: tuple[tuple[str, float], ...]

    @property
    def total(self) -> float:
        return sum(p for _, p in self.outcomes)


def _set(key: str, line: float, outcomes: Sequence[tuple[str, float]]) -> MarketProbs:
    """The outcomes clipped away from 0 and 1 and scaled to add up to one, so what is stored is a coherent set."""
    clipped = [(s, min(max(p, CLIP), 1.0 - CLIP)) for s, p in outcomes]
    total = sum(p for _, p in clipped)
    return MarketProbs(key, line, tuple((s, p / total) for s, p in clipped))


def _over_under(key: str, line: float, pmf: NDArray[np.float64]) -> MarketProbs:
    r = derive.count_line(pmf, line)
    return _set(key, line, (("Over", r.over), ("Under", r.under)))


def _three_way(key: str, pred: Prediction) -> MarketProbs:
    home, draw, away = derive.result(pred)
    return _set(key, 0.0, (("Home", home), ("Draw", draw), ("Away", away)))


def _double_chance(key: str, pred: Prediction) -> MarketProbs:
    home_or_draw, draw_or_away, home_or_away = derive.double_chance(pred)
    return _set(key, 0.0, (("1X", home_or_draw), ("12", home_or_away), ("X2", draw_or_away)))


def count_markets(pred: Prediction, *, prefix: str, total_lines: Sequence[float], side_lines: Sequence[float],
                  available: Collection[str]) -> list[MarketProbs]:
    """The markets around ONE count of the match (corners, cards, yellow cards...): the total, each side's own count, who has more and
    double chance. ``prefix`` is the family of the key (``CORNERS``, ``CARDS``, ``YELLOW``, ``RED``)."""
    out: list[MarketProbs] = []
    if f"{prefix}_OU" in available:
        out += [_over_under(f"{prefix}_OU", ln, pred.pmf_total) for ln in total_lines]
    for side, pmf in (("HOME", pred.pmf_home), ("AWAY", pred.pmf_away)):
        if f"{prefix}_OU_{side}" in available:
            out += [_over_under(f"{prefix}_OU_{side}", ln, pmf) for ln in side_lines]
    if f"{prefix}_1X2" in available:
        out.append(_three_way(f"{prefix}_1X2", pred))
    if f"{prefix}_DC" in available:
        out.append(_double_chance(f"{prefix}_DC", pred))
    return out


def half_markets(pred: Prediction, *, period: str, total_lines: Sequence[float], side_lines: Sequence[float],
                 available: Collection[str]) -> list[MarketProbs]:
    """The markets of ONE half (``period`` is ``1H`` or ``2H``): the total, each side's goals, the result, draw no bet, double chance and
    both teams to score."""
    out: list[MarketProbs] = []
    if f"OU_{period}" in available:
        out += [_over_under(f"OU_{period}", ln, pred.pmf_total) for ln in total_lines]
    for side, pmf in (("HOME", pred.pmf_home), ("AWAY", pred.pmf_away)):
        if f"OU_{side}_{period}" in available:
            out += [_over_under(f"OU_{side}_{period}", ln, pmf) for ln in side_lines]
    if f"1X2_{period}" in available:
        out.append(_three_way(f"1X2_{period}", pred))
    if f"DNB_{period}" in available:
        home, away = derive.draw_no_bet(pred)
        out.append(_set(f"DNB_{period}", 0.0, (("Home", home), ("Away", away))))
    if f"DC_{period}" in available:
        out.append(_double_chance(f"DC_{period}", pred))
    if f"BTTS_{period}" in available:
        yes = derive.both_score(pred)
        out.append(_set(f"BTTS_{period}", 0.0, (("Yes", yes), ("No", 1.0 - yes))))
    return out


def across_halves_markets(first: Prediction, second: Prediction, *, available: Collection[str]) -> list[MarketProbs]:
    """What needs both halves: HT/FT (nine outcomes) and the highest scoring half (of the match and of each side)."""
    out: list[MarketProbs] = []
    if "HTFT" in available:
        cells = halves.half_time_full_time(first, second)
        out.append(_set("HTFT", 0.0, tuple((f"{WORDS[label[0]]}/{WORDS[label[2]]}", p) for label, p in cells.items())))
    for key, f, s in (("HSH", first.pmf_total, second.pmf_total), ("HSH_HOME", first.pmf_home, second.pmf_home),
                      ("HSH_AWAY", first.pmf_away, second.pmf_away)):
        if key in available:
            before, tie, after = halves.highest_scoring_half(normalised(f), normalised(s))
            out.append(_set(key, 0.0, ((HALF_WORDS["first"], before), (HALF_WORDS["tie"], tie), (HALF_WORDS["second"], after))))
    return out


GOALS_TOTAL_LINES: Final = (0.5, 1.5, 2.5)
GOALS_SIDE_LINES_1H: Final = (0.5,)
GOALS_SIDE_LINES_2H: Final = (0.5, 1.5)


def goals_by_half_markets(first: Prediction, second: Prediction, *, available: Collection[str]) -> list[MarketProbs]:
    """Every market of the goals of the halves that the catalogue has a key for."""
    return [
        *half_markets(first, period="1H", total_lines=GOALS_TOTAL_LINES, side_lines=GOALS_SIDE_LINES_1H, available=available),
        *half_markets(second, period="2H", total_lines=(*GOALS_TOTAL_LINES, 3.5), side_lines=GOALS_SIDE_LINES_2H, available=available),
        *across_halves_markets(first, second, available=available),
    ]
