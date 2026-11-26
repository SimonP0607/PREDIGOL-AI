"""The single figure of every goals market of a match (plan 2026, AD-B05, ``forecast-v2``), in SHADOW.

WHY. A reader saw three numbers for «menos de 2,5» in one brief, and a pick shows another number than the Match Center (Doc 1). Each
output computed its own: the page writes ``forecast-v1`` (three markets, each calibrated on its own), the decision layer calibrates selection
by selection (``decision-v1``: 13 of 34 matches with markets that do not add up, one 1X2 adding up to 0.626, measured by IA-074), a pick keeps
the model's raw number, and a text repeats whichever it was given. This module is the ONE place a probability of a goals market is made, so
that every output that asks for «the probability of X for this match, now, under this version» gets the same number, with its seal, its model,
its version, the moment of its price and an id a text can cite.

THE RULE (``forecast-v2``). For one match, from the models' newest stored numbers, the market's de-vigged consensus and the calibrators in
force (``fbi.intel.calibration``), all as of one moment:

1. The three markets the page states (1X2, total goals at 2.5, both teams to score) are ``market_view.forecast_market`` itself: the same
   model choice, the same calibration and the same numbers as ``forecast-v1`` given the same prices - a test holds them equal to six places.
   The price window is the stable seal's (``seal-v1``, AD-B03: the newest consensus of the last 4 days), so the seal changes only when its
   cause does; with the 6-hour window of ``forecast-v1`` the function returns ``forecast-v1``'s numbers exactly.
2. ONE EVENT, ONE FIGURE. Every selection that is an event of the result is the 1X2 figure, added up: the double chance (1X, X2, 12),
   draw-no-bet, and the Asian handicap at -0.5, -0.25, 0, +0.25 and +0.5 (a quarter line is half the stake on each neighbouring line). They
   carry the 1X2's seal, model and calibrator: a calibrated «Local -0,5» is the calibrated «Local». No other calibrator is applied to them
   (the double chance has none of its own, IA-035; an Asian champion would give a second number to the same event).
3. Every other line of total goals and of the Asian handicap is a complete pair (Over/Under at a line; Home at l with Away at -l). Its
   model is the market's specialised one (``CalibrationState.primary_model``), its number the model's stored row - or, for a line the
   model did not store, its score matrix (``fbi.forecasting.score_matrix``, rebuilt from the model's seven stored rows). The market's
   champion is applied as ``forecast-v1`` applies it - to each side, with the newest consensus of that side within the window - and the pair
   is scaled so that what it wins and returns adds up to one. Without a champion, or without a price for a ``logit2``, the model's own number
   is stated and sealed ``sin_calibrar`` with its reason.
4. The goals of one side (``OU_HOME``, ``OU_AWAY``) and the European handicap (``EH``) come from the same matrix; no calibrator exists for
   them, so they are ``sin_calibrar`` (``no_champion``).
5. Anything else - another market, a family (corners, cards, halves: AD-B07), a line no model can price - has no figure and says why
   (``not_in_view`` / ``no_reading``): an output never makes up a number for it.

WHAT IT IS NOT. It is not coherent across markets by construction once calibrated: a calibrated over 2.5 beside a raw over 3.5 can break the
ladder, because the calibrators are fitted market by market (the coherent calibration of IA-036 was rejected). ``score_matrix.coherence``
over a set says where; the report (``scripts/ia_single_figure.py``) counts it in production. It changes nothing a reader sees: no route serves
it to a reader, the page keeps ``forecast-v1``, and decision-v2 judges it only with ``--probability common --view-version forecast-v2``.
No language model computes, corrects or chooses a number: a text may only repeat a figure it cites (``fbi.forecasting.figure_text``).

PURE: rows in, figures out - no database and no clock (``fbi.forecasting.market_reader.figures_at`` reads the rows).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from fbi.forecasting import figure_base
from fbi.forecasting import score_matrix as sm
from fbi.forecasting.market_view import (
    BASIS_CHAMPION,
    BASIS_NEEDS_PRICE,
    BASIS_NO_CHAMPION,
    BASIS_NOT_APPLICABLE,
    CALIBRATED,
    MARKETS,
    UNCALIBRATED,
    MarketForecast,
    Row,
    Source,
    forecast_market,
)
from fbi.forecasting.seal import CALIBRADA, SIN_CALIBRAR, STABLE_MARKET_AGE, Label
from fbi.intel.calibration import CalibrationState
from fbi.models.lines import LineOutcome

VERSION: Final = "forecast-v2"
MARKET_AGE: Final[timedelta] = STABLE_MARKET_AGE
"""The newest consensus a ``logit2`` champion may use: the stable seal's window (``seal-v1``)."""

