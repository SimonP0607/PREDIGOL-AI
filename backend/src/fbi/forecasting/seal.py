"""The calibration seal of a forecast, made stable (plan 2026, AD-B03, ``seal-v1``), in SHADOW.

WHAT WAS WRONG (measured in production, 16-nov-2026, read-only; ``docs/owner/IA_073_SELLO_DE_CALIBRACION.md``). Every champion
calibrator in force is a ``logit2``: it takes the de-vigged market as an input, and ``forecast-v1`` only accepts a consensus no older than
``MAX_MARKET_AGE`` (6 h). The consensus of a match is captured a few times a day (often once, around 16:30 UTC, days before the match), so
six hours after a capture the next pass of the pipeline finds no "fresh" price and writes the SAME model number as ``UNCALIBRATED``
(``needs_price``); the next capture turns it ``CALIBRATED`` again. The champion, the model and its version did not change: only the age of
the price crossed six hours. In seven days 76 % of the markets forecast flipped at least once, all of them between ``champion`` and
``needs_price`` and none with a change of model. The seal said more about the clock than about the calibration.

THE RULE (``seal-v1``). A number is ``calibrada`` when, and only when, its (market, model) has a CHAMPION calibrator in force (validated
by ``calib-gate-v1`` and not retired) that can be applied - for a ``logit2``, with the newest de-vigged consensus captured within
``STABLE_MARKET_AGE`` before the moment, whatever its age inside that window. Otherwise it is ``sin_calibrar`` with its reason:

    no_champion ......... its (market, model) has no champion in force
    needs_price ......... the champion needs a market price and there has been none within the window (the market had not opened yet)
    not_applicable ...... the champion cannot be applied to these numbers (a probability of 0 or 1)

So the seal of a number changes only when its CAUSE changes - a champion promoted or retired, the first price of the match, or (rarely) a
price that grew older than the window - and never because of the order or the hour of the passes. The age of the price used is kept with
the reading (``market_as_of``), so a reader can say "calibrated against the price of 14:30". The window is the forecast's own horizon
(``fbi.predictions.forecast.HORIZON``, 4 days): a price captured inside the time the match has been forecast at all. Why an older price is
acceptable: between two captures of the same consensus the de-vigged probability moved 0.7-1.1 points on average whatever the gap (1 to 48
hours, n = 1,443, 7 days), so a price of yesterday says almost what a price of an hour ago says; the protocol ``AD-B03`` (``fbi.research.
protocol``) measures, before anything is promoted, whether the calibrated number with an aged price still beats the raw model.

WHAT IT DOES NOT CHANGE. ``forecast-v1`` - what the page, the AI's packet and every reader show - is not touched: same rule, same numbers,
same rows. The stable seal is written beside it under its own version (``SHADOW_VERSION``) that no reader selects, so that its passes can be
compared with ``forecast-v1``'s and the owner can decide (AD-B05 reads it). No calibrator is fitted, promoted or retired here.
Pure: no database, no clock (``fbi.forecasting.match_forecast`` writes the shadow version from these constants).
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final, Literal

from fbi.forecasting.market_view import (
    BASIS_CHAMPION,
    BASIS_NEEDS_PRICE,
    BASIS_NO_CHAMPION,
    BASIS_NOT_APPLICABLE,
    CALIBRATED,
    MarketForecast,
)

RULE: Final = "seal-v1"
SHADOW_VERSION: Final = "forecast-v1-seal"
"""The version of the forecast table the stable seal is written under, in shadow: ``forecast-v1`` with ``seal-v1``. No reader
selects it (every reader names ``forecast-v1``, ``family-v1`` or a version of its own)."""

STABLE_MARKET_AGE: Final = timedelta(days=4)
"""How old the newest consensus may be for a ``logit2`` champion to apply: the forecast horizon (a test holds the two equal)."""

SWITCH: Final = "FBI_FORECAST_SEAL"
"""``shadow`` (the default in code): the pipeline also writes ``SHADOW_VERSION``; ``off``: it does not. Nothing else reads it."""
MODES: Final = ("off", "shadow")

Label = Literal["calibrada", "sin_calibrar"]
CALIBRADA: Final[Label] = "calibrada"
SIN_CALIBRAR: Final[Label] = "sin_calibrar"

REASONS: Final = {
    BASIS_CHAMPION: "calibrador campeón vigente",
    BASIS_NO_CHAMPION: "sin calibrador validado para este mercado y modelo",
    BASIS_NEEDS_PRICE: "el calibrador necesita el precio del mercado y aún no hay ninguno",
    BASIS_NOT_APPLICABLE: "el calibrador no se puede aplicar a estos números",
}
"""The reason of each seal, in the words a reader is told (Spanish: the product's language)."""


@dataclass(frozen=True, slots=True)
class Seal:
    label: Label
    basis: str
    calibrator_id: int | None
    price_as_of: datetime | None
    """When the oldest consensus the calibration used was captured (None without a calibration)."""

    def price_age(self, at: datetime) -> timedelta | None:
        return None if self.price_as_of is None else at - self.price_as_of

    @property
    def reason(self) -> str:
        return REASONS.get(self.basis, self.basis)


def seal_of(f: MarketForecast) -> Seal:
    """The seal of one market forecast, as its calibration says."""
    if f.calibration == CALIBRATED:
        used = [o.market_as_of for o in f.outcomes if o.market_as_of is not None]
        return Seal(CALIBRADA, f.basis, f.calibrator_id, min(used) if used else None)
    return Seal(SIN_CALIBRAR, f.basis, None, None)


def label_of(calibration: str) -> Label:
    """``CALIBRATED`` / ``UNCALIBRATED`` of the stored rows, in the contract's words (``fbi.api.contracts.intelligence.vocab``)."""
    return CALIBRADA if calibration == CALIBRATED else SIN_CALIBRAR


def mode(env: Mapping[str, str]) -> str:
    """The switch's mode; anything that is not a known mode is the default (``shadow``): an unknown value never turns a thing on."""
    value = env.get(SWITCH, "shadow").strip().lower()
    return value if value in MODES else "shadow"


# -- the check of repetition: a seal changes only when its cause does --------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Reading:
    """One pass's seal of one number, with the cause it is owed to: (the champion in force or None, whether a price within the window
    existed). The cause is read from the state of the world at the pass, independently of the seal that was written."""

    at: datetime
    label: Label
    cause: Hashable


@dataclass(frozen=True, slots=True)
class Change:
    at: datetime
    before: Label
    after: Label
    cause_changed: bool


def changes(readings: Sequence[Reading]) -> list[Change]:
    """Every change of seal between consecutive passes (in time order), and whether its cause changed with it."""
    ordered = sorted(readings, key=lambda r: r.at)
    out: list[Change] = []
    for prev, cur in pairwise(ordered):
        if prev.label != cur.label:
            out.append(Change(cur.at, prev.label, cur.label, prev.cause != cur.cause))
    return out


def unexplained(readings: Sequence[Reading]) -> int:
    """How many seal changes came without a change of cause: the closing criterion of AD-B03 asks for 0."""
    return sum(1 for c in changes(readings) if not c.cause_changed)
