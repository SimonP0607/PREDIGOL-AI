"""The common probability view in decision-v2 (``engine.CommonView``), in shadow: as a MEASUREMENT (plan PICKS, F3, option B) and, in the
replay's other measurement, as THE number the stages judge (plan Intelligence 2026, INT-A03, IA-053).

The only door between decision-v2 and the probability view (``fbi.forecasting``): the engine never imports it, it takes the plain values
built here. It reads ``models.predictions`` and the market's fresh consensus as of the decision's moment through ``market_reader.view_at``
- the same function that the Match Center's forecast is written from - and never the stored forecast: a forecast is not an input of a
decision (``tests/unit/test_forecast_isolation.py``).

Two uses, both in shadow. ``read`` gives the view of every selection; by default it only travels with the decision so that the replay can
measure the gap between decision-v2's own probability and the common one, and no stage reads it. ``judged`` sets it on the core's candidates
(``--probability common`` of the replay): the stages then judge the view's number - its model, its interval, its seal (calibrated by a
champion with a fresh price, or «Sin calibrar» with its reason) and its version - instead of the pick's (``engine.PROBABILITY_SOURCES``). A
selection the view does not cover keeps its own probability and says why (``NOT_IN_VIEW``, ``NO_READING``). Read-only.

Two versions of the view (plan 2026, AD-B05, IA-083). ``forecast-v1`` (the default, what the Match Center states): 1X2, total goals at 2.5
and both teams to score. ``forecast-v2`` (the single figure, ``fbi.forecasting.single_figure``, shadow): every goals market - the double
chance, draw-no-bet and the Asian lines that are events of the result from the 1X2 figure, every total and Asian line the models store, the
goals of each side - with the stable seal's price window. The version travels with each reading (``CommonView.version``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg

from fbi.decision.engine import COMMON, OWN, CommonView
from fbi.decision.families import Candidate
from fbi.forecasting.market_reader import figures_at, view_at
from fbi.forecasting.market_view import CALIBRATED, MARKETS, VERSION, MarketForecast
from fbi.forecasting.single_figure import MENU, FigureSet
from fbi.forecasting.single_figure import VERSION as FIGURE_VERSION
from fbi.intel.calibration import CalibrationState
from fbi.intel.decision import LINE_Q, Key

NOT_IN_VIEW: Final = "not_in_view"
"""Why a selection keeps its own probability: the view does not forecast its market and line (``market_view.MARKETS``: 1X2, total goals at
2.5 and both teams to score; not the handicaps, the double chance, the other lines nor the families)."""
VERSIONS: Final = (VERSION, FIGURE_VERSION)
"""The versions of the view decision-v2 can judge with: ``forecast-v1`` (the default) and ``forecast-v2`` (the single figure)."""
NO_READING: Final = "no_reading"
"""Why a selection keeps its own probability: the view forecasts its market but had no reading at the moment (no model priced every
outcome of it at one cut-off)."""


def readings(forecasts: Mapping[tuple[int, str, Decimal], MarketForecast]) -> dict[Key, CommonView]:
    """Every outcome of every market of the view, keyed like a candidate. Pure."""
    out: dict[Key, CommonView] = {}
    for (fixture_id, market_key, line), f in forecasts.items():
        for o in f.outcomes:
            out[(fixture_id, market_key, o.selection, line.quantize(LINE_Q))] = CommonView(
                o.p, o.p_model, f.model, f.calibration, f.basis, f.calibrator_id, o.lo, o.hi, f.data_cutoff_ts, o.market_as_of, VERSION,
                f.model_version_id)
    return out


def figure_readings(sets: Mapping[int, FigureSet]) -> dict[Key, CommonView]:
    """Every single figure (``forecast-v2``) of these matches, keyed like a candidate. Pure."""
    out: dict[Key, CommonView] = {}
    for fs in sets.values():
        for f in fs.figures.values():
            out[(f.fixture_id, f.market_key, f.selection, f.line.quantize(LINE_Q))] = CommonView(
                f.p, f.p_model, f.model, f.calibration, f.basis, f.calibrator_id, f.lo, f.hi, f.cutoff, f.price_as_of, f.version,
                f.model_version_id)
    return out


def read(conn: psycopg.Connection[Any], fixtures: Iterable[int], *, at: datetime, cal: CalibrationState, version: str = VERSION
         ) -> dict[Key, CommonView]:
    """The common view of these matches as of ``at``, by selection: ``forecast-v1``'s three markets (the default) or every single figure
    (``forecast-v2``)."""
    if version == FIGURE_VERSION:
        return figure_readings(figures_at(conn, sorted(set(fixtures)), at=at, cal=cal))
    if version != VERSION:
        raise ValueError(f"the view's version is one of {VERSIONS}, not {version!r}")
    return readings(view_at(conn, sorted(set(fixtures)), at=at, cal=cal))


def covered(key: Key, version: str = VERSION) -> bool:
    """Whether the view forecasts the selection's market and line. Pure."""
    if version == FIGURE_VERSION:
        return key[1] in MENU
    return (key[1], key[3]) in MARKETS


def fields(view: CommonView | None, key: Key, version: str = VERSION) -> dict[str, Any]:
    """The fields of a candidate's row that make the stages judge the view's number (``engine._number`` reads them), or that say why the
    selection keeps its own. Pure."""
    if view is None:
        return {"probability_source": OWN, "probability_missing": NO_READING if covered(key, version) else NOT_IN_VIEW}
    return {"probability_source": COMMON, "probability_missing": None, "common_p": view.p, "common_p_model": view.p_model,
            "common_model": view.model, "common_model_version_id": view.model_version_id, "common_calibrated": view.calibration == CALIBRATED,
            "common_calibration": view.calibration, "common_basis": view.basis, "common_calibrator_id": view.calibrator_id,
            "common_low": view.low, "common_high": view.high, "common_cutoff": view.cutoff, "common_version": view.version}


def judged(candidates: Sequence[Candidate], views: Mapping[Key, CommonView], *, family: str, version: str = VERSION) -> list[Candidate]:
    """The candidates of ``family`` with the view's number for the stages to judge (every model row of a selection takes the same fields: the
    view chose one model for the market); the candidates of other families as they are. Pure: nothing given is changed."""
    out: list[Candidate] = []
    for c in candidates:
        if c.family.name != family:
            out.append(c)
            continue
        found = fields(views.get(c.key), c.key, version)
        out.append(dataclasses.replace(c, models={m: {**row, **found} for m, row in c.models.items()}))
    return out
