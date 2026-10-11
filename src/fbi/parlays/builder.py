"""The automatic parlay builder (REVIEW PREDIGOL, 11 Oct 2026, point 15): the user says what they are looking for and
PrediGol builds the parlay with the rule of its own parlays (``fbi.parlays.persist``, ``parlay-v4``) - or says
plainly that there is none, and why.

The user's filters only NARROW the pool that rule chooses from; none of them loosens a rule:

  window        matches kicking off in the next ``hours`` (3 to 72);
  legs          between ``min_legs`` and ``max_legs`` (2 to 7, parlay-v4's own range);
  markets       some of 1X2 / OU / BTTS / AH / DC (none: all);
  competitions  some competition ids (none: all);
  leg odds      each leg's current best price between ``min_odds`` and ``max_odds``;
  total odds    the combined odds at most ``max_total_odds``: a leg that would take the parlay past it is not added.

Everything else is parlay-v4, unchanged and shared with PrediGol's own parlays: the value gate at the price available
now and a measured interval (``fbi.picks.daily.passing``), the AI review in enforce mode, at least three books per
leg, no interval wider than 40 points, no quarter lines, one leg per match, no team twice, at most two legs of one
competition, the joint probability at the pessimistic end corrected for significant negative dependence, the legs
chosen greedily by expected log growth of a 1% stake - and a parlay only when it grows. Too few legs worth combining
means no parlay: never a padded one, and never one built from selections that do not pass these rules.

Nothing here touches the database: the API service loads the pool (``fbi.api.services.product.built_parlay``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from fbi.parlays.persist import (
    Correlations,
    Spec,
    choose,
    correlated_pairs,
    eligible_leg,
    joint_low,
    parlay_elg,
    quarter_line,
)
from fbi.picks.daily import Ranked

RULE_VERSION = "builder-v1"
"""On top of ``fbi.parlays.persist.RULE_VERSION``: what the user's filters add (they only narrow)."""
MARKETS: tuple[str, ...] = ("1X2", "OU", "BTTS", "AH", "DC")
MIN_HOURS, MAX_HOURS = 3, 72
MIN_LEGS, MAX_LEGS = 2, 7

Reason = Literal["no_candidates", "no_match", "too_few_legs", "total_odds_cap", "no_growth"]
"""Why there is no parlay: nothing passed the rules in the window; nothing passed them AND the filters; fewer
combinable matches than the minimum; the total-odds cap is what stops it; or no combination of at least the minimum
grows (the independence rules leave too few, or the legs together are not worth it)."""


class FilterError(ValueError):
    """A filter outside its range: the API answers 422 with the field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class Filters:
    hours: int = 24
    min_legs: int = 2
    max_legs: int = 4
    markets: tuple[str, ...] = ()
    competitions: tuple[int, ...] = ()
    min_odds: Decimal | None = None
    max_odds: Decimal | None = None
    max_total_odds: Decimal | None = None

    def __post_init__(self) -> None:
        if not MIN_HOURS <= self.hours <= MAX_HOURS:
            raise FilterError("hours", f"the window is {MIN_HOURS} to {MAX_HOURS} hours")
        if not MIN_LEGS <= self.min_legs <= self.max_legs <= MAX_LEGS:
            raise FilterError("legs", f"legs: {MIN_LEGS} <= min_legs <= max_legs <= {MAX_LEGS}")
        unknown = [m for m in self.markets if m not in MARKETS]
        if unknown:
            raise FilterError("markets", f"unknown markets: {', '.join(unknown)}")
        if self.min_odds is not None and self.max_odds is not None and self.min_odds > self.max_odds:
            raise FilterError("odds", "min_odds is above max_odds")
        if self.max_total_odds is not None and self.max_total_odds <= 1:
            raise FilterError("max_total_odds", "max_total_odds must be above 1")

    @classmethod
    def of(cls, *, hours: int, min_legs: int, max_legs: int, markets: Iterable[str] = (),
           competitions: Iterable[int] = (), min_odds: Decimal | None = None, max_odds: Decimal | None = None,
           max_total_odds: Decimal | None = None) -> Filters:
        """Sets in a canonical order: two requests asking the same thing are the same filters (and one cache entry)."""
        return cls(hours=hours, min_legs=min_legs, max_legs=max_legs, markets=tuple(sorted(set(markets))),
                   competitions=tuple(sorted(set(competitions))), min_odds=min_odds, max_odds=max_odds,
                   max_total_odds=max_total_odds)


def in_filters(x: Ranked, f: Filters, *, at: datetime) -> bool:
    c = x.leg.candidate
    if not at <= c.kickoff_at < at + timedelta(hours=f.hours):
        return False
    if f.markets and c.market_key not in f.markets:
        return False
    if f.competitions:
        comp = x.row.get("competition_id")
        if comp is None or int(comp) not in f.competitions:
            return False
    price = c.price
    if price is None:
        return False
    if f.min_odds is not None and price < f.min_odds:
        return False
    return f.max_odds is None or price <= f.max_odds


def combinable(x: Ranked) -> bool:
    """A leg a parlay can hold (parlay-v4): three books or more, an interval no wider than 40 points, no quarter line.
    The independence rules (one leg per match, no team twice, two per competition) apply while choosing."""
    return eligible_leg(x) and not quarter_line(x.leg.candidate.line)


def total_odds(legs: Iterable[Ranked]) -> Decimal:
    return math.prod((x.leg.candidate.price or Decimal(0) for x in legs), start=Decimal(1))


@dataclass(frozen=True, slots=True)
class Funnel:
    """How many selections reached each step - the parlay's "why not more" in numbers."""

    passing: int
    """Picks of the window through the value gate at the current price, with a measured interval (one per selection)."""
    reviewed: int
    """Of those, still in after the AI review (it only removes in enforce mode)."""
    matching: int
    """Of those, the ones that match the user's filters."""
    combinable: int
    """Of those, the ones a parlay can hold: three books or more, an interval no wider than 40 points, no quarter line."""
    matches: int
    """The distinct matches among the combinable ones: a parlay has one leg per match."""


