"""Settling a pick: the result, on the basis the market settles on, or an honest 'pending'.

BASIS. 1X2, double chance, Over/Under, BTTS and Asian handicap settle on the
regulation score - 90 minutes plus stoppage time. Extra time and penalty
shoot-outs do not count (core.fixture_results.reg_goals_*).

WHAT IS SETTLED AUTOMATICALLY
  * a finished match (FT, AET, PEN) with a regulation score;
  * a cancelled match (CANC): never played, so every market is void.

WHAT IS NOT - it stays pending, with the reason, for a human:
  * postponed or suspended (PST, SUSP): bookmakers void after a delay that
    differs from book to book, so no delay is invented here;
  * abandoned (ABD): some markets may already be decided (an over 0.5 that
    has happened) and the rest void, depending on the book;
  * awarded or walkover (AWD, WO): the official result is not the played one,
    and books treat it differently;
  * anything still to be played or in play.

QUARTER LINES. A line ending in .25 or .75 is two half-stakes on the two
neighbouring lines (2.75 = half on 2.5, half on 3.0); each half wins, loses
or pushes, and the pair gives win, half-win, push, half-loss or loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

RULE_VERSION = "settle-v2"
"""v2 (9 Oct 2026): a match decided after 90 minutes settles when the provider STATES the 90-minute score
(``score.fulltime``, core.fixture_results.ft_goals_*), not only when it breaks down extra time - reg_goals_* is
COALESCE(ft_goals, goals - et_goals) since revision 0031, so v1 left such picks pending for nothing. Everything
else is v1's rule."""
BASIS = "regulation_90"

FINISHED = frozenset({"FT", "AET", "PEN"})
DECIDED_AFTER_NINETY = frozenset({"AET", "PEN"})
"""Statuses that mean the match went past 90 minutes. reg_goals_* can only be
trusted for these when the extra-time score is recorded, because it is derived by
subtracting it."""
VOID_STATUSES = frozenset({"CANC"})
REVIEW: dict[str, str] = {
    "PST": "postponed: bookmakers void after a delay that varies by book; not inferred",
    "SUSP": "suspended: it may resume or be voided depending on the book; not inferred",
    "ABD": "abandoned: some markets may already be decided and void rules vary by book; not inferred",
    "AWD": "awarded: the official result is not the played one and books treat it differently; not inferred",
    "WO": "walkover: no match was played but a result was awarded; books treat it differently; not inferred",
}


class Status(StrEnum):
    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    VOID = "void"
    HALF_WIN = "half_win"
    HALF_LOSS = "half_loss"


@dataclass(frozen=True, slots=True)
class MatchState:
    status_short: str
    reg_home: int | None
    reg_away: int | None
    et_home: int | None = None
    et_away: int | None = None
    """The extra-time goals the provider reported, if any."""
    ft_home: int | None = None
    ft_away: int | None = None
    """The 90-minute score the provider STATED (``score.fulltime``), if any.

    ``reg_goals_*`` is COALESCE(ft_goals, goals - COALESCE(et_goals, 0)): with neither the
    stated 90-minute score nor the extra-time breakdown it silently equals the score after
    extra time. For a match decided after extra time that is a claim we cannot make: see
    the check in ``settle``.
    """


@dataclass(frozen=True, slots=True)
class Settlement:
    status: Status
    profit_units: Decimal | None
    review_reason: str | None = None

    @property
    def is_final(self) -> bool:
        return self.status is not Status.PENDING


def _half(diff: Decimal) -> str:
    return "win" if diff > 0 else "loss" if diff < 0 else "push"


def _line_outcome(diff_at: list[Decimal]) -> Status:
    """diff_at: selected side's margin at each (sub-)line. One entry, or two for a quarter line."""
    parts = [_half(d) for d in diff_at]
    if len(parts) == 1:
        return {"win": Status.WIN, "loss": Status.LOSS, "push": Status.PUSH}[parts[0]]
    first, second = sorted(parts)
    pair = (first, second)
    return {
        ("win", "win"): Status.WIN,
        ("push", "win"): Status.HALF_WIN,
        ("push", "push"): Status.PUSH,
        ("loss", "push"): Status.HALF_LOSS,
        ("loss", "loss"): Status.LOSS,
    }[pair]  # ("loss", "win") cannot happen: the two lines are 0.5 apart