SOURCE_STORED: Final = "stored"
"""The model's own stored row (``models.predictions``)."""
SOURCE_MATRIX: Final = "matrix"
"""The model's score matrix, rebuilt from its seven stored rows (``score_matrix.invert``)."""
SOURCE_RESULT: Final = "result"
"""An event of the result: the 1X2 figure, added up."""

NOT_IN_VIEW: Final = "not_in_view"
"""Why a selection has no figure: its market is not one of ``MENU`` (a family, another period, a player)."""
NO_READING: Final = "no_reading"
"""Why a selection has no figure: its market is in ``MENU`` but no model priced it at this moment."""

MENU: Final = frozenset({"1X2", "DC", "DNB", "OU", "BTTS", "AH", "OU_HOME", "OU_AWAY", "EH"})
"""The markets the single figure covers (the keys of ``fbi.market.catalogue``; the families wait for AD-B07)."""

RESULT_AH_LINES: Final = tuple(Decimal(q) / 4 for q in range(-2, 3))
"""-0.5, -0.25, 0, +0.25, +0.5: the Asian lines that are events of the result (with the line of the side bet on)."""
TEAM_LINES: Final = tuple(Decimal(n) + Decimal("0.5") for n in range(4))
"""0.5, 1.5, 2.5, 3.5: the goals of one side stated by default (any other line can be asked for)."""
CORE_MARKETS: Final = frozenset(m for m, _ in MARKETS)

PriceKey = tuple[str, str, Decimal]
"""(market, selection, the selection's own line)."""


def line_of(x: Decimal | float | str | int) -> Decimal:
    """A line as a key: two decimals, no negative zero (the decision layer's ``LINE_Q``)."""
    return (Decimal(str(x)) + 0).quantize(Decimal("0.01"))


def key_of(market: str, selection: str, line: Decimal | float | str | int) -> PriceKey:
    return str(market), str(selection), line_of(line)


@dataclass(frozen=True, slots=True)
class Figure:
    """The single figure of one selection: the probability that it wins (``p``) and that it returns the stake (``push``), what it was made
    from and its seal. ``reading_id`` is what a text cites (``figure_text``)."""

    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    p: float
    push: float
    lo: float | None
    hi: float | None
    p_model: float
    model: str
    model_version_id: int
    cutoff: datetime
    calibration: str
    """``CALIBRATED`` (a champion applied) or ``UNCALIBRATED`` (the model's own number; ``basis`` says why)."""
    basis: str
    calibrator_id: int | None
    price_as_of: datetime | None
    """When the oldest consensus the calibration used was captured (None without a calibration)."""
    source: str
    set_hash: str
    """The fingerprint of the inputs of the market set the figure belongs to."""
    version: str = VERSION
    base: figure_base.Base = figure_base.UNCALIBRATED_BASE
    """What the stated figure rests on and the calibrator's weights (``fbi.forecasting.figure_base``)."""

    @property
    def label(self) -> Label:
        return CALIBRADA if self.calibration == CALIBRATED else SIN_CALIBRAR

    @property
    def key(self) -> PriceKey:
        return key_of(self.market_key, self.selection, self.line)

    @property
    def reading_id(self) -> str:
        return reading_id(self.version, self.fixture_id, self.key, self.set_hash)

    def as_json(self) -> dict[str, object]:
        return {"fixture_id": self.fixture_id, "market": self.market_key, "selection": self.selection, "line": float(self.line),
                "p": round(self.p, 6), "push": round(self.push, 6), "interval": None if self.lo is None or self.hi is None else
                [round(self.lo, 6), round(self.hi, 6)], "p_model": round(self.p_model, 6), "model": self.model,
                "model_version_id": self.model_version_id, "cutoff": self.cutoff.isoformat(), "seal": self.label,
                "calibration": self.calibration, "basis": self.basis, "calibrator_id": self.calibrator_id,
                "price_as_of": None if self.price_as_of is None else self.price_as_of.isoformat(), "source": self.source,
                "version": self.version, "reading_id": self.reading_id, "base": self.base.as_json()}


