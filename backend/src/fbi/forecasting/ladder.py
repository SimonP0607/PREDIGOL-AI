"""The coherent ladder: the figures of one market along its lines made to say one thing (plan RP-2.2, ``ladder-projection-v1``). Pure.

WHY. Every line of a goals market is calibrated on its own, so the same event can come out with two figures: «more than 1.0 goals» at 0.627 beside
«more than 1.5» at 0.738, which cannot both be true (the first includes the second). The battery of coherence (``fbi.forecasting.battery``, tests 3
and 7) counts those cases; this module says what the figures would be if the ladder were ONE distribution, and by how much each one would move. It
changes nothing by itself: the caller decides what to do with the answer (a measurement first, ``scripts/ia_ladder_projection.py``; a published
figure only after the protocol ``LAD-P1`` passes).

THE IDEA. A market's lines are all questions about one count (the goals of a side or the total; the goal difference for a handicap). Only the HALF LINES
(0.5, 1.5, ...) are free: ``v(h)`` is the chance that the count passes ``h``, and it can only go down as the line goes up (for a handicap, up as the
handicap grows). Every other line follows from them, with no figure of its own to disagree with:

    whole line L    win = v(L + 1/2), push = v(L - 1/2) - v(L + 1/2)       (the count lands exactly on the line; the handicap reads the other way)
    quarter line    the average of its two neighbours (what test 7 asks the stored figure to be)
    the other side  its complement (Under is what Over leaves; a handicap's two sides sit at opposite lines)

TWO WAYS TO READ THE LADDER, both stated before any outcome is looked at (the protocol compares them with the figures as they are):

    ``half``    only the half-line figures count; the whole and quarter lines are read off them (the simplest rule)
    ``pooled``  every stored figure says something about the half lines (a whole line gives two of them, a quarter line one): the ladder is the
                average of everything it was told, then made monotone

THE PROJECTION. The half-line values are replaced by the closest non-increasing (non-decreasing) sequence in the least-squares sense: pool adjacent
violators. It is the smallest change that removes the violation, it leaves a ladder that is already coherent exactly as it is, and it keeps the weighted
mean of the ladder. Figures that the 1X2 pins down (a handicap of -0.5 is the home win, +0.5 is home plus draw: test 4) are anchors and do not move. No
probability is scaled, shrunk or re-fitted.

WHAT IT DOES NOT DO. It does not touch a market with fewer than two half lines told, nor a line whose neighbours are missing (it keeps its figure and is
counted as ``kept``: the battery still sees it), nor the relations between markets (tests 5 and 6: a total against its teams, a half against the
match), nor the 1X2 itself. The interval of a figure that left it is stretched to hold it, never the figure moved to fit the interval.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from fbi.forecasting.battery import STEP, ZERO, Figure, Key

VERSION: Final = "ladder-projection-v1"
Mode = Literal["half", "pooled"]
MODES: Final[tuple[Mode, ...]] = ("half", "pooled")

TOTALS: Final = ("OU", "OU_HOME", "OU_AWAY", "OU_1H", "OU_2H")
"""The markets whose lines are thresholds of one count: «over L» is the chance the count passes L."""
HANDICAP: Final = "AH"
ANCHOR_WEIGHT: Final = 1_000_000.0
"""A figure the 1X2 pins down weighs this much more than any other, so the projection leaves it where it is."""
HALF: Final = Decimal("0.5")
NOISE: Final = 2e-6
"""The stored figures carry six decimals: a market whose figures all are within this of what the ladder gives is already coherent and is not touched."""


def is_half(line: Decimal) -> bool:
    return abs(line * 2) % 2 == 1


def is_whole(line: Decimal) -> bool:
    return line % 1 == 0


def is_quarter_line(line: Decimal) -> bool:
    return abs(line * 4) % 2 == 1


def pava(values: Sequence[float], weights: Sequence[float], *, increasing: bool) -> list[float]:
    """Weighted least-squares isotonic regression by pool adjacent violators. ``increasing`` says which way the answer may go."""
    sign = 1.0 if increasing else -1.0
    blocks: list[list[float]] = []  # [mean, weight, count]
    for v, w in zip(values, weights, strict=True):
        blocks.append([sign * v, w, 1.0])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, w2, c2 = blocks.pop()
            m1, w1, c1 = blocks.pop()
            blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    out: list[float] = []
    for mean, _, count in blocks:
        out.extend([sign * mean] * int(count))
    return out


@dataclass(frozen=True, slots=True)
class Move:
    """What the projection did to one figure."""

    key: Key
    before: float
    after: float
    kind: str
    """``half``: a half line moved by the isotonic fit; ``derived``: a whole or quarter line read off the ladder; ``kept``: no ladder to read it off."""

    @property
    def shift(self) -> float:
        return self.after - self.before


@dataclass(frozen=True, slots=True)
class Projection:
    figures: tuple[Figure, ...]
    moves: tuple[Move, ...]

    def moved(self, tol: float = NOISE) -> int:
        return sum(1 for m in self.moves if abs(m.shift) > tol)


# ── one perspective: «over» for a total, «home» for a handicap ───────────────────────────────────────────────────────────────────────────────


def _canonical(f: Figure) -> tuple[Decimal, float, float]:
    """(line, win, push) of the figure seen as Over / Home: Under is what Over leaves, and a handicap's Away at a line is Home at the opposite one."""
    if f.selection in ("Over", "Home"):
        return f.line, f.win, f.push
    return (-f.line if f.market == HANDICAP else f.line), f.lose, f.push