def _sub_lines(line: Decimal) -> list[Decimal]:
    quarters = line * 4
    if quarters != quarters.to_integral_value():
        raise ValueError(f"line {line} is not a multiple of 0.25")
    if int(quarters) % 2 != 0:  # .25 or .75
        return [line - Decimal("0.25"), line + Decimal("0.25")]
    return [line]


def profit(status: Status, odds: Decimal, stake: Decimal) -> Decimal:
    b = odds - 1
    return {
        Status.WIN: stake * b,
        Status.HALF_WIN: stake * b / 2,
        Status.PUSH: Decimal(0),
        Status.VOID: Decimal(0),
        Status.HALF_LOSS: -stake / 2,
        Status.LOSS: -stake,
    }[status].quantize(Decimal("0.0001"))


def market_outcome(market_key: str, selection: str, line: Decimal, home: int, away: int) -> Status:
    """How one selection settles on a known regulation score. Raises for an unknown market."""
    if market_key == "1X2":
        actual = "Home" if home > away else "Draw" if home == away else "Away"
        if selection not in ("Home", "Draw", "Away"):
            raise ValueError(f"unknown 1X2 selection {selection!r}")
        return Status.WIN if selection == actual else Status.LOSS
    if market_key == "DC":
        actual = "Home" if home > away else "Draw" if home == away else "Away"
        covers = {"1X": {"Home", "Draw"}, "12": {"Home", "Away"}, "X2": {"Draw", "Away"}}
        if selection not in covers:
            raise ValueError(f"unknown double-chance selection {selection!r}")
        return Status.WIN if actual in covers[selection] else Status.LOSS
    if market_key == "BTTS":
        both = home > 0 and away > 0
        if selection not in ("Yes", "No"):
            raise ValueError(f"unknown BTTS selection {selection!r}")
        return Status.WIN if both == (selection == "Yes") else Status.LOSS
    if market_key == "OU":
        total = Decimal(home + away)
        if selection == "Over":
            return _line_outcome([total - s for s in _sub_lines(line)])
        if selection == "Under":
            return _line_outcome([s - total for s in _sub_lines(line)])
        raise ValueError(f"unknown Over/Under selection {selection!r}")
    if market_key == "AH":
        # The line is applied to the SELECTED side: Home -0.75 means home goals - 0.75 vs away goals.
        if selection == "Home":
            margin = Decimal(home - away)
        elif selection == "Away":
            margin = Decimal(away - home)
        else:
            raise ValueError(f"unknown Asian handicap selection {selection!r}")
        return _line_outcome([margin + s for s in _sub_lines(line)])
    raise ValueError(f"no settlement rule for market {market_key!r}")


def settle(market_key: str, selection: str, line: Decimal, odds: Decimal, stake: Decimal,
           state: MatchState) -> Settlement:
    status = state.status_short.strip().upper()  # the provider spells "CANC" and "Canc"
    if status in VOID_STATUSES:
        return Settlement(Status.VOID, Decimal(0))
    if status in REVIEW:
        return Settlement(Status.PENDING, None, REVIEW[status])
    if status not in FINISHED:
        return Settlement(Status.PENDING, None, None)  # not played yet, or in play
    if state.reg_home is None or state.reg_away is None:
        return Settlement(Status.PENDING, None, "finished, but no regulation score is recorded")
    if status in DECIDED_AFTER_NINETY and state.et_home is None and state.ft_home is None:
        # reg_goals_* = COALESCE(ft_goals, goals - COALESCE(et_goals, 0)), so with neither
        # it equals the after-extra-time score. Settling 1X2, Over/Under or BTTS on that
        # would quietly treat extra-time goals as regulation goals. The match is left
        # unsettled and recorded as RESULT_UNRESOLVED instead.
        return Settlement(
            Status.PENDING, None,
            f"{status}: the match went past 90 minutes and neither the 90-minute score nor the "
            "extra-time score is recorded, so the regulation result cannot be derived",
        )
    try:
        outcome = market_outcome(market_key, selection, line, state.reg_home, state.reg_away)
    except ValueError as exc:
        return Settlement(Status.PENDING, None, str(exc))
    return Settlement(outcome, profit(outcome, odds, stake))
