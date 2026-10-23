"""Settling a bet on a COUNT of the match - corners, cards, the goals of a half - once the count is known (plan F11).

``fbi.picks.settlement`` grades the five markets of the pipeline on the score after 90 minutes. The families of F9 and F10 are graded on other
numbers: the corners of the match, the cards in one of the conventions of ``fbi.market.rules``, the goals of the first or the second half. The
arithmetic of a bet is the same - a line, a side, a quarter line that is two half-stakes - and only the numbers and the words of the selections
differ, so this module holds exactly that: given the numbers a rule reads and the bet (kind, subject, selection, line), the status it settles with.

What it does NOT decide, because it is not its work:

* whether the numbers exist - the rule says what they are (``fbi.market.rules``) and an unknown count is NULL, never zero: ``settle_numbers``
  returns ``None`` for a bet whose count is missing, and a missing count never turns into a loss;
* whether the match was played to the end, or when a match that was not played is void (the 72 hours of ``fbi.picks.settlement``);
* the stake, the odds and the profit (``fbi.picks.settlement.profit``).

Nothing here is wired into the settlement of a pick yet: a pick on a family exists only after a validated calibrator and the decision layer, and
then the version of the settlement becomes ``settle-v5``. Today the module grades the stored forecasts of the families after the matches
(``fbi.families.score``): the same arithmetic, so the day a family is priced it is graded as it has been all along.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Final

from fbi.market.rules import Rule
from fbi.picks.settlement import Status, market_outcome

RESULT_WORDS: Final = {"Home": "1", "Draw": "X", "Away": "2"}
"""The words of a result in the price tables, and the letters HT/FT is spelt with ("Home/Draw" is a home lead at half time that ended level)."""
FIRST_HALF: Final = "1st Half"
SECOND_HALF: Final = "2nd Half"
TIE: Final = "Draw"
"""The selections of the highest scoring half, in the words of the price tables."""

KINDS: Final = frozenset({"over_under", "odd_even", "one_x_two", "double_chance", "draw_no_bet", "both_teams_score", "asian_handicap"})
HALVES_KINDS: Final = frozenset({"half_time_full_time", "highest_scoring_half"})


def _count(subject: str, home: int, away: int) -> int:
    """The number a line is compared with: the count of one side, or the sum of both."""
    if subject == "match":
        return home + away
    if subject == "home":
        return home
    if subject == "away":
        return away
    raise ValueError(f"a bet on the count of {subject!r} is not graded here")


def count_outcome(kind: str, subject: str, selection: str, line: Decimal, home: int, away: int) -> Status:
    """How one selection settles on the two counts (home, away) a rule reads. Raises for a kind, a subject or a selection it does not know."""
    if kind == "over_under":
        return market_outcome("OU", selection, line, _count(subject, home, away), 0)
    if kind == "odd_even":
        if selection not in ("Odd", "Even"):
            raise ValueError(f"unknown odd/even selection {selection!r}")
        return Status.WIN if (_count(subject, home, away) % 2 == 1) == (selection == "Odd") else Status.LOSS
    if kind not in KINDS:
        raise ValueError(f"no settlement for the kind of bet {kind!r}")
    if subject != "match":
        raise ValueError(f"a {kind} bet compares the two sides: its subject is the match, not {subject!r}")
    if kind == "one_x_two":
        return market_outcome("1X2", selection, line, home, away)
    if kind == "double_chance":
        return market_outcome("DC", selection, line, home, away)
    if kind == "both_teams_score":
        return market_outcome("BTTS", selection, line, home, away)
    if kind == "asian_handicap":
        return market_outcome("AH", selection, line, home, away)
    # draw no bet: the stake comes back when the two counts are level
    if selection not in ("Home", "Away"):
        raise ValueError(f"unknown draw-no-bet selection {selection!r}")
    if home == away:
        return Status.PUSH
    return Status.WIN if (selection == "Home") == (home > away) else Status.LOSS


def _result_word(home: int, away: int) -> str:
    return "Home" if home > away else "Away" if away > home else "Draw"


def halves_outcome(kind: str, subject: str, selection: str, first: tuple[int, int], second: tuple[int, int]) -> Status:
    """How HT/FT and the highest scoring half settle on the goals of the two halves, each as (home, away)."""
    if kind == "half_time_full_time":
        if subject != "match":
            raise ValueError(f"HT/FT is a bet on the match, not on {subject!r}")
        half_time = _result_word(*first)
        full_time = _result_word(first[0] + second[0], first[1] + second[1])
        if not (selection.count("/") == 1 and all(w in RESULT_WORDS for w in selection.split("/"))):
            raise ValueError(f"unknown HT/FT selection {selection!r}")
        return Status.WIN if selection == f"{half_time}/{full_time}" else Status.LOSS
    if kind == "highest_scoring_half":
        if selection not in (FIRST_HALF, SECOND_HALF, TIE):
            raise ValueError(f"unknown highest-scoring-half selection {selection!r}")
        before, after = _count(subject, *first), _count(subject, *second)
        actual = FIRST_HALF if before > after else SECOND_HALF if after > before else TIE
        return Status.WIN if selection == actual else Status.LOSS
    raise ValueError(f"no settlement for the kind of bet {kind!r}")


def settle_numbers(rule: Rule, kind: str, subject: str, selection: str, line: Decimal,
                   values: Mapping[str, int | None]) -> Status | None:
    """The status of a selection graded by ``rule`` on the columns of a finished match (``values``: the columns of the view of outcomes), or
    ``None`` when the rule cannot grade it - it has no columns, or a count it reads is unknown. An unknown count is never read as a zero."""
    if not rule.liquidable:
        return None
    numbers = [values.get(column) for column in rule.columns]
    if any(n is None for n in numbers):
        return None
    counts = [int(n) for n in numbers if n is not None]
    if rule.measure == "goals_halves":
        if len(counts) != 4:
            raise ValueError(f"{rule.key} reads {len(counts)} numbers, not the four of two halves")
        return halves_outcome(kind, subject, selection, (counts[0], counts[1]), (counts[2], counts[3]))
    if len(counts) != 2:
        raise ValueError(f"{rule.key} reads {len(counts)} numbers, not a pair of counts")
    return count_outcome(kind, subject, selection, line, counts[0], counts[1])
