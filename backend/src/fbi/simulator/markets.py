"""Every result and goals market of a match, by summation over its one joint distribution (``joint.JointScore``).

A SELECTION is settled cell by cell: at every (home_1H, away_1H, home_2H, away_2H) the stake is won, returned or lost, in fractions
``win`` and ``push`` of 0, 1/2 or 1 (the halves only for quarter lines). Its probability is the expectation of those fractions under the
joint, so every market of a match comes from the same numbers and they are coherent by construction (the 1X2 adds up to one, the double
chance is its sums, a handicap at 0 is draw-no-bet, BTTS implies over 1.5 ...).

MARKETS (``Selection.market``; ``period`` is FT, 1H or 2H unless said otherwise):

    1X2 ....... Home / Draw / Away
    DC ........ 1X / X2 / 12
    DNB ....... Home / Away; a draw returns the stake
    AH ........ Asian handicap, Home / Away; ``line`` is the handicap that applies to the SELECTION (the convention of
                ``fbi.models.lines`` and of the stored prices): the bet is on own margin + line, > 0 wins, = 0 returns the stake
    EH ........ European (three-way) handicap, Home / Draw / Away; ``line`` is a whole number applied to the HOME side: the result of
                home goals + line against away goals
    OU ........ Over / Under total goals at ``line``
    TT_HOME, TT_AWAY  Over / Under the goals of one side at ``line`` (team totals)
    BTTS ...... Yes / No
    CS ........ the correct score, pick ``"h-a"`` (``"2-1"``)
    HTFT ...... half-time / full-time, pick ``"1/X"`` (or ``"Home/Draw"``); full time only

LINES. Any multiple of 0.25. A whole line can return the stake; a QUARTER line (x.25, x.75) is half the stake on each neighbouring line
(-0.25 is half at 0 and half at -0.5), so it can win or lose half: its ``(win, push)`` are the averages of the two legs, which
reproduces the split bet's expected value exactly (``fbi.models.lines``, same convention).

CORRELATION. For two selections of the same match ``pair`` gives P(a), P(b), P(both win) and the EXCESS, P(both) - P(a) P(b): the
covariance of the two win indicators, zero for independent bets, positive when they tend to win together. With quarter lines the
"indicator" is the fraction of the stake won (0, 1/2, 1), and the excess is that fraction's covariance. ``return_covariance`` gives the
covariance of the two bets' returns per unit staked at given prices, pushes included: what a portfolio needs. ``Correlations`` caches
the settlements so that a matrix over many selections costs one pass each.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from numpy.typing import NDArray

from fbi.models.lines import LineOutcome
from fbi.simulator.joint import JointScore

PERIODS: Final = ("FT", "1H", "2H")
MARKETS: Final = frozenset({"1X2", "DC", "DNB", "AH", "EH", "OU", "TT_HOME", "TT_AWAY", "BTTS", "CS", "HTFT"})
_SIGN: Final = {"1": 1, "X": 0, "2": -1, "Home": 1, "Draw": 0, "Away": -1}

Grid = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Selection:
    """One outcome of one market of the match."""

    market: str
    pick: str
    line: float = 0.0
    period: str = "FT"

    def __post_init__(self) -> None:
        if self.market not in MARKETS:
            raise ValueError(f"unknown market {self.market!r}; known: {sorted(MARKETS)}")
        if self.period not in PERIODS:
            raise ValueError(f"a period is FT, 1H or 2H, not {self.period!r}")
        if self.market == "HTFT" and self.period != "FT":
            raise ValueError("HT/FT is a full-time market")
        quarters = self.line * 4
        if not math.isfinite(quarters) or quarters != round(quarters):
            raise ValueError(f"a line is a multiple of 0.25, not {self.line!r}")

    @property
    def key(self) -> str:
        line = "" if self.line == 0 and self.market not in ("AH", "OU", "TT_HOME", "TT_AWAY") else f"@{self.line:g}"
        return f"{self.market}:{self.period}:{self.pick}{line}"


@dataclass(frozen=True, slots=True)
class PairStat:
    """Two selections of one match: their probabilities, the joint one and the excess P(both) - P(a) P(b)."""

    p_a: float
    p_b: float
    p_both: float
    excess: float
    correlation: float | None
    """Pearson correlation of the two win fractions; None when one of them is certain (no variance)."""


def is_quarter(line: float) -> bool:
    return round(line * 4) % 2 == 1


def _legs(line: float) -> tuple[float, ...]:
    return (line - 0.25, line + 0.25) if is_quarter(line) else (line,)


def _line_bet(value: NDArray[np.int64], line: float, joint: JointScore) -> tuple[Grid, Grid]:
    """A bet on ``value + line``: > 0 wins, = 0 returns the stake, < 0 loses; quarter lines as two half stakes."""
    shape = joint.p.shape
    win = np.zeros(shape)
    push = np.zeros(shape)
    legs = _legs(line)
    for leg in legs:
        adjusted = value + leg
        win += np.broadcast_to(adjusted > 0, shape)
        push += np.broadcast_to(adjusted == 0, shape)
    return win / len(legs), push / len(legs)


def _event(mask: NDArray[np.bool_], joint: JointScore) -> tuple[Grid, Grid]:
    shape = joint.p.shape
    return np.broadcast_to(mask, shape).astype(np.float64), np.zeros(shape)


def _sign(text: str, market: str) -> int:
    if text not in _SIGN:
        raise ValueError(f"{market} has Home/Draw/Away (or 1/X/2), not {text!r}")
    return _SIGN[text]


def settle(joint: JointScore, sel: Selection) -> tuple[Grid, Grid]:
    """``(win, push)``: the fraction of the stake won and returned at every cell of the joint."""
    home, away = joint.goals(sel.period)
    margin = home - away
    m, pick = sel.market, sel.pick
    if m == "1X2":
        return _event(np.sign(margin) == _sign(pick, m), joint)
    if m == "DC":
        if pick not in ("1X", "X2", "12"):
            raise ValueError(f"DC has 1X, X2 and 12, not {pick!r}")
        a, b = (_sign(c, m) for c in pick)
        s = np.sign(margin)
        return _event((s == a) | (s == b), joint)
    if m == "DNB":
        if pick not in ("Home", "Away"):
            raise ValueError(f"DNB has Home and Away, not {pick!r}")
        return _line_bet(margin if pick == "Home" else -margin, 0.0, joint)
    if m == "AH":
        if pick not in ("Home", "Away"):
            raise ValueError(f"AH has Home and Away, not {pick!r}")
        return _line_bet(margin if pick == "Home" else -margin, sel.line, joint)
    if m == "EH":
        if sel.line != round(sel.line):
            raise ValueError(f"a European handicap is a whole number of goals, not {sel.line!r}")
        return _event(np.sign(margin + int(sel.line)) == _sign(pick, m), joint)
    if m in ("OU", "TT_HOME", "TT_AWAY"):
        count = home + away if m == "OU" else (home if m == "TT_HOME" else away)
        if pick == "Over":
            return _line_bet(count, -sel.line, joint)
        if pick == "Under":
            return _line_bet(-count, sel.line, joint)
        raise ValueError(f"{m} has Over and Under, not {pick!r}")
    if m == "BTTS":
        both = (home > 0) & (away > 0)
        if pick not in ("Yes", "No"):
            raise ValueError(f"BTTS has Yes and No, not {pick!r}")
        return _event(both if pick == "Yes" else ~both, joint)
    if m == "CS":
        try:
            h, a = (int(x) for x in pick.split("-"))
        except ValueError as exc:
            raise ValueError(f"a correct score is 'h-a', not {pick!r}") from exc
        return _event((home == h) & (away == a), joint)
    # HTFT
    parts = pick.split("/")
    if len(parts) != 2:
        raise ValueError(f"HT/FT is 'ht/ft' (1/X, Home/Draw), not {pick!r}")
    h1, a1 = joint.goals("1H")
    ht, ft = (_sign(x, m) for x in parts)
    return _event((np.sign(h1 - a1) == ht) & (np.sign(margin) == ft), joint)


def price(joint: JointScore, sel: Selection) -> LineOutcome:
    """P(win) and P(push) of one selection."""
    win, push = settle(joint, sel)
    return LineOutcome(joint.expectation(win), joint.expectation(push))


def probability(joint: JointScore, sel: Selection) -> float:
    """P(win) of one selection (with a quarter line: the expected fraction of the stake won)."""
    return price(joint, sel).win


@dataclass
class Correlations:
    """The correlation provider over one match: settlements cached per selection."""

    joint: JointScore
    _cache: dict[Selection, tuple[Grid, Grid]] = field(default_factory=dict)

    def _settled(self, sel: Selection) -> tuple[Grid, Grid]:
        if sel not in self._cache:
            self._cache[sel] = settle(self.joint, sel)
        return self._cache[sel]

    def price(self, sel: Selection) -> LineOutcome:
        win, push = self._settled(sel)
        return LineOutcome(self.joint.expectation(win), self.joint.expectation(push))

    def pair(self, a: Selection, b: Selection) -> PairStat:
        wa, _ = self._settled(a)
        wb, _ = self._settled(b)
        e = self.joint.expectation
        pa, pb, both = e(wa), e(wb), e(wa * wb)
        excess = both - pa * pb
        va, vb = e(wa * wa) - pa * pa, e(wb * wb) - pb * pb
        corr = excess / math.sqrt(va * vb) if va > 1e-15 and vb > 1e-15 else None
        return PairStat(pa, pb, both, excess, corr)

    def excess(self, a: Selection, b: Selection) -> float:
        return self.pair(a, b).excess

    def return_covariance(self, a: Selection, odds_a: float, b: Selection, odds_b: float) -> float:
        """Cov of the two returns per unit staked, R = win * odds + push - 1, pushes and half results included."""
        wa, ua = self._settled(a)
        wb, ub = self._settled(b)
        ra, rb = wa * odds_a + ua - 1.0, wb * odds_b + ub - 1.0
        e = self.joint.expectation
        return e(ra * rb) - e(ra) * e(rb)

    def matrix(self, selections: Sequence[Selection]) -> NDArray[np.float64]:
        """The excess matrix over ``selections`` (diagonal: P(1 - P) for a binary bet)."""
        n = len(selections)
        out = np.zeros((n, n))
        for i in range(n):
            for j in range(i, n):
                out[i, j] = out[j, i] = self.pair(selections[i], selections[j]).excess
        return out


def pair(joint: JointScore, a: Selection, b: Selection) -> PairStat:
    return Correlations(joint).pair(a, b)


# -- the standard menu: every market, with stable keys -------------------------------------------------------------------------------------

FT_TOTAL_LINES: Final = (0.5, 1.5, 2.5, 3.5, 4.5)
HALF_TOTAL_LINES: Final = (0.5, 1.5, 2.5)
TEAM_LINES: Final = (0.5, 1.5, 2.5)
AH_LINES: Final = (-2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
EH_LINES: Final = (-2.0, -1.0, 1.0, 2.0)
CS_MAX: Final = 5
"""Correct scores listed up to 5-5 in the menu; the rest of the mass is ``cs_ft_other``."""


def groups(period: str = "FT") -> dict[str, tuple[Selection, ...]]:
    """The mutually exclusive, exhaustive sets of selections of a period (each adds up to one): the test of coherence."""
    out: dict[str, tuple[Selection, ...]] = {
        "1X2": tuple(Selection("1X2", s, 0.0, period) for s in ("Home", "Draw", "Away")),
        "BTTS": (Selection("BTTS", "Yes", 0.0, period), Selection("BTTS", "No", 0.0, period)),
    }
    for line in (FT_TOTAL_LINES if period == "FT" else HALF_TOTAL_LINES):
        out[f"OU@{line:g}"] = (Selection("OU", "Over", line, period), Selection("OU", "Under", line, period))
    for line in EH_LINES:
        out[f"EH@{line:g}"] = tuple(Selection("EH", s, line, period) for s in ("Home", "Draw", "Away"))
    if period == "FT":
        out["HTFT"] = tuple(Selection("HTFT", f"{a}/{b}") for a in "1X2" for b in "1X2")
    return out


def menu(joint: JointScore, selections: Iterable[Selection] | None = None) -> dict[str, dict[str, float]]:
    """``{selection key: {"win": p, "push": p}}`` for the standard menu (or for ``selections``)."""
    if selections is None:
        chosen: list[Selection] = []
        for period in PERIODS:
            for group in groups(period).values():
                chosen.extend(group)
            chosen += [Selection("DC", s, 0.0, period) for s in ("1X", "X2", "12")]
            chosen += [Selection("DNB", s, 0.0, period) for s in ("Home", "Away")]
            for side in ("TT_HOME", "TT_AWAY"):
                chosen += [Selection(side, s, ln, period) for ln in TEAM_LINES for s in ("Over", "Under")]
            chosen += [Selection("AH", s, ln if s == "Home" else -ln, period) for ln in AH_LINES for s in ("Home", "Away")]
        chosen += [Selection("CS", f"{h}-{a}") for h in range(CS_MAX + 1) for a in range(CS_MAX + 1)]
        selections = chosen
    c = Correlations(joint)
    out: dict[str, dict[str, float]] = {}
    for sel in selections:
        lo = c.price(sel)
        out[sel.key] = {"win": lo.win, "push": lo.push}
    if any(k.startswith("CS:FT:") for k in out):
        listed = sum(v["win"] for k, v in out.items() if k.startswith("CS:FT:"))
        out["CS:FT:other"] = {"win": max(0.0, 1.0 - listed), "push": 0.0}
    return out
