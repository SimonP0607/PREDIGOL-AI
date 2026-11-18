"""C-14 served (plan EA, EA-201): the three marks of every price in force of a match. Read only; nothing is fitted here.

* the prices are the ones ``/matches/{id}/markets/catalog`` shows (``read_in_force`` + ``unify``), grouped by the same key;
* the catalogue's state of each market is IA-070's (``load_catalogue``);
* the model: ``forecast-v1`` (``models.match_forecasts``) for the reader, ONLY on an ``evaluable`` market and while
  ``FBI_FORECAST_USERS`` lets readers see the forecast; the owner also gets ``model_shadow`` - ``family-v1`` or ``forecast-v1`` on a
  market still in calibration;
* the implied probability: per house, its prices of one line normalised to their total (2 for a double chance, 1 otherwise), then
  the mean over the houses that price the whole line;
* the history: the selection settled by its rule (``settle_numbers``) on the last ``HISTORY`` matches of the home side at home and of
  the away side away, before the kick-off.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, cast

from fbi.api.cache import shared
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing, Probability
from fbi.api.contracts.intelligence.market_probs import (
    HistoryMark,
    Implied,
    MarketMarksPrivate,
    MarketProbs,
    MarketProbsPrivate,
    ParlayFlag,
    SelectionMarksPrivate,
)
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.stats_profile import Ref
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.forecast import FAMILY_VERSION, VERSION, users_may_see
from fbi.api.services.market_status import MarketCatalogue, load_catalogue
from fbi.api.switches import market_probs_on, parlay_markets_v2_on
from fbi.core.clock import now
from fbi.market.in_force import book as book_in_force
from fbi.market.in_force import group_key, implied, unify
from fbi.market.rules import rule_for
from fbi.odds.quote_current import CurrentQuote, market_key
from fbi.odds.quote_taxonomy import spec_for
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status
from fbi.statmath import formulas as fx
from fbi.userdata.eligibility import verdict
from fbi.userdata.records import MarketPolicy

HISTORY: Final = 10
CACHE_SECONDS: Final = 60

FIXTURE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = %(f)s
"""
SIDE_HISTORY_SQL: Final = """
SELECT o.* FROM market.fixture_outcomes o JOIN core.fixtures f ON f.id = o.fixture_id
 WHERE {column} = %(team)s AND o.kickoff_at < %(kickoff)s AND o.goals_ft_home IS NOT NULL
 ORDER BY o.kickoff_at DESC LIMIT %(n)s
"""
FORECASTS_SQL: Final = """
WITH last AS (
    SELECT version, market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = %(f)s AND version = ANY(%(versions)s) AND known_at <= %(at)s
     GROUP BY 1, 2, 3
)
SELECT x.version, x.market_key, x.line, x.selection, x.calibration, x.known_at, x.p, x.p_lo, x.p_hi
  FROM models.match_forecasts x
  JOIN last l ON l.version = x.version AND l.market_key = x.market_key AND l.line = x.line AND l.k = x.known_at
 WHERE x.fixture_id = %(f)s
"""

ForecastKey = tuple[str, str, Decimal]


def _missing(reason: str) -> Missing:
    return Missing.model_validate({"missing_reason": reason})


def history(rows_home: Sequence[dict[str, Any]], rows_away: Sequence[dict[str, Any]], q: CurrentQuote) -> HistoryMark | Missing:
    spec = spec_for(q.bet_id, q.provider_name)
    rule = rule_for(spec)
    if rule is None:
        return _missing("sin_datos")
    rows = {"match": [*rows_home, *rows_away], "home": list(rows_home), "away": list(rows_away)}.get(q.subject, [])
    hits = n = 0
    for r in rows:
        try:
            status = settle_numbers(rule, q.kind, q.subject, q.selection, q.line, r)
        except ValueError:
            return _missing("sin_datos")
        if status == Status.WIN:
            hits, n = hits + 1, n + 1
        elif status == Status.LOSS:
            n += 1
    if n == 0:
        return _missing("sin_datos")
    pct, lo, hi = fx.wilson_pct(hits, n)
    return HistoryMark(hits=hits, n=n, pct=pct, wilson_low=lo, wilson_high=hi, window="u10_contexto", rule_key=rule.key)


