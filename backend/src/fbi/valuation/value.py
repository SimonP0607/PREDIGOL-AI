"""The value of one selection with its uncertainty (``value-v2``, plan 2026 AD-E02, IA-097), in SHADOW.

WHAT IT GIVES. For one selection, one probability and one price, as of one moment:

    ev ............. expected value per unit staked at the price:  P(win) * odds - (1 - P(push))
    ev_low/ev_high . its 95 % interval, from the uncertainty of the probability AND of the price (``METHOD``: the delta method)
    fair_odds ...... the price at which the bet breaks even: (1 - P(push)) / P(win) = 1 / P(win | settled)
    price_age_min .. how old the price is at the moment (the moment of the decision, never the clock)
    books .......... how many bookmakers priced it; fewer than ``MIN_BOOKS`` is «una sola casa» (``single_book``) and NEVER confirms
    verdict ........ whether the value is confirmed (``CONFIRMED``) or the first reason it is not (``VERDICTS``)

THE ARITHMETIC. ``win`` and ``push`` are UNCONDITIONAL: the probability that the bet wins and that it returns the stake. A whole line
can return the stake; a quarter line is half the stake on each neighbouring line, so it can win or lose half - and because the expected
value is linear in each leg, the averages of the two legs' (win, push) give its expected value exactly (``fbi.models.lines``, the
convention ``fbi.picks.settlement`` settles by). A probability CONDITIONAL on the bet settling (the convention of ``picks.picks`` and of
decision-v1) is turned into ``win`` by ``Chance.conditional``: ``win = p * (1 - push)``. The two conventions are kept apart on purpose:
an expected value computed as ``(1 - push) * (p * odds - 1)`` with an unconditional ``p`` understates it by ``push * p * odds``.

THE UNCERTAINTY (delta method, two independent errors, a 95 % interval of the expected value):

    probability  the interval of the probability (its own: the model's ``p_lo``/``p_hi``, or the single figure's) at its own level -
                 the models' is 90 % (``fbi.models.goals.INTERVAL_LEVEL``, quantiles over parameter draws) - read as a normal error,
                 each side on its own: ``sd_low = (win - low) / z(level)``; it moves ``ev`` by ``odds * sd``
    price        the price may have moved since it was confirmed: the standard deviation of its logarithm grows with its age as
                 ``PRICE_DRIFT_PER_SQRT_HOUR * sqrt(hours)``, capped at ``PRICE_DRIFT_CAP`` (both measured in production, see below);
                 it moves ``ev`` by ``win * odds * sd``

    ev_low = ev - Z * sqrt((odds * sd_low)**2 + (win * odds * sd_price)**2)      (and ev_high the same with ``sd_high``)

so the interval always contains ``ev``, it widens with the interval of the probability and with the age of the price, and it is clipped
to what a bet can do (``-(1 - push)`` .. ``odds - 1``). The calibrator's own error is NOT in it (no calibrator states one): an interval
from a model's raw number is carried to its calibrated number by width (``transported``), and the reading says so (``interval_basis``).

NO RANGES OF ODDS. Nothing here depends on how big the price is: the verdict reads the interval, the books, the age and the seal - never
a band of odds (property tested: two selections with the same interval, books and age get the same verdict whatever their odds).

THE PRICE'S MOMENT. A price confirmed AFTER the moment of the decision is a leak (AD-A04): the reading refuses it (``FUTURE_PRICE``)
and computes nothing from it.

MEASURED (production, read-only, 17 Nov 2026): the change of the logarithm of the best price between consecutive consensus captures of
the same selection (``market.market_consensus``, Shin, 1X2 / total 2.5 / both teams to score, at least 3 books, the 434 matches that
kicked off between 8 and 1 days before; 9,205 pairs of captures, 172 to 230 matches per band): root mean square 0.042 at 2.4-3 h apart (n = 1,302), 0.043 at 3-6 h
(n = 1,806), 0.055 at 6-12 h (n = 2,142), 0.066 at 12-24 h (n = 2,639), 0.050 at 24-48 h (n = 1,316). ``PRICE_DRIFT_PER_SQRT_HOUR``
is the largest of rms / sqrt(hours) over those bands (0.042 / sqrt(2.95)) and ``PRICE_DRIFT_CAP`` the largest rms: an envelope that
over-states the drift of an old price rather than under-states it. No capture is closer than 2.4 h, so for a price minutes old the
envelope is an extrapolation (``sqrt`` of time, the random walk's).

PURE: values in, a reading out - no database, no clock, no model. Its reader is decision-v2 (``fbi.decision.engine``, a measurement no
stage reads) and, in the future, the parlays of ``parlay-v6`` (AD-E06); decision-v1 never reads it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from statistics import NormalDist
from typing import Any, Final

from fbi.intel.decision import MIN_BOOKS
from fbi.models.goals import INTERVAL_LEVEL

VERSION: Final = "value-v2"
METHOD: Final = "delta"
Z: Final = 1.96
"""The 95 % interval of the expected value."""
PROBABILITY_LEVEL: Final = INTERVAL_LEVEL
"""The level of the models' probability intervals (90 %: ``fbi.models.goals``, imported, never copied)."""
PRICE_DRIFT_PER_SQRT_HOUR: Final = 0.0243
"""The standard deviation of the logarithm of the best price after one hour (measured, see the module's note)."""
PRICE_DRIFT_CAP: Final = 0.066
"""The largest root mean square change of the logarithm of the best price measured up to 48 h (see the module's note)."""
MIN_BOOKS_TO_CONFIRM: Final = MIN_BOOKS
"""Fewer bookmakers than this is «una sola casa»: it never confirms (decision-v1's ``MIN_BOOKS``, imported, never copied)."""

