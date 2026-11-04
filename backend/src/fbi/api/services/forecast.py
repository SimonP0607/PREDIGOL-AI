"""PrediGol's forecast of a match, read for the product and for the Admin Console's preview (plan F5). Reading only.

The forecast is what the worker wrote to ``models.match_forecasts`` (``fbi.forecasting.match_forecast``): a probability, the
interval the model measured around it and whether a champion calibrator was applied. This module only lays it out. It never
computes a probability, never reads a price to make one, and never turns a forecast into a value or a pick.

Who sees what. A user sees the forecast and nothing else - no odds, no edge, no pick - and only once the owner has decided that
users see it (``FBI_FORECAST_USERS``; off until then). The Admin Console's preview (``preview=shadow``) sees the forecast with
its fair odds beside what the decision layer said about the same match (``value``, which needs a price) and the picks frozen for
it (``picks``), so that the three can be told apart.

The families (plan F10: the goals of each half, the corners and the cards) forecast under a version of their own, ``family-v1``: research,
uncalibrated, with no interval. This page never mixes them into the forecast above - that reads ``forecast-v1`` and nothing else - and a
user never gets them: the preview alone gets a section of its own (``families``), and it is null in every other answer.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.api.contracts.forecast import (
    FamilyLine,
    FamilyMarket,
    ForecastMarket,
    ForecastOutcome,
    MatchForecast,
    PickRow,
    ValueRow,
)
from fbi.api.envelope import DataStatus, Envelope, Section, ok, section, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.family_rules import FAMILIES, rule_of
from fbi.api.switches import user_switch
from fbi.core.clock import now
from fbi.core.decision_versions import DECISION_CORE

VERSION: Final = "forecast-v1"
"""The forecast the worker writes (``fbi.forecasting.match_forecast.VERSION``; a test holds the two equal)."""
NOT_FIT: Final = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
"""The competition data classes the worker does not forecast (``match_forecast.NOT_FIT``; a test holds them equal)."""
USERS_SWITCH: Final = "FBI_FORECAST_USERS"
"""Every signed-in account sees the forecast: on since plan UX A9 (the owner approved it), ``FBI_FORECAST_USERS=0`` hides it again
without a deploy (``fbi.api.switches``). The Admin Console's preview does not depend on it. The API needs a restart to read it."""
MARKET_ORDER: Final = {"1X2": 0, "OU": 1, "BTTS": 2}
MAX_VALUE_ROWS: Final = 200
FAMILY_VERSION: Final = "family-v1"
"""The forecasts of the families of counts (``fbi.families.forecast.VERSION``; a test holds the two equal): the goals of each half, the corners and the
cards. Research and uncalibrated. The forecast of the product never reads them; the Admin Console's preview does, in a section of its own."""

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
  FROM intel.decisions WHERE fixture_id = %(f)s AND decision_version = %(decision_version)s
 ORDER BY market_key, selection, line, known_at DESC, id DESC
 LIMIT %(limit)s
"""
"""The value of a price, from the pipeline's decision layer and no other: the rows of the families (``decision-fam-v1``) are research, and a page
that shows what the model sees in a price shows it from the layer that has calibrators, filters it was held to and a stake."""

PICKS_SQL = """
SELECT id, market_key, selection, line, status, mode, market_odds, p_calibrated
  FROM picks.picks WHERE fixture_id = %(f)s ORDER BY id
"""


def users_may_see() -> bool:
    return user_switch(USERS_SWITCH, default=True)


LIKELY_SQL = """
WITH last AS (
    SELECT fixture_id, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = ANY(%(ids)s) AND version = %(version)s AND market_key = '1X2' AND known_at <= %(at)s
     GROUP BY 1
)
SELECT x.fixture_id, x.selection, x.p, x.calibration
  FROM models.match_forecasts x JOIN last l ON l.fixture_id = x.fixture_id AND l.k = x.known_at
 WHERE x.version = %(version)s AND x.market_key = '1X2'
 ORDER BY x.fixture_id, x.id