def _probability(row: dict[str, Any], origin: str) -> Probability:
    lo, hi = row.get("p_lo"), row.get("p_hi")
    value = float(row["p"])
    interval: tuple[int, int] | Missing = _missing("sin_datos")
    if lo is not None and hi is not None:
        pct = fx.half_up(value * 100)
        interval = (min(int(fx.half_up(float(lo) * 100)), int(pct)), max(int(fx.half_up(float(hi) * 100)), int(pct)))
    return Probability.of(value, calibration="calibrada" if row.get("calibration") == "CALIBRATED" else "sin_calibrar",
                          as_of=row["known_at"], origin=origin, evaluation=_missing("sin_datos"),
                          evaluation_version=_missing("sin_datos"), interval=interval)


def _forecasts(conn: Conn, fixture_id: int, at: datetime) -> dict[str, dict[ForecastKey, dict[str, Any]]]:
    out: dict[str, dict[ForecastKey, dict[str, Any]]] = {VERSION: {}, FAMILY_VERSION: {}}
    for r in fetch_all(conn, FORECASTS_SQL, {"f": fixture_id, "versions": [VERSION, FAMILY_VERSION], "at": at}):
        out[str(r["version"])][(str(r["market_key"]), str(r["selection"]), Decimal(r["line"]))] = r
    return out


SINGLE_FIGURE: Final = "forecast-v2"
"""The single figure of every goals market (``fbi.forecasting.single_figure``, AD-B05) - the score matrix's coherent derivations of
draw-no-bet, the team totals and every Asian line (plan EA, EA-307): in the owner's projection only, as ``model_shadow``."""


def _shadow_figures(conn: Conn, fixture_id: int, at: datetime) -> Any:
    from fbi.api.services.match_intelligence import (
        read_figures,  # the private answer only: its import stays lazy
    )

    found, _ = read_figures(conn, fixture_id, at=at)
    return found


def _figure_probability(fig: Any) -> Probability:
    interval: tuple[int, int] | Missing = _missing("sin_datos")
    pct = int(fx.half_up(float(fig.p) * 100))
    if fig.lo is not None and fig.hi is not None:
        interval = (min(int(fx.half_up(float(fig.lo) * 100)), pct), max(int(fx.half_up(float(fig.hi) * 100)), pct))
    return Probability.of(min(1.0, max(0.0, float(fig.p))), calibration="calibrada" if fig.calibration == "CALIBRATED" else "sin_calibrar",
                          as_of=fig.cutoff, origin=SINGLE_FIGURE, evaluation=_missing("sin_datos"),
                          evaluation_version=_missing("sin_datos"), interval=interval)


