"""The common probability view as a MEASUREMENT of decision-v2 (``engine.CommonView``), in shadow (plan PICKS, F3, option B).

The only door between decision-v2 and the probability view (``fbi.forecasting``): the engine never imports it, it takes the plain values
built here. It reads ``models.predictions`` and the market's fresh consensus as of the decision's moment through ``market_reader.view_at``
- the same function that the Match Center's forecast is written from - and never the stored forecast: a forecast is not an input of a
decision (``tests/unit/test_forecast_isolation.py``). Nothing in the engine's stages reads the result; it only travels with the decision so
that the replay can measure the gap between decision-v2's own probability and the common one. Read-only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from fbi.decision.engine import CommonView
from fbi.forecasting.market_reader import view_at
from fbi.forecasting.market_view import VERSION, MarketForecast
from fbi.intel.calibration import CalibrationState
from fbi.intel.decision import LINE_Q, Key


def readings(forecasts: Mapping[tuple[int, str, Decimal], MarketForecast]) -> dict[Key, CommonView]:
    """Every outcome of every market of the view, keyed like a candidate. Pure."""
    out: dict[Key, CommonView] = {}
    for (fixture_id, market_key, line), f in forecasts.items():
        for o in f.outcomes:
            out[(fixture_id, market_key, o.selection, line.quantize(LINE_Q))] = CommonView(
                o.p, o.p_model, f.model, f.calibration, f.basis, f.calibrator_id, o.lo, o.hi, f.data_cutoff_ts, o.market_as_of, VERSION)
    return out


def read(conn: psycopg.Connection[Any], fixtures: Iterable[int], *, at: datetime, cal: CalibrationState) -> dict[Key, CommonView]:
    """The common view of these matches' core markets as of ``at``, by selection."""
    return readings(view_at(conn, sorted(set(fixtures)), at=at, cal=cal))