"""
"""The newest result forecast (1X2) of many matches at once, for a list (Home, plan UX A9)."""


def likely_results(conn: Conn, fixture_ids: list[int], *, at: datetime | None = None
                   ) -> dict[int, tuple[str, Decimal, str]]:
    """Per match, the likely outcome of the result forecast as a reader may see it: (selection, probability, calibration).
    Nothing while readers do not see the forecast (``FBI_FORECAST_USERS=0``) and nothing for a match without one."""
    if not fixture_ids or not users_may_see():
        return {}
    out: dict[int, tuple[str, Decimal, str]] = {}
    for r in fetch_all(conn, LIKELY_SQL, {"ids": fixture_ids, "version": VERSION, "at": at or now()}):
        fid = int(r["fixture_id"])
        if fid not in out or Decimal(r["p"]) > out[fid][1]:  # the first of two equal ones, as the match page says
            out[fid] = (str(r["selection"]), Decimal(r["p"]), str(r["calibration"]))
    return out


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
            market=market, line=line, family=str(first["family"]),
            model=str(first["model_name"]) if preview else None,
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


def _families(conn: Conn, fixture_id: int, at: datetime) -> Section[list[FamilyMarket]]:
    """What the families forecast for the match, by family and market, each line with the probability of every outcome. The same rule as the
    forecast: the newest set of each market and line known by ``at``. The model's own number, uncalibrated, with no interval; the fair odds
    are 1 / probability, which only this preview shows."""
    rows = fetch_all(conn, FORECAST_SQL, {"f": fixture_id, "version": FAMILY_VERSION, "at": at})
    if not rows:
        return section([], status=DataStatus.EMPTY, code="no_family_forecast",
                       reason="The families have forecast nothing for this match: they forecast the matches about to be played of the competitions "
                              "whose data is fit for a model.")
    grouped: dict[tuple[str, str], dict[Decimal, list[dict[str, Any]]]] = {}
    for r in rows:
        grouped.setdefault((str(r["family"]), str(r["market_key"])), {}).setdefault(Decimal(r["line"]), []).append(r)
    order = {family: i for i, family in enumerate(FAMILIES)}
    out: list[FamilyMarket] = []
    for (family, key), by_line in sorted(grouped.items(), key=lambda kv: (order.get(kv[0][0], len(order)), kv[0][1])):
        lines: list[FamilyLine] = []
        for line, rs in sorted(by_line.items()):
            best = max(rs, key=lambda r: r["p"])  # the first of them if two tie
            lines.append(FamilyLine(line=line, known_at=rs[0]["known_at"], outcomes=[ForecastOutcome(
                selection=str(r["selection"]), probability=r["p"], low=r["p_lo"], high=r["p_hi"], likely=r is best,
                fair_odds=_fair_odds(r["p"])) for r in rs]))
        newest = max(by_line.values(), key=lambda rs: rs[0]["known_at"])[0]
        rule = rule_of(key)
        out.append(FamilyMarket(
            family=family, market=key, model=str(newest["model_name"]), calibration=newest["calibration"],
            rule=None if rule is None else rule.key, known_at=max(ln.known_at for ln in lines),
            data_cutoff_at=newest["data_cutoff_ts"], lines=lines))
    return section(out)


def _value(conn: Conn, fixture_id: int) -> Section[list[ValueRow]]:
    rows = fetch_all(conn, VALUE_SQL, {"f": fixture_id, "limit": MAX_VALUE_ROWS, "decision_version": DECISION_CORE})
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
    moment = at or now()
    rows = fetch_all(conn, FORECAST_SQL, {"f": fixture_id, "version": VERSION, "at": moment})
    markets = _markets(rows, preview=preview)
    if markets:
        forecast = section(markets)
    else:
        code, reason = _why_none(fixture)
        forecast = section([], status=DataStatus.NOT_AVAILABLE, code=code, reason=reason)
    data = MatchForecast(
        fixture_id=int(fixture["id"]), kickoff_at=fixture["kickoff_at"], status_group=str(fixture["status_group"]),
        forecast=forecast, value=_value(conn, fixture_id) if preview else None,
        picks=_picks(conn, fixture_id) if preview else None,
        families=_families(conn, fixture_id, moment) if preview else None)
    return ok(data, data_as_of=max((m.known_at for m in markets), default=None))
