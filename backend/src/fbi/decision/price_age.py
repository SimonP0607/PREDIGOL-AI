"""How old a price may be when decision-v2 judges it: the age rule, as VERSIONED DATA (plan 2026, AD-B06, IA-067; decision n.º 11).

TWO RULES, named in every decision that uses them (``Price.age_rule``) and handed to the interface as data (``PriceAgeRule.as_json``,
contracts C-01 and C-02: the interface receives the thresholds and the state, it never fixes them):

    price-age-v1   decision-v1's own, IMPORTED from ``fbi.intel.decision``: a price older than ``MAX_PRICE_AGE`` (3 h) is stale at the
                   market stage (3), and at a final checkpoint (``FINAL_CHECKPOINTS``) one older than ``FINAL_FRESH`` (30 min) is not fresh
                   at the price stage (9). The rule of ``decision-v2.0``, the evidence of P1.
    price-age-v2   by horizon, for the odds book's price (``fbi.decision.book_price``): the cadence of the book's refreshes plus the usual
                   delay of an ask (p99 about 15 min) - 30 + 15, 60 + 15 and 180 + 15 min - with each band's edge moved 15 min EARLIER than
                   the ask that opens it, so that a decision taken just before a scheduled refresh still reads the refresh before it:

                       345 min or more before kick-off   at most 195 min old
                       from 345 to 45 min                at most  75 min old
                       less than 45 min                  at most  45 min old

                   A band runs from its ``from_minutes`` (included) to the next band's (excluded): at exactly 345 min the limit is 195, at
                   exactly 45 it is 75. A price exactly as old as its limit is in force; one second older is not. The same limit is held at
                   the market stage (3) and, at a final checkpoint, at the price stage (9), so stage 9 never fires alone. A price without an
                   age cannot be checked and is old (``no_age``). The rule of ``decision-v2.1``.

THE STATE of the price (``PRICE_STATES``, the list contract C-02 reads): ``vigente`` (a price within its limit), ``antiguo`` (older than its
limit, or with no age: ``reason`` says which) and ``sin_precio`` (no price: ``reason`` is the source's own word - ``never_asked``,
``not_quoted``, ``withdrawn``, ``unreadable`` - or ``no_price``). A measurement and a word for the reader: the STAGES decide the state of
the decision, with decision-v1's codes (``price_stale``, ``price_not_fresh``, ``no_price``).

Pure: no database, no clock. Nothing here relaxes itself: when the book's refresh stops, more prices are ``antiguo`` and the reason says so.
Where it differs from decision-v1 (on purpose, approved by the owner as decision n.º 11, in shadow only): 195 min is above decision-v1's 3 h
far from kick-off and 45-75 min above its 30 min at the final checkpoints, while 75 min is far below its 3 h between T-5 h 45 and T-45 min.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from fbi.intel import decision

VIGENTE: Final = "vigente"
ANTIGUO: Final = "antiguo"
SIN_PRECIO: Final = "sin_precio"
PRICE_STATES: Final = (VIGENTE, ANTIGUO, SIN_PRECIO)
"""The state of a decision's price (contract C-02's ``price_state``)."""

NO_AGE: Final = "no_age"
OVER_LIMIT: Final = "over_limit"
OVER_FINAL: Final = "over_final"
NO_PRICE: Final = "no_price"
REASONS: Final = (NO_AGE, OVER_LIMIT, OVER_FINAL, NO_PRICE)
"""Why a price is ``antiguo`` (the first three) or ``sin_precio`` without the source's own word (the last)."""


@dataclass(frozen=True, slots=True)
class AgeBand:
    """A band of time before kick-off and the oldest price it accepts: from ``from_minutes`` before kick-off (included) to the next band's."""

    name: str
    from_minutes: float
    max_age: timedelta
    nominal_from_minutes: float
    """Where the band would start without the lead: the instant of the ask that opens it."""

    @property
    def max_age_minutes(self) -> float:
        return self.max_age.total_seconds() / 60


@dataclass(frozen=True, slots=True)
class Limit:
    """The limits that hold for one price at one moment."""

    band: AgeBand
    market: timedelta
    """The oldest price the market stage (3) accepts."""
    final: timedelta | None
    """The oldest price the price stage (9) accepts at a final checkpoint; None elsewhere."""


@dataclass(frozen=True, slots=True)
class PriceCheck:
    """The state of one price under a rule, with why and against which limit."""

    state: str
    reason: str | None
    band: str
    max_age_minutes: float
    """The limit that held: the final one at a final checkpoint when it is the stricter, the band's otherwise."""
    rule: str