CONFIRMED: Final = "confirmed"
FUTURE_PRICE: Final = "future_price"
NO_PRICE: Final = "no_price"
NO_PROBABILITY: Final = "no_probability"
NO_INTERVAL: Final = "no_interval"
NO_AGE: Final = "no_age"
SINGLE_BOOK: Final = "single_book"
UNCALIBRATED: Final = "uncalibrated"
NOT_POSITIVE: Final = "interval_includes_loss"
VERDICTS: Final = (FUTURE_PRICE, NO_PRICE, NO_PROBABILITY, NO_INTERVAL, NO_AGE, SINGLE_BOOK, UNCALIBRATED, NOT_POSITIVE, CONFIRMED)
"""In the order they are checked: the first that applies is the verdict. Only ``CONFIRMED`` confirms."""
WHY: Final = {
    FUTURE_PRICE: "precio posterior al momento de la decisión: fuga, no se usa",
    NO_PRICE: "sin precio", NO_PROBABILITY: "sin probabilidad",
    NO_INTERVAL: "la probabilidad no trae intervalo: el VE no tiene intervalo",
    NO_AGE: "el precio no tiene edad: no se sabe cuánto pudo moverse",
    SINGLE_BOOK: f"una sola casa (menos de {MIN_BOOKS} casas): no confirma",
    UNCALIBRATED: "probabilidad sin calibrar: no confirma",
    NOT_POSITIVE: "el intervalo del VE incluye pérdida", CONFIRMED: "VE positivo en todo su intervalo, con precio de varias casas"}


@dataclass(frozen=True, slots=True)
class Chance:
    """The probability side of a selection: UNCONDITIONAL win and push, the 95 % interval of the win and its seal."""

    win: float
    push: float = 0.0
    low: float | None = None
    high: float | None = None
    calibrated: bool = True
    interval_basis: str = "own"
    """Where the interval comes from: ``own`` (the number's own interval), ``transported`` (a raw number's interval carried to its
    calibrated number by width, ``transported``), ``none``."""
    level: float = PROBABILITY_LEVEL
    """The level of ``low``/``high`` (the models' 90 % by default)."""

    def __post_init__(self) -> None:
        if not 0.0 < self.level < 1.0:
            raise ValueError(f"an interval's level is in (0, 1), not {self.level!r}")
        for name in ("win", "push"):
            v = getattr(self, name)
            if not (math.isfinite(v) and 0.0 <= v <= 1.0):
                raise ValueError(f"{name} is a probability, not {v!r}")
        if self.win + self.push > 1.0 + 1e-9:
            raise ValueError(f"win {self.win} and push {self.push} add up to more than one")

    @classmethod
    def conditional(cls, p: float, push: float = 0.0, low: float | None = None, high: float | None = None, *, calibrated: bool = True,
                    interval_basis: str = "own") -> Chance:
        """From a probability CONDITIONAL on the bet settling (``picks.picks``, decision-v1): every number times ``1 - push``."""
        settled = 1.0 - push
        return cls(p * settled, push, None if low is None else low * settled, None if high is None else high * settled, calibrated,
                   interval_basis if low is not None and high is not None else "none")

    @property
    def has_interval(self) -> bool:
        return self.low is not None and self.high is not None


@dataclass(frozen=True, slots=True)
class Quote:
    """The price side: the best price, how many bookmakers priced it and when it was last confirmed."""

    odds: float | None
    books: int | None
    price_at: datetime | None
    source: str = "consensus"


def transported(p: float, p_raw: float, low: float | None, high: float | None) -> tuple[float | None, float | None]:
    """The interval of a raw number carried to its calibrated number ``p`` by width (each side on its own), within [0, 1]. Pure."""
    if low is None or high is None:
        return None, None
    return max(0.0, p - max(0.0, p_raw - low)), min(1.0, p + max(0.0, high - p_raw))