def _estimates(
    rising: bool, line: Decimal, win: float, push: float, *, pooled: bool
) -> list[tuple[Decimal, float]]:
    """What one stored figure (Over/Home form) says about the half-line values ``v``: pairs (half line, value). Only the half lines say it directly with
    ``half``; with ``pooled`` a whole line gives two of them and a quarter line one (the one its two neighbours agree on)."""
    if is_half(line):
        return [(line, win)]
    if not pooled:
        return []
    if is_whole(line):
        return (
            [(line - HALF, win), (line + HALF, win + push)]
            if rising
            else [(line + HALF, win), (line - HALF, win + push)]
        )
    below, above = line - STEP, line + STEP
    if rising:  # the handicap grows with the line
        return [(above, win + push)] if is_whole(below) else [(below, win)]
    return [(below + HALF, win)] if is_whole(below) else [(below, win + push)]


def _ladder(
    figures: Mapping[Key, Figure], market: str, anchors: Mapping[Decimal, float], *, pooled: bool
) -> dict[Decimal, float] | None:
    """The projected half-line values of one market (the chance that the count passes each half line), or None when fewer than two have been told."""
    rising = market == HANDICAP
    told: dict[Decimal, list[float]] = defaultdict(list)
    for (m, _, _), f in figures.items():
        if m != market:
            continue
        line, win, push = _canonical(f)
        for node, value in _estimates(rising, line, win, push, pooled=pooled):
            told[node].append(value)
    if len(told) < 2:
        return None
    nodes = sorted(told)
    values, weights = [], []
    for n in nodes:
        if rising and n in anchors:
            values.append(anchors[n])
            weights.append(ANCHOR_WEIGHT)
        else:
            values.append(sum(told[n]) / len(told[n]))
            weights.append(float(len(told[n])))
    return dict(zip(nodes, pava(values, weights, increasing=rising), strict=True))


def _anchors(figures: Mapping[Key, Figure]) -> dict[Decimal, float]:
    """The handicap lines the 1X2 pins down: -0.5 is the home win and +0.5 is home plus draw (test 4). Empty when the 1X2 is not there."""
    home, draw = figures.get(("1X2", "Home", ZERO)), figures.get(("1X2", "Draw", ZERO))
    out: dict[Decimal, float] = {}
    if home is not None:
        out[-HALF] = home.win
        if draw is not None:
            out[HALF] = home.win + draw.win
    return out


def _read(rising: bool, line: Decimal, v: Mapping[Decimal, float]) -> tuple[float, float] | None:
    """(win, push) of a half or whole line, seen as Over / Home, read off the ladder; None when a half line it needs is not there."""
    if is_half(line):
        return (v[line], 0.0) if line in v else None
    lo, hi = v.get(line - HALF), v.get(line + HALF)
    if lo is None or hi is None:
        return None
    return (lo, hi - lo) if rising else (hi, lo - hi)


def _back(f: Figure, win: float, push: float) -> Figure:
    """The figure, given its Over / Home reading, in its own selection; to twelve decimals, so that two figures that are the same number are exactly
    equal and a strict test does not see rounding as a violation; the interval stretches to hold the new figure (it is what the model measured)."""
    own = win if f.selection in ("Over", "Home") else 1.0 - win - push
    own, push = round(own, 12), round(push, 12)
    lo = f.lo if f.lo is None or f.lo <= own else own
    hi = f.hi if f.hi is None or f.hi >= own else own
    return Figure(f.market, f.selection, f.line, own, push, lo, hi)