@dataclass(frozen=True, slots=True)
class Built:
    legs: tuple[Ranked, ...]
    """By kick-off; empty when there is no parlay."""
    reason: Reason | None
    funnel: Funnel
    combined_odds: Decimal | None
    p_all_low: float | None
    """P(every leg wins) at the pessimistic probabilities, corrected for significant negative dependence."""
    expected_log_growth: float | None
    correlated_pairs: int
    """Pairs of legs whose joint probability the measured dependence lowered."""


def build(passing: list[Ranked], reviewed: list[Ranked], f: Filters, *, at: datetime,
          correlations: Correlations | None = None) -> Built:
    """``passing``: the window's selections through the value gate; ``reviewed``: the same after the AI review."""
    matching = [x for x in reviewed if in_filters(x, f, at=at)]
    usable = [x for x in matching if combinable(x)]
    funnel = Funnel(passing=len(passing), reviewed=len(reviewed), matching=len(matching), combinable=len(usable),
                    matches=len({x.leg.candidate.fixture_id for x in usable}))
    spec = Spec("custom", f.min_legs, f.max_legs, 1)
    cap = f.max_total_odds
    legs = choose(matching, spec, correlations,
                  allow=None if cap is None else (lambda chosen, x: total_odds([*chosen, x]) <= cap))
    if legs is None:
        return Built(legs=(), reason=_why_not(passing, matching, funnel, f, spec, correlations), funnel=funnel,
                     combined_odds=None, p_all_low=None, expected_log_growth=None, correlated_pairs=0)
    ordered = tuple(sorted(legs, key=lambda x: (x.leg.candidate.kickoff_at, x.leg.candidate.fixture_id)))
    chosen = list(ordered)
    return Built(legs=ordered, reason=None, funnel=funnel, combined_odds=total_odds(chosen),
                 p_all_low=joint_low(chosen, correlations),
                 expected_log_growth=parlay_elg(chosen, correlations=correlations),
                 correlated_pairs=len(correlated_pairs(chosen, correlations)))


def _why_not(passing: list[Ranked], matching: list[Ranked], funnel: Funnel, f: Filters, spec: Spec,
             correlations: Correlations | None) -> Reason:
    if not passing:
        return "no_candidates"
    if not matching:
        return "no_match"
    if funnel.matches < f.min_legs:
        return "too_few_legs"
    if f.max_total_odds is not None and choose(matching, spec, correlations) is not None:
        return "total_odds_cap"
    return "no_growth"


__all__ = ["MARKETS", "MAX_HOURS", "MAX_LEGS", "MIN_HOURS", "MIN_LEGS", "RULE_VERSION", "Built", "FilterError",
           "Filters", "Funnel", "Reason", "build", "combinable", "in_filters", "total_odds"]
