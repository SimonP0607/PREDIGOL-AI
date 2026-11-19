"""The model's figures of one market made comparable with the implied probability and the history (plan EA, EA-202; decision of
19-nov-2026). Pure.

A price's implied probability is the margin-free consensus of the pair it belongs to, and the history counts only the matches the
bet won or lost; both leave the refunded matches out. The model's figure is a probability of winning that keeps them in: on a line
that can be refunded (a whole goal line, a draw-no-bet, an Asian handicap on a whole number) the two sides of the pair add up to less
than 1. Three rules put the three marks on the same footing:

* a pair that can be refunded is shown on the same terms: each side's figure divided by the pair's sum (the probability of winning
  if the bet is not refunded) - the pair's own sides, both present, or none;
* a quarter line (half won, half refunded) has no single figure that compares: none is shown;
* a double chance is two outcomes of three: its three figures add up to 2. Read from a model that answers the three outcomes
  (``one_x_two``), each one is the sum of its two outcomes; a figure stored otherwise is not shown.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Final, TypeVar

PUSH_KINDS: Final = frozenset({"over_under", "asian_handicap", "draw_no_bet"})
DOUBLE_CHANCE: Final = {"1X": ("Home", "Draw"), "12": ("Home", "Away"), "X2": ("Draw", "Away"),
                        "Home/Draw": ("Home", "Draw"), "Home/Away": ("Home", "Away"), "Draw/Away": ("Draw", "Away")}
DC_SUM_TOLERANCE: Final = 0.05

T = TypeVar("T")


def quarter(line: Decimal | float) -> bool:
    return abs(Decimal(str(line)) * 4) % 2 == 1


def pair_key(kind: str, selection: str, line: Decimal | float) -> tuple[str, Decimal]:
    """The two sides of one refundable bet share this key: a total's line, a handicap's home line (the away side at its negation)."""
    v = Decimal(str(line))
    if kind == "asian_handicap" and selection == "Away":
        v = -v
    return kind, v + 0  # -0 is 0


def conditional(kind: str, figures: Mapping[tuple[str, Decimal], float]) -> dict[tuple[str, Decimal], float | None]:
    """(selection, line) -> the figure on the terms of the implied probability, or None when it must not be shown."""
    out: dict[tuple[str, Decimal], float | None] = {}
    if kind not in PUSH_KINDS:
        return dict(figures)
    pairs: dict[tuple[str, Decimal], list[tuple[str, Decimal]]] = {}
    for sel, line in figures:
        pairs.setdefault(pair_key(kind, sel, line), []).append((sel, line))
    for members in pairs.values():
        if any(quarter(line) for _, line in members):
            out.update(dict.fromkeys(members))
            continue
        if len(members) != 2:
            out.update(dict.fromkeys(members))
            continue
        total = sum(figures[m] for m in members)
        if total <= 0:
            out.update(dict.fromkeys(members))
            continue
        for m in members:
            out[m] = figures[m] / total
    return out


def double_chance(selection: str, outcome: Callable[[str], float | None]) -> float | None:
    """A double chance from the three outcomes of the same model (``outcome("Home")`` ...), or None."""
    parts = DOUBLE_CHANCE.get(selection)
    if parts is None:
        return None
    values = [outcome(p) for p in parts]
    if any(v is None for v in values):
        return None
    return min(1.0, sum(v for v in values if v is not None))


def double_chance_ok(figures: Sequence[float]) -> bool:
    """Three double-chance figures of one model add up to 2."""
    return len(figures) == 3 and abs(sum(figures) - 2.0) <= DC_SUM_TOLERANCE