@dataclass(frozen=True, slots=True)
class PriceAgeRule:
    """A versioned rule of the age of a price: bands by time before kick-off (the widest first) and, at the final checkpoints, a limit of
    its own (``final_max_age``) or the band's (None)."""

    version: str
    bands: tuple[AgeBand, ...]
    """Ordered from the farthest from kick-off; the last band starts at 0."""
    final_max_age: timedelta | None
    lead_minutes: float
    require_age: bool
    """Whether a price without an age is old (it cannot be checked)."""
    source: str
    """What the numbers come from."""

    @property
    def flat(self) -> bool:
        """One limit whatever the time to kick-off (decision-v1's rule)."""
        return len(self.bands) == 1

    def band_of(self, minutes_to_kickoff: float) -> AgeBand:
        for b in self.bands:
            if minutes_to_kickoff >= b.from_minutes:
                return b
        return self.bands[-1]

    def limit(self, minutes_to_kickoff: float, checkpoint: str) -> Limit:
        b = self.band_of(minutes_to_kickoff)
        final = None
        if checkpoint in decision.FINAL_CHECKPOINTS:
            final = b.max_age if self.final_max_age is None else self.final_max_age
        return Limit(b, b.max_age, final)

    def check(self, *, priced: bool, age: timedelta | None, minutes_to_kickoff: float, checkpoint: str,
              missing: str | None = None) -> PriceCheck:
        """The state of a price: ``sin_precio`` without one, ``antiguo`` past its limit (or without an age, where the rule asks for one),
        ``vigente`` otherwise. Pure."""
        lim = self.limit(minutes_to_kickoff, checkpoint)
        held = lim.market if lim.final is None else min(lim.market, lim.final)
        minutes = held.total_seconds() / 60
        if not priced:
            return PriceCheck(SIN_PRECIO, missing or NO_PRICE, lim.band.name, minutes, self.version)
        if age is None:
            return PriceCheck(ANTIGUO if self.require_age else VIGENTE, NO_AGE if self.require_age else None, lim.band.name, minutes,
                              self.version)
        if age > lim.market:
            return PriceCheck(ANTIGUO, OVER_LIMIT, lim.band.name, minutes, self.version)
        if lim.final is not None and age > lim.final:
            return PriceCheck(ANTIGUO, OVER_FINAL, lim.band.name, minutes, self.version)
        return PriceCheck(VIGENTE, None, lim.band.name, minutes, self.version)

    def as_json(self) -> dict[str, Any]:
        """The rule as data (contracts C-01 and C-02): its version, each band in minutes before kick-off (``to_minutes`` None: no upper
        edge) with its limit, the limit at the final checkpoints, the lead of the edges and the states a price can take."""
        out = []
        for i, b in enumerate(self.bands):
            out.append({"name": b.name, "from_minutes": b.from_minutes, "to_minutes": None if i == 0 else self.bands[i - 1].from_minutes,
                        "max_age_minutes": b.max_age_minutes, "nominal_from_minutes": b.nominal_from_minutes})
        return {"version": self.version, "bands": out, "lead_minutes": self.lead_minutes,
                "final_checkpoints": sorted(decision.FINAL_CHECKPOINTS),
                "final_max_age_minutes": None if self.final_max_age is None else self.final_max_age.total_seconds() / 60,
                "final_rule": "own" if self.final_max_age is not None else "band", "require_age": self.require_age,
                "age_from": "the ask that confirmed the price", "states": list(PRICE_STATES), "reasons": list(REASONS),
                "source": self.source}


V1: Final = PriceAgeRule("price-age-v1", (AgeBand("any", 0.0, decision.MAX_PRICE_AGE, 0.0),), decision.FINAL_FRESH, 0.0, False,
                         "decision-v1 (fbi.intel.decision: MAX_PRICE_AGE, FINAL_FRESH), imported")

LEAD: Final = timedelta(minutes=15)
"""How much earlier than the ask that opens it each band's edge starts (the p99 of an ask's delay, plan INT-A06 / TRES, 11-15 Nov 2026)."""
CADENCE: Final[Mapping[str, tuple[timedelta, timedelta]]] = {
    "far": (timedelta(hours=6), timedelta(minutes=180)),
    "near": (timedelta(hours=1), timedelta(minutes=60)),
    "last": (timedelta(0), timedelta(minutes=30)),
}
"""The book's refreshes (plan Cuotas, BE-011): from this time before kick-off, an ask every so often."""


def _band(name: str) -> AgeBand:
    opens, every = CADENCE[name]
    nominal = opens.total_seconds() / 60
    start = max(0.0, nominal - LEAD.total_seconds() / 60) if nominal > 0 else 0.0
    return AgeBand(name, start, every + LEAD, nominal)


V2: Final = PriceAgeRule("price-age-v2", (_band("far"), _band("near"), _band("last")), None, LEAD.total_seconds() / 60, True,
                         "the book's refresh cadence plus 15 min, edges 15 min earlier (decision n.º 11, 16 Nov 2026)")

RULES: Final[Mapping[str, PriceAgeRule]] = {r.version: r for r in (V1, V2)}