def project(figures: Iterable[Figure], *, mode: Mode = "half") -> Projection:
    """The set with every line of every ladder read off one coherent ladder, and what moved. A market that is not a ladder, or has fewer than two
    half lines told, comes back as it was; a figure with no ladder to be read off keeps its figure (``kept``)."""
    pooled = mode == "pooled"
    original: dict[Key, Figure] = {f.key: f for f in figures}
    anchors = _anchors(original)
    ladders: dict[str, dict[Decimal, float]] = {}
    for market in (*TOTALS, HANDICAP):
        got = _ladder(original, market, anchors, pooled=pooled)
        if got is not None:
            ladders[market] = got
    out: dict[Key, Figure] = dict(original)
    moves: list[Move] = []
    quarters: list[Key] = []
    for key, f in sorted(original.items()):
        market, selection, line = key
        if market not in ladders:
            continue
        canon_line = _canonical(f)[0]
        if is_quarter_line(canon_line):
            quarters.append(key)
            continue
        read = _read(market == HANDICAP, canon_line, ladders[market])
        if read is None:
            moves.append(Move(key, f.win, f.win, "kept"))
            continue
        out[key] = _back(f, *read)
        moves.append(Move(key, f.win, out[key].win, "half" if is_half(line) else "derived"))
    kept = {m.key for m in moves if m.kind == "kept"}
    for key in (
        quarters
    ):  # the quarter lines last: half the stake on each of two neighbours already projected
        market, selection, line = key
        f = original[key]
        near, far = (market, selection, line + STEP), (market, selection, line - STEP)
        easier, harder = out.get(near), out.get(far)
        if easier is None or harder is None or near in kept or far in kept:
            moves.append(Move(key, f.win, f.win, "kept"))
            kept.add(key)
            continue
        win, push = (
            round((easier.win + harder.win) / 2, 12),
            round((easier.push + harder.push) / 2, 12),
        )
        out[key] = Figure(
            f.market,
            f.selection,
            f.line,
            win,
            push,
            f.lo if f.lo is None or f.lo <= win else win,
            f.hi if f.hi is None or f.hi >= win else win,
        )
        moves.append(Move(key, f.win, out[key].win, "derived"))
    untouched = {
        m
        for m in ladders
        if all(
            abs(out[k].win - f.win) <= NOISE and abs(out[k].push - f.push) <= NOISE
            for k, f in original.items()
            if k[0] == m
        )
    }
    if untouched:  # a market that already is the ladder, to the storage's rounding, comes back exactly as it came
        for k in original:
            if k[0] in untouched:
                out[k] = original[k]
        moves = [
            Move(m.key, m.before, m.before, m.kind) if m.key[0] in untouched else m for m in moves
        ]
    return Projection(tuple(out[k] for k in sorted(out)), tuple(moves))


def shifts(projections: Iterable[Projection]) -> dict[str, float]:
    """How far the figures moved over a set of matches: the share that moved, the mean, median, 90th percentile and largest shift (in probability, in
    absolute value, over the figures that moved by more than the storage's rounding)."""
    moved: list[float] = []
    total = 0
    for p in projections:
        for m in p.moves:
            if m.kind == "kept":
                continue
            total += 1
            if abs(m.shift) > NOISE:
                moved.append(abs(m.shift))
    moved.sort()
    n = len(moved)
    return {
        "figures": float(total),
        "moved": float(n),
        "share_moved": n / total if total else 0.0,
        "mean_shift": sum(moved) / n if n else 0.0,
        "median_shift": moved[n // 2] if n else 0.0,
        "p90_shift": moved[int(n * 0.9)] if n else 0.0,
        "max_shift": moved[-1] if n else 0.0,
    }


def by_market(projections: Iterable[Projection]) -> dict[str, dict[str, float]]:
    """``shifts`` apart for each market."""
    grouped: dict[str, list[Move]] = defaultdict(list)
    for p in projections:
        for m in p.moves:
            grouped[m.key[0]].append(m)
    return {
        market: shifts([Projection((), tuple(moves))]) for market, moves in sorted(grouped.items())
    }


__all__ = [
    "ANCHOR_WEIGHT",
    "MODES",
    "NOISE",
    "TOTALS",
    "VERSION",
    "Move",
    "Projection",
    "by_market",
    "pava",
    "project",
    "shifts",
]
