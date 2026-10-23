"""PrediGol's forecast of a match, read for the product and for the Admin Console's preview (plan F5). Reading only.

The forecast is what the worker wrote to ``models.match_forecasts`` (``fbi.forecasting.match_forecast``): a probability, the
interval the model measured around it and whether a champion calibrator was applied. This module only lays it out. It never
computes a probability, never reads a price to make one, and never turns a forecast into a value or a pick.

Who sees what. A user sees the forecast and nothing else - no odds, no edge, no pick - and only once the owner has decided that
users see it (``FBI_FORECAST_USERS``; off until then). The Admin Console's preview (``preview=shadow``) sees the forecast with
its fair odds beside what the decision layer said about the same match (``value``, which needs a price) and the picks frozen for
it (``picks``), so that the three can be told apart.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.api.contracts.forecast import (
    ForecastMarket,
    ForecastOutcome,
    MatchForecast,
    PickRow,
    ValueRow,
)
from fbi.api.envelope import DataStatus, Envelope, Section, ok, section, unavailable
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now
from fbi.core.env import environment

VERSION: Final = "forecast-v1"
"""The forecast the worker writes (``fbi.forecasting.match_forecast.VERSION``; a test holds the two equal)."""
NOT_FIT: Final = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
"""The competition data classes the worker does not forecast (``match_forecast.NOT_FIT``; a test holds them equal)."""
USERS_SWITCH: Final = "FBI_FORECAST_USERS"
"""``FBI_FORECAST_USERS=1`` lets every signed-in account see the forecast. Off until the owner decides (plan §22): the
Admin Console's preview does not depend on it. The API needs a restart to read it."""
MARKET_ORDER: Final = {"1X2": 0, "OU": 1, "BTTS": 2}
MAX_VALUE_ROWS: Final = 200

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group,
       (SELECT s.class FROM analytics.competition_data_scores s
         WHERE s.competition_season_id = f.competition_season_id) AS data_class,
       EXISTS (SELECT 1 FROM analytics.fixture_validation v WHERE v.fixture_id = f.id AND v.state = 'QUARANTINED')
              AS quarantined
  FROM core.fixtures f WHERE f.id = %(f)s
"""

FORECAST_SQL = """
WITH last AS (
    SELECT market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = %(f)s AND version = %(version)s AND known_at <= %(at)s
     GROUP BY 1, 2
)
SELECT x.market_key, x.line, x.family, x.selection, x.model_name, x.calibration, x.basis, x.known_at, x.data_cutoff_ts,
       x.p, x.p_lo, x.p_hi, x.p_model
  FROM models.match_forecasts x JOIN last l ON l.market_key = x.market_key AND l.line = x.line AND l.k = x.known_at
 WHERE x.fixture_id = %(f)s AND x.version = %(version)s
 ORDER BY x.market_key, x.line, x.id
"""
"""The newest set of each market known by ``at``: all the outcomes of a market are written together."""

VALUE_SQL = """
SELECT DISTINCT ON (market_key, selection, line) market_key, selection, line, state, odds, p_cal, p_market, edge_cal,
       ev_cal, reasons, known_at
  FROM intel.decisions WHERE fixture_id = %(f)s
 ORDER BY market_key, selection, line, known_at DESC, id DESC
 LIMIT %(limit)s
"""

PICKS_SQL = """
SELECT id, market_key, selection, line, status, mode, market_odds, p_calibrated
  FROM picks.picks WHERE fixture_id = %(f)s ORDER BY id