def build(conn: Conn, fixture_id: int, *, at: datetime | None = None, catalogue: MarketCatalogue | None = None,
          shadow: bool = False) -> MarketProbsPrivate:
    moment = at or now()
    fx_row = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fx_row is None:
        raise ApiError(404, "not_found", "not found")
    book = book_in_force(conn, fixture_id)
    quotes = unify(book.quotes) if book is not None else []
    cat = catalogue or load_catalogue()
    kickoff: datetime = fx_row["kickoff_at"]
    started = moment >= kickoff
    home_rows = fetch_all(conn, SIDE_HISTORY_SQL.format(column="f.home_team_id"),
                          {"team": fx_row["home_team_id"], "kickoff": kickoff, "n": HISTORY})
    away_rows = fetch_all(conn, SIDE_HISTORY_SQL.format(column="f.away_team_id"),
                          {"team": fx_row["away_team_id"], "kickoff": kickoff, "n": HISTORY})
    forecasts = _forecasts(conn, fixture_id, moment)
    figures = _shadow_figures(conn, fixture_id, moment) if shadow else None
    readers_see_forecast = users_may_see()
    switch = parlay_markets_v2_on()
    by_key: dict[str, list[CurrentQuote]] = defaultdict(list)
    for q in quotes:
        by_key[market_key(q.bet_id, q.period, q.subject)].append(q)
    markets: list[MarketMarksPrivate] = []
    for key, rows in sorted(by_key.items()):
        lead = min(rows, key=lambda q: q.bet_id)
        spec = spec_for(lead.bet_id, lead.provider_name)
        status = cat.for_bet(lead.bet_id)
        unit = status.key
        published_key = lead.market_key if lead.period == "FT" and lead.subject == "match" else None
        evaluable = status.state == "evaluable"
        imp = implied(rows)
        by_sel: dict[tuple[str, Decimal], list[CurrentQuote]] = defaultdict(list)
        for q in rows:
            by_sel[(q.selection, q.line)].append(q)
        selections = []
        origin: str | Missing = _missing("sin_datos")
        for (sel, line), qs in sorted(by_sel.items(), key=lambda kv: (group_key(kv[1][0]), kv[0][0])):
            top = max(qs, key=lambda q: (q.odds, -q.bookmaker_id))
            published = forecasts[VERSION].get((published_key, sel, line)) if published_key else None
            family = forecasts[FAMILY_VERSION].get((unit, sel, line))
            model: Probability | Missing = _missing("sin_datos")
            shadow_p: Probability | Missing = _missing("sin_datos")
            if published is not None:
                origin = VERSION
                if evaluable and readers_see_forecast:
                    model = _probability(published, VERSION)
                else:
                    shadow_p = _probability(published, VERSION)
            elif family is not None:
                origin = FAMILY_VERSION
                shadow_p = _probability(family, FAMILY_VERSION)
            if figures is not None and isinstance(shadow_p, Missing) and lead.period == "FT":
                fig = figures.get(unit, sel, line)
                if fig is not None:
                    shadow_p = _figure_probability(fig)
                    if isinstance(origin, Missing):
                        origin = SINGLE_FIGURE
            i = imp.get((sel, line))
            v = verdict(spec, line=line, books=len({q.bookmaker_id for q in qs}), state=status.state, started=started,
                        switch_on=switch)
            selections.append(SelectionMarksPrivate(
                selection=sel, line=float(line), best_odds=float(top.odds), bookmaker=top.bookmaker, model=model,
                implied=Implied(value=fx.half_up(i[0], 4), pct=fx.pct_int(i[0]), books=i[1], as_of=i[2]) if i else _missing("sin_datos"),
                history=history(home_rows, away_rows, top), parlay=ParlayFlag(allowed=v.allowed, reason=cast(Any, v.reason)),
                model_shadow=shadow_p))
        markets.append(MarketMarksPrivate(
            key=key, unit=unit, category=lead.family, kind=lead.kind, period=lead.period, subject=lead.subject,
            state=cast(Any, status.state), state_reason=status.reason, rule_key=status.entry.rule_key or _missing("sin_datos"),
            model_origin=origin, distribution=_missing("sin_datos"), selections=selections,
            distribution_shadow=_missing("sin_datos")))
    items = ItemList[MarketMarksPrivate](items=markets) if markets else ItemList[MarketMarksPrivate](items=[], missing_reason="sin_datos")
    return MarketProbsPrivate(
        fixture_id=fixture_id, kickoff_at=kickoff, home=Ref(id=int(fx_row["home_team_id"]), name=str(fx_row["home_name"])),
        away=Ref(id=int(fx_row["away_team_id"]), name=str(fx_row["away_name"])), catalog_version=cat.catalog_version,
        markets=items, freshness=Freshness(generated_at=moment, stale=False))


def parlay_policy() -> MarketPolicy:
    """What Mi parlay takes beyond the five (EA-501): ``FBI_PARLAY_MARKETS_V2`` and the catalogue's state of each bet - the same
    inputs that mark a price ``parlay.allowed`` here, so the page never offers what the server refuses."""
    cat = load_catalogue()
    return MarketPolicy(enabled=parlay_markets_v2_on(), state_of=lambda bet_id: cat.for_bet(bet_id).state)


@shared(CACHE_SECONDS)
def _public_cached(conn: Conn, fixture_id: int) -> Envelope[MarketProbs]:
    return ok(to_public(build(conn, fixture_id), MarketProbs))


def public(conn: Conn, fixture_id: int) -> Envelope[MarketProbs]:
    if not market_probs_on():
        raise ApiError(404, "not_found", "not found")
    return _public_cached(conn, fixture_id)


def private(conn: Conn, fixture_id: int) -> Envelope[MarketProbsPrivate]:
    return ok(build(conn, fixture_id, shadow=True))