def price_sd(age_minutes: float) -> float:
    """The standard deviation of the logarithm of a price ``age_minutes`` old (the measured envelope). Pure."""
    return min(PRICE_DRIFT_PER_SQRT_HOUR * math.sqrt(max(0.0, age_minutes) / 60.0), PRICE_DRIFT_CAP)


def expected_value(win: float, push: float, odds: float) -> float:
    """Per unit staked: ``win * (odds - 1) - lose`` = ``win * odds - (1 - push)``. Increasing in ``odds`` and in ``win``. Pure."""
    return win * odds - (1.0 - push)


def fair_odds(win: float, push: float) -> float | None:
    """The price at which the bet breaks even: ``(1 - push) / win``; None when it cannot win. Pure."""
    return None if win <= 0 else (1.0 - push) / win


@dataclass(frozen=True, slots=True)
class ValueReading:
    """What ``assess`` says of one selection."""

    verdict: str
    ev: float | None
    ev_low: float | None
    ev_high: float | None
    fair_odds: float | None
    odds: float | None
    win: float | None
    push: float | None
    price_age_min: float | None
    price_sd: float | None
    books: int | None
    calibrated: bool
    interval_basis: str
    price_source: str
    version: str = VERSION
    method: str = METHOD

    @property
    def single_book(self) -> bool:
        """«Una sola casa»: fewer than ``MIN_BOOKS_TO_CONFIRM`` bookmakers (or none known)."""
        return self.books is None or self.books < MIN_BOOKS_TO_CONFIRM

    @property
    def confirms(self) -> bool:
        return self.verdict == CONFIRMED

    @property
    def why(self) -> str:
        return WHY[self.verdict]

    def as_json(self) -> dict[str, Any]:
        def r(x: float | None) -> float | None:
            return None if x is None else round(x, 6)

        return {"version": self.version, "method": self.method, "verdict": self.verdict, "confirms": self.confirms, "why": self.why,
                "ev": r(self.ev), "ev_low": r(self.ev_low), "ev_high": r(self.ev_high), "fair_odds": r(self.fair_odds),
                "odds": self.odds, "win": r(self.win), "push": r(self.push), "price_age_min": r(self.price_age_min),
                "price_sd": r(self.price_sd), "books": self.books, "single_book": self.single_book, "calibrated": self.calibrated,
                "interval_basis": self.interval_basis, "price_source": self.price_source}


def assess(chance: Chance | None, quote: Quote, *, at: datetime) -> ValueReading:
    """The value of one selection as of ``at`` (the moment of the decision). Pure and deterministic."""
    odds = quote.odds
    age = None if quote.price_at is None else (at - quote.price_at).total_seconds() / 60.0
    calibrated = chance is not None and chance.calibrated
    basis = "none" if chance is None else chance.interval_basis

    def reading(verdict: str, ev: float | None = None, low: float | None = None, high: float | None = None, fair: float | None = None,
                sd: float | None = None) -> ValueReading:
        return ValueReading(verdict, ev, low, high, fair, odds, None if chance is None else chance.win,
                            None if chance is None else chance.push, age, sd, quote.books, calibrated, basis, quote.source)

    if age is not None and age < 0:
        return reading(FUTURE_PRICE)
    if odds is None or not math.isfinite(odds) or odds <= 1.0:
        return reading(NO_PRICE, fair=None if chance is None else fair_odds(chance.win, chance.push))
    if chance is None:
        return reading(NO_PROBABILITY)
    ev = expected_value(chance.win, chance.push, odds)
    fair = fair_odds(chance.win, chance.push)
    if chance.low is None or chance.high is None:
        return reading(NO_INTERVAL, ev, fair=fair)
    if age is None:
        return reading(NO_AGE, ev, fair=fair)
    sd = price_sd(age)
    zp = NormalDist().inv_cdf((1.0 + chance.level) / 2.0)
    sd_low = (chance.win - min(chance.low, chance.win)) / zp
    sd_high = (max(chance.high, chance.win) - chance.win) / zp
    price_term = (chance.win * odds * sd) ** 2
    floor, ceiling = -(1.0 - chance.push), odds - 1.0
    ev_low = max(floor, ev - Z * math.sqrt((odds * sd_low) ** 2 + price_term))
    ev_high = min(ceiling, ev + Z * math.sqrt((odds * sd_high) ** 2 + price_term))
    ev_low, ev_high = min(ev_low, ev), max(ev_high, ev)
    if quote.books is None or quote.books < MIN_BOOKS_TO_CONFIRM:
        verdict = SINGLE_BOOK
    elif not chance.calibrated:
        verdict = UNCALIBRATED
    elif ev_low <= 0:
        verdict = NOT_POSITIVE
    else:
        verdict = CONFIRMED
    return reading(verdict, ev, ev_low, ev_high, fair, sd)