"""


def users_may_see() -> bool:
    return environment().get(USERS_SWITCH, "0").strip().lower() in {"1", "on", "true", "yes"}


def _fair_odds(p: Decimal) -> Decimal | None:
    return (Decimal(1) / p).quantize(Decimal("0.01")) if p > 0 else None


def _markets(rows: list[dict[str, Any]], *, preview: bool) -> list[ForecastMarket]:
    grouped: dict[tuple[str, Decimal], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((str(r["market_key"]), Decimal(r["line"])), []).append(r)
    out: list[ForecastMarket] = []
    for (market, line), rs in sorted(grouped.items(), key=lambda kv: (MARKET_ORDER.get(kv[0][0], 99), kv[0][1])):
        best = max(rs, key=lambda r: r["p"])  # the first of them if two tie: ``max`` keeps the first maximum
        first = rs[0]
        out.append(ForecastMarket(
            market=market, line=line, family=str(first["family"]), model=str(first["model_name"]),
            calibration=first["calibration"], basis=first["basis"], known_at=first["known_at"],
            data_cutoff_at=first["data_cutoff_ts"],
            outcomes=[ForecastOutcome(
                selection=str(r["selection"]), probability=r["p"], low=r["p_lo"], high=r["p_hi"], likely=r is best,
                fair_odds=_fair_odds(r["p"]) if preview else None,
                model_probability=r["p_model"] if preview else None) for r in rs]))
    return out


def _why_none(fixture: dict[str, Any]) -> tuple[str, str]:
    """Why a match has no forecast, as a stable code and a sentence: said, not left to look like a gap."""
    if fixture["data_class"] in NOT_FIT:
        return "data_not_fit", "PrediGol does not forecast this competition: its data is not fit for a model yet."
    if fixture["quarantined"]:
        return "quarantined", "PrediGol made no forecast: the data of this match is under review."
    return "no_forecast_yet", "PrediGol has no forecast for this match yet."


def _value(conn: Conn, fixture_id: int) -> Section[list[ValueRow]]:
    rows = fetch_all(conn, VALUE_SQL, {"f": fixture_id, "limit": MAX_VALUE_ROWS})
    if not rows:
        return section([], status=DataStatus.EMPTY, code="no_evaluation",
                       reason="The decision layer has not evaluated any price of this match: without a price there is no value.")
    return section([ValueRow(
        market=str(r["market_key"]), selection=str(r["selection"]), line=r["line"], state=str(r["state"]), odds=r["odds"],
        probability=r["p_cal"], market_probability=r["p_market"], edge=r["edge_cal"], ev=r["ev_cal"],
        reasons=[str(x) for x in (r["reasons"] or [])], known_at=r["known_at"]) for r in rows])


def _picks(conn: Conn, fixture_id: int) -> Section[list[PickRow]]:
    rows = fetch_all(conn, PICKS_SQL, {"f": fixture_id})
    if not rows:
        return section([], status=DataStatus.EMPTY, code="no_pick",
                       reason="No pick was frozen for this match: a forecast, however sure, is not one.")
    return section([PickRow(id=int(r["id"]), market=str(r["market_key"]), selection=str(r["selection"]), line=r["line"],
                            status=str(r["status"]), mode=str(r["mode"]), odds=r["market_odds"],
                            probability=r["p_calibrated"]) for r in rows])


def match_forecast(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None = None) -> Envelope[MatchForecast | None]:
    """The forecast of a match; with ``preview`` (the Admin Console), beside its value and its picks."""
    fixture = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    if not preview and not users_may_see():
        return unavailable(None, "The PrediGol forecast is not shown to users yet.")
    rows = fetch_all(conn, FORECAST_SQL, {"f": fixture_id, "version": VERSION, "at": at or now()})
    markets = _markets(rows, preview=preview)
    if markets:
        forecast = section(markets)
    else:
        code, reason = _why_none(fixture)
        forecast = section([], status=DataStatus.NOT_AVAILABLE, code=code, reason=reason)
    data = MatchForecast(
        fixture_id=int(fixture["id"]), kickoff_at=fixture["kickoff_at"], status_group=str(fixture["status_group"]),
        forecast=forecast, value=_value(conn, fixture_id) if preview else None,
        picks=_picks(conn, fixture_id) if preview else None)
    return ok(data, data_as_of=max((m.known_at for m in markets), default=None))
