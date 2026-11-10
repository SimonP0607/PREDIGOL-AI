"""The probability view of a market (plan PICKS, F3, option B): ONE way to say what PrediGol thinks of a market, for whoever needs it.

The Match Center states it (``fbi.forecasting.match_forecast`` writes it as ``forecast-v1``); decision-v2 (shadow) reads the same function
so that the probability it judges is the one a reader sees: the same model, a complete market that adds up to one, and a calibration
that is only applied where a champion calibrator exists AND the price it needs is fresh. Without a fresh price the view says so
(``UNCALIBRATED``, ``needs_price``) instead of dressing the model's number up.

It is PURE: it takes the rows it is given and the calibration state, and reads nothing (no database, no clock). It does not name the
forecast table and it is not a forecast: the stored forecast is written by ``match_forecast`` from this function's result, and nothing
that decides reads that table (``tests/unit/test_forecast_isolation.py``). It lives in ``fbi.forecasting`` and not in
``fbi.predictions`` because the latter's code IS the models' code (``fbi.core.version.MODEL_PACKAGES``): a file added there renews the
version of every model. Moving it out of ``match_forecast`` changed nothing it computes (the forecast's tests and ``input_hash`` are
the proof); do not change a number here without a new forecast version.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.models.scoring import MARKET_ROWS

VERSION: Final = "forecast-v1"

MAX_MARKET_AGE: Final = timedelta(hours=6)
"""A calibrator that takes the market's probability as an input gets the newest de-vigged consensus no older than this."""

FAMILIES: Final = {"1X2": "RESULT", "OU": "TOTAL_GOALS", "BTTS": "BOTH_TEAMS_SCORE"}
"""The forecast family of each market PrediGol forecasts. F10 adds goals by half, corners and cards."""

CALIBRATED: Final = "CALIBRATED"
UNCALIBRATED: Final = "UNCALIBRATED"

BASIS_CHAMPION: Final = "champion"
BASIS_NO_CHAMPION: Final = "no_champion"
BASIS_NEEDS_PRICE: Final = "needs_price"
BASIS_NOT_APPLICABLE: Final = "not_applicable"

_LO: Final = 1e-6


def _market_rows() -> dict[tuple[str, Decimal], tuple[str, ...]]:
    """(market, line) -> its outcomes, in the order the models price them."""
    out: dict[tuple[str, Decimal], list[str]] = defaultdict(list)
    for market, selection, line in MARKET_ROWS:
        out[(market, Decimal(str(line)))].append(selection)
    missing = {m for m, _ in out} - set(FAMILIES)
    assert not missing, f"a market the models price has no forecast family: {sorted(missing)}"
    return {k: tuple(v) for k, v in out.items()}


MARKETS: Final = _market_rows()
"""What is forecast: (market, line) -> outcomes. Derived from what the goal models price, so the two cannot drift apart."""


@dataclass(frozen=True, slots=True)
class Source:
    """One model's number for one outcome (a row of ``models.predictions``)."""

    model: str
    model_version_id: int
    data_cutoff_ts: datetime
    feature_set_hash: str
    p: float
    lo: float | None
    hi: float | None
    push: float


@dataclass(frozen=True, slots=True)
class Row:
    """A ``models.predictions`` row of the core markets, as the forecast reads it."""

    selection: str
    source: Source


@dataclass(frozen=True, slots=True)
class Outcome:
    selection: str
    p_model: float
    p: float
    lo: float | None
    hi: float | None
    push: float
    p_market: float | None = None
    market_as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class MarketForecast:
    """PrediGol's forecast of one market of one match: the outcomes (one model, one cut-off) and how they were calibrated."""

    fixture_id: int
    market_key: str
    line: Decimal
    model: str
    model_version_id: int
    data_cutoff_ts: datetime
    outcomes: tuple[Outcome, ...]
    calibration: str
    basis: str
    calibrator_id: int | None
    input_hash: str

    @property
    def family(self) -> str:
        return FAMILIES[self.market_key]


# ── the pure part ────────────────────────────────────────────────────────────────────────────────────────────────

def _clip(x: float) -> float:
    return min(max(x, _LO), 1 - _LO)