def reading_id(version: str, fixture_id: int, key: PriceKey, set_hash: str) -> str:
    """Twelve hex characters: the version, the match, the selection and its set's inputs. Another version, or other inputs, is another id."""
    m, s, line = key
    return _hash([version, fixture_id, m, s, str(line_of(line)), set_hash])[:12]


@dataclass(frozen=True, slots=True)
class FigureSet:
    """Every single figure of one match, as of one moment, and what could not be priced."""

    fixture_id: int
    figures: Mapping[PriceKey, Figure]
    matrices: Mapping[str, sm.Inversion | None] = field(default_factory=dict)
    """Each goal model's recovered parameters (None: its rows could not be inverted within tolerance)."""
    version: str = VERSION

    def get(self, market: str, selection: str, line: Decimal | float | str | int) -> Figure | None:
        return self.figures.get(key_of(market, selection, line))

    def why_none(self, market: str, selection: str, line: Decimal | float | str | int) -> str | None:
        """None when the selection has a figure; otherwise why not (``NOT_IN_VIEW`` or ``NO_READING``)."""
        if self.get(market, selection, line) is not None:
            return None
        return NO_READING if market in MENU else NOT_IN_VIEW

    def by_reading(self) -> dict[str, Figure]:
        return {f.reading_id: f for f in self.figures.values()}

    def prices(self) -> dict[PriceKey, LineOutcome]:
        """The figures as (win, push), the shape ``score_matrix.coherence`` checks."""
        return {k: LineOutcome(f.p, f.push) for k, f in self.figures.items()}


# ── the pure part ────────────────────────────────────────────────────────────────────────────────────────────────

def _hash(parts: Sequence[object]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _clip(x: float) -> float:
    return min(max(x, 1e-6), 1 - 1e-6)


Numbers = Mapping[str, Mapping[PriceKey, Source]]
"""model -> its newest stored rows (one version, one cut-off), by (market, selection, line)."""
Prices = Mapping[PriceKey, tuple[float, datetime]]
"""(market, selection, line) -> the newest de-vigged consensus within the window and when it was captured."""


@dataclass(frozen=True, slots=True)
class _Side:
    selection: str
    line: Decimal
    win: float
    push: float
    lo: float | None
    hi: float | None


def _core(fixture_id: int, numbers: Numbers, cal: CalibrationState, prices: Prices) -> dict[tuple[str, Decimal], MarketForecast]:
    """``forecast-v1``'s three markets, through ``forecast_market`` itself."""
    out: dict[tuple[str, Decimal], MarketForecast] = {}
    for (market, line), selections in sorted(MARKETS.items()):
        models: dict[str, list[Row]] = {}
        for name, rows in numbers.items():
            found = [Row(s, rows[key_of(market, s, line)]) for s in selections if key_of(market, s, line) in rows]
            if found:
                models[name] = found
        market_prices = {s: prices[key_of(market, s, line)] for s in selections if key_of(market, s, line) in prices}
        f = forecast_market(fixture_id, market, line, models, cal, market_prices, version=VERSION)
        if f is not None:
            out[(market, line)] = f
    return out


def _figures_of(f: MarketForecast) -> list[Figure]:
    used = [o.market_as_of for o in f.outcomes if o.market_as_of is not None]
    as_of = min(used) if f.calibration == CALIBRATED and used else None
    return [Figure(f.fixture_id, f.market_key, o.selection, line_of(f.line), o.p, o.push, o.lo, o.hi, o.p_model, f.model, f.model_version_id,
                   f.data_cutoff_ts, f.calibration, f.basis, f.calibrator_id, as_of, SOURCE_STORED, f.input_hash, base=f.base)
            for o in f.outcomes]


def _result_events(x: MarketForecast) -> list[Figure]:
    """The selections that are events of the result, from the 1X2 figure: one event, one figure."""
    p = {o.selection: o for o in x.outcomes}
    h, d, a = p["Home"].p, p["Draw"].p, p["Away"].p
    hm, dm, am = p["Home"].p_model, p["Draw"].p_model, p["Away"].p_model
    used = [o.market_as_of for o in x.outcomes if o.market_as_of is not None]
    as_of = min(used) if x.calibration == CALIBRATED and used else None
    tag = _hash([x.input_hash, SOURCE_RESULT])
    zero, quarter, half = Decimal(0), Decimal("0.25"), Decimal("0.5")
    events: list[tuple[str, str, Decimal, float, float, float, float]] = [  # market, selection, line, win, push, raw win, raw push
        ("DC", "1X", zero, h + d, 0.0, hm + dm, 0.0), ("DC", "X2", zero, d + a, 0.0, dm + am, 0.0),
        ("DC", "12", zero, h + a, 0.0, hm + am, 0.0),
        ("DNB", "Home", zero, h, d, hm, dm), ("DNB", "Away", zero, a, d, am, dm),
        ("AH", "Home", zero, h, d, hm, dm), ("AH", "Away", zero, a, d, am, dm),
        ("AH", "Home", -half, h, 0.0, hm, 0.0), ("AH", "Away", half, d + a, 0.0, dm + am, 0.0),
        ("AH", "Away", -half, a, 0.0, am, 0.0), ("AH", "Home", half, h + d, 0.0, hm + dm, 0.0),
        # a quarter line: half the stake at each neighbour (Home -0.25 = Home 0 and Home -0.5)
        ("AH", "Home", -quarter, h, d / 2, hm, dm / 2), ("AH", "Away", quarter, a + d / 2, d / 2, am + dm / 2, dm / 2),
        ("AH", "Home", quarter, h + d / 2, d / 2, hm + dm / 2, dm / 2), ("AH", "Away", -quarter, a, d / 2, am, dm / 2),
    ]
    return [Figure(x.fixture_id, m, s, line_of(line), win, push, None, None, raw, x.model, x.model_version_id, x.data_cutoff_ts,
                   x.calibration, x.basis, x.calibrator_id, as_of, SOURCE_RESULT, tag, base=x.base)
            for m, s, line, win, push, raw, _ in events]


def _pair(market: str, line: Decimal) -> tuple[tuple[str, Decimal], ...]:
    """The complete set of one line: what each side is, with its own line."""
    if market in ("OU", "OU_HOME", "OU_AWAY"):
        return (("Over", line), ("Under", line))
    if market == "AH":
        return (("Home", line), ("Away", line_of(-line)))
    if market == "EH":
        return (("Home", line), ("Draw", line), ("Away", line))
    raise ValueError(f"not a market of lines: {market}")


def _matrix_sides(prices: Mapping[PriceKey, LineOutcome], market: str, line: Decimal) -> list[_Side] | None:
    sides: list[_Side] = []
    for sel, own in _pair(market, line):
        o = prices.get(key_of(market, sel, own))
        if o is None:
            return None
        sides.append(_Side(sel, own, o.win, o.push, None, None))
    return sides


def _stored_sides(rows: Mapping[PriceKey, Source], market: str, line: Decimal) -> list[_Side] | None:
    sides: list[_Side] = []
    for sel, own in _pair(market, line):
        src = rows.get(key_of(market, sel, own))
        if src is None:
            return None
        sides.append(_Side(sel, own, src.p, src.push, src.lo, src.hi))
    return sides


def _calibrated(market: str, model: str, sides: list[_Side], cal: CalibrationState, prices: Prices
                ) -> tuple[list[tuple[float, float | None, float | None]], str, int | None, datetime | None]:
    """(p, lo, hi) of each side, the basis, the calibrator and the moment of the oldest price used - the rule of ``forecast-v1`` for one
    set: the champion applied to each side with its own price, the set scaled so that it wins and returns one."""
    raw = [(s.win, s.lo, s.hi) for s in sides]
    champion = cal.champions.get((market, model))
    if champion is None:
        return raw, BASIS_NO_CHAMPION, None, None
    market_p = [prices.get(key_of(market, s.selection, s.line)) for s in sides]
    if champion.method == "logit2" and any(m is None for m in market_p):
        return raw, BASIS_NEEDS_PRICE, None, None
    applied: list[float] = []
    for s, m in zip(sides, market_p, strict=True):
        v = champion.apply(s.win, None if m is None else m[0])
        if v is None:
            return raw, BASIS_NOT_APPLICABLE, None, None
        applied.append(v)
    total = sum(applied)
    target = 1.0 - sides[0].push
    if total <= 0 or target <= 0:
        return raw, BASIS_NOT_APPLICABLE, None, None
    scale = target / total
    out: list[tuple[float, float | None, float | None]] = []
    for s, v, m in zip(sides, applied, market_p, strict=True):
        p = v * scale
        lo = hi = None
        if s.lo is not None and s.hi is not None:
            mp = None if m is None else m[0]
            cl, ch = champion.apply(_clip(s.lo), mp), champion.apply(_clip(s.hi), mp)
            if cl is not None and ch is not None:
                lo, hi = min(min(cl, ch) * scale, p), max(max(cl, ch) * scale, p)
        out.append((p, lo, hi))
    used = [m[1] for m in market_p if m is not None]
    return out, BASIS_CHAMPION, champion.id, min(used) if used else None


def _line_set(fixture_id: int, market: str, line: Decimal, numbers: Numbers, matrices: Mapping[str, Mapping[PriceKey, LineOutcome]],
              cal: CalibrationState, prices: Prices) -> list[Figure]:
    """One complete line of a market of lines, from its specialised model: its stored rows, else its matrix."""
    candidates: dict[str, tuple[list[_Side], str, Source | None]] = {}
    for name, rows in numbers.items():
        stored = _stored_sides(rows, market, line)
        if stored is not None:
            candidates[name] = (stored, SOURCE_STORED, rows[key_of(market, stored[0].selection, stored[0].line)])
            continue
        if name in matrices:
            from_matrix = _matrix_sides(matrices[name], market, line)
            if from_matrix is not None:
                any_row = next(iter(rows.values()))
                candidates[name] = (from_matrix, SOURCE_MATRIX, any_row)
    if not candidates:
        return []
    name = cal.primary_model(market, sorted(candidates)) or sorted(candidates)[0]
    sides, source, src = candidates[name]
    assert src is not None
    numbers_out, basis, calibrator_id, as_of = _calibrated(market, name, sides, cal, prices)
    calibration = CALIBRATED if basis == BASIS_CHAMPION else UNCALIBRATED
    base = figure_base.of_champion(cal.champions.get((market, name)), applied=calibration == CALIBRATED)
    used = [prices.get(key_of(market, s.selection, s.line)) for s in sides] if calibration == CALIBRATED else []
    digest = _hash([VERSION, fixture_id, market, str(line), name, src.model_version_id, src.data_cutoff_ts, source, src.feature_set_hash,
                    calibrator_id, basis, sorted((s.selection, str(s.line), round(s.win, 6), round(s.push, 6)) for s in sides),
                    sorted((str(u[1]), round(u[0], 6)) for u in used if u is not None)])
    return [Figure(fixture_id, market, s.selection, line_of(s.line), p, s.push, lo, hi, s.win, name, src.model_version_id, src.data_cutoff_ts,
                   calibration, basis, calibrator_id, as_of, source, digest, base=base)
            for s, (p, lo, hi) in zip(sides, numbers_out, strict=True)]


def _lines_of(market: str, numbers: Numbers, extra: Iterable[PriceKey]) -> set[Decimal]:
    """The lines of a market of lines to state: every line a model stored (where the market is quoted) and every line asked for. An Asian
    line is named by its HOME side."""
    found: set[Decimal] = set()
    keys = [k for rows in numbers.values() for k in rows] + [key_of(*k) for k in extra]
    for m, s, line in keys:
        if m != market:
            continue
        found.add(line_of(-line) if market == "AH" and s == "Away" else line_of(line))
    return found


def figure_set(fixture_id: int, numbers: Numbers, cal: CalibrationState, prices: Prices, *,
               extra: Iterable[PriceKey] = (), team_lines: Iterable[Decimal] = TEAM_LINES,
               eh_lines: Iterable[Decimal] = sm.EH_LINES) -> FigureSet:
    """Every single figure of one match. ``numbers``: each model's newest stored rows; ``prices``: the newest consensus of each outcome within
    the window the caller chose (``MARKET_AGE`` for ``forecast-v2``); ``extra``: selections to state even if no model stored their line (an
    Asian or total line a decision asks about), priced from the matrix."""
    extra = list(extra)
    figures: dict[PriceKey, Figure] = {}
    core = _core(fixture_id, numbers, cal, prices)
    for f in core.values():
        for fig in _figures_of(f):
            figures[fig.key] = fig
    result = core.get(("1X2", Decimal("0.0")))
    if result is not None:
        for fig in _result_events(result):
            figures[fig.key] = fig

    inversions: dict[str, sm.Inversion | None] = {}
    matrices: dict[str, dict[PriceKey, LineOutcome]] = {}
    for name in sorted(numbers):
        if name not in sm.GOAL_MODELS:
            continue
        rows = numbers[name]
        any_row = next(iter(rows.values()), None)
        inv = sm.invert({k: v.p for k, v in rows.items()}, name, model_version_id=None if any_row is None else any_row.model_version_id)
        inversions[name] = inv
        if inv is None:
            continue
        ou = _lines_of("OU", numbers, extra)
        ah = _lines_of("AH", numbers, extra)
        team = {line_of(x) for x in team_lines} | _lines_of("OU_HOME", numbers, extra) | _lines_of("OU_AWAY", numbers, extra)
        eh = {line_of(x) for x in eh_lines} | _lines_of("EH", numbers, extra)
        derived = sm.derive(sm.build(inv.params), ou_lines=ou, ah_lines=ah, team_lines=team, eh_lines=[x for x in eh if x != 0])
        matrices[name] = {key_of(*k): v for k, v in derived.items()}

    for market in ("OU", "AH", "OU_HOME", "OU_AWAY", "EH"):
        lines = _lines_of(market, numbers, extra)
        if market in ("OU_HOME", "OU_AWAY"):
            lines |= {line_of(x) for x in team_lines}
        if market == "EH":
            lines |= {line_of(x) for x in eh_lines}
            lines.discard(Decimal("0.00"))
        for line in sorted(lines):
            if market == "OU" and (market, line) in {(m, line_of(ln)) for m, ln in MARKETS}:
                continue  # the page's own line: already stated, through forecast_market
            if market == "AH" and result is not None and line in {line_of(x) for x in RESULT_AH_LINES}:
                continue  # an event of the result: the 1X2 figure
            for fig in _line_set(fixture_id, market, line, numbers, matrices, cal, prices):
                figures[fig.key] = fig
    return FigureSet(fixture_id, figures, inversions)