def _hash(parts: Sequence[object]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _calibrate(champion: Calibrator, outcomes: Sequence[Outcome]) -> tuple[list[Outcome], str] | None:
    """The champion applied to every outcome, the market scaled to add up to one. None when it cannot be applied."""
    cal: list[float] = []
    for o in outcomes:
        p = champion.apply(o.p_model, o.p_market)
        if p is None:
            return None
        cal.append(p)
    total = sum(cal)
    if total <= 0:
        return None
    out: list[Outcome] = []
    for o, p in zip(outcomes, cal, strict=True):
        ps = p / total
        lo = hi = None
        if o.lo is not None and o.hi is not None:
            cl = champion.apply(_clip(o.lo), o.p_market)
            ch = champion.apply(_clip(o.hi), o.p_market)
            if cl is not None and ch is not None:
                # a calibrator is monotone in the model's probability, but nothing here relies on the sign of its slope
                lo, hi = min(cl, ch) / total, max(cl, ch) / total
                lo, hi = min(lo, ps), max(hi, ps)
        out.append(Outcome(o.selection, o.p_model, ps, lo, hi, o.push, o.p_market, o.market_as_of))
    return out, BASIS_CHAMPION


def forecast_market(fixture_id: int, market_key: str, line: Decimal, models: dict[str, list[Row]],
                         cal: CalibrationState, market: dict[str, tuple[float, datetime]]) -> MarketForecast | None:
    """The forecast of one market, or None when no model priced every outcome of it.

    ``models``: model -> its rows for this market (every outcome, one cut-off); ``market``: outcome -> the newest de-vigged
    consensus probability and when it was captured, used only by a champion that takes the market as an input.
    """
    selections = MARKETS[(market_key, line)]
    complete: dict[str, list[Row]] = {}
    for name, rows in models.items():
        if sorted(r.selection for r in rows) != sorted(selections):
            continue
        # one version and one cut-off: the outcomes of a market are a set that adds up to one
        if len({(r.source.model_version_id, r.source.data_cutoff_ts) for r in rows}) != 1:
            continue
        complete[name] = rows
    if not complete:
        return None
    name = cal.primary_model(market_key, sorted(complete)) or sorted(complete)[0]
    by_sel = {r.selection: r.source for r in complete[name]}
    first = by_sel[selections[0]]
    raw = [Outcome(s, by_sel[s].p, by_sel[s].p, by_sel[s].lo, by_sel[s].hi, by_sel[s].push,
                   market.get(s, (None, None))[0], market.get(s, (None, None))[1]) for s in selections]
    champion = cal.champions.get((market_key, name))
    outcomes: tuple[Outcome, ...] = tuple(raw)
    calibration, basis, calibrator_id = UNCALIBRATED, BASIS_NO_CHAMPION, None
    if champion is not None:
        needs_market = champion.method == "logit2"
        if needs_market and any(o.p_market is None for o in raw):
            basis = BASIS_NEEDS_PRICE
        else:
            applied = _calibrate(champion, raw)
            if applied is None:
                basis = BASIS_NOT_APPLICABLE
            else:
                outcomes, basis = tuple(applied[0]), applied[1]
                calibration, calibrator_id = CALIBRATED, champion.id
    if calibration == UNCALIBRATED:
        # the market's probability is not part of an uncalibrated forecast: it is not stated, so it is not kept
        outcomes = tuple(Outcome(o.selection, o.p_model, o.p_model, o.lo, o.hi, o.push) for o in raw)
    digest = _hash([VERSION, fixture_id, market_key, str(line), name, first.model_version_id, first.data_cutoff_ts,
                    sorted((s, by_sel[s].feature_set_hash) for s in selections), calibrator_id, basis,
                    sorted((o.selection, None if o.p_market is None else round(o.p_market, 6)) for o in outcomes)])
    return MarketForecast(fixture_id, market_key, line, name, first.model_version_id, first.data_cutoff_ts, outcomes,
                          calibration, basis, calibrator_id, digest)


def most_likely(outcomes: Iterable[Outcome]) -> str | None:
    """The outcome with the highest probability (the first of them in the models' order if two tie)."""
    best: Outcome | None = None
    for o in outcomes:
        if best is None or o.p > best.p:
            best = o
    return None if best is None else best.selection
