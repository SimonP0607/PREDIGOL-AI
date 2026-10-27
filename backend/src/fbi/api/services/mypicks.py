"""Mis picks completo (plan UX, B5, section 30): the reader's own saved picks under the filter they chose - their totals and
breakdown, always with their sample, the line value of their prices - and the two CSV files of their own records. Reading
only, through the API's read-only connection, and only the signed-in reader's rows (every query is ``WHERE u.user_id``).

THE SAMPLE. The rule of «Cómo le va a PrediGol» (``fbi.api.services.transparency``, one implementation: its ``count``,
``margin``, ``MIN_SAMPLE`` and ``CONCLUSIVE``): below 25 settled picks only the counts are given; from 25 the units, the ROI,
the hit rate and the ROI's margin (1 / sqrt(n): ±20 points with 25, ±10 with 100); below 100 the page says the sample does not
allow a conclusion yet. Each row of the breakdown follows it on its own.

THE LINE VALUE. ``clv-v1`` (``fbi.market.closing_value``): the price the reader counts - their own when they gave one, else
the price shown when they saved it - at the de-vigged (Shin) consensus of the last capture before kick-off. Only once the
match has started: before, the close is not known.

THE CSV. Every saved pick under the filter (no page), the newest kick-off first, and every parlay with one line per leg; the
reader's own rows and nothing else, the times in their time zone, the headings and the words in their language (es or en),
the kinds of bet and the selections as their codes. A text cell that a spreadsheet would read as a formula (it starts with
=, +, -, @, a tab or a return) gets a leading apostrophe. UTF-8 with its mark, so a spreadsheet reads the accents.
"""

from __future__ import annotations

import csv
import io
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from zoneinfo import ZoneInfo

from fbi.api.contracts.mypicks import (
    AppliedFilter,
    BandRow,
    CompetitionRow,
    FilterOptions,
    MarketRow,
    MyLineValue,
    PicksDefinition,
    PicksSummary,
    PicksTally,
)
from fbi.api.contracts.product import CompetitionBadge
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services import transparency
from fbi.api.services.pick_filter import BAND_ORDER, BANDS, CLOSE_JOIN, JOINS, SQL, PickFilter
from fbi.core.clock import now
from fbi.market import closing_value

MARKET_ORDER: Final = ("1X2", "OU", "BTTS", "AH", "DC")

SUMMARY_SQL: Final = """
SELECT u.id, u.status, u.profit_units AS profit, u.market_key, COALESCE(u.user_odds, u.odds) AS price, f.kickoff_at,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag, pc.p_fair AS p_close, pc.as_of AS close_at
  FROM picks.user_picks u""" + JOINS + CLOSE_JOIN + """
 WHERE u.user_id = %(user)s""" + SQL

OPTIONS_SQL: Final = """
SELECT DISTINCT u.market_key, c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag
  FROM picks.user_picks u
  JOIN core.fixtures f ON f.id = u.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE u.user_id = %(user)s
"""

EXPORT_PICKS_SQL: Final = """
SELECT u.id, u.saved_at, f.kickoff_at, c.name AS competition, c.country, th.name AS home, ta.name AS away, u.market_key,
       u.selection, u.line, u.origin, u.odds, u.bookmaker, u.user_odds, u.status, u.profit_units, u.settled_at,
       pc.p_fair AS p_close
  FROM picks.user_picks u""" + JOINS + CLOSE_JOIN + """
 WHERE u.user_id = %(user)s""" + SQL + """
 ORDER BY f.kickoff_at DESC, u.id DESC
"""

EXPORT_PARLAYS_SQL: Final = """
SELECT p.id, p.name, p.created_at, p.combined_odds, p.status, p.profit_units, p.settled_at, l.leg_no, f.kickoff_at,
       c.name AS competition, th.name AS home, ta.name AS away, l.market_key, l.selection, l.line, l.odds,
       l.status AS leg_status
  FROM picks.user_parlays p
  JOIN picks.user_parlay_legs l ON l.user_parlay_id = p.id
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE p.user_id = %(user)s
 ORDER BY p.created_at DESC, p.id DESC, l.leg_no
"""

DEFINITIONS: Final = tuple(PicksDefinition(key=d.key, version=d.version, since=d.since)
                           for d in transparency.DEFINITIONS if d.key in ("roi", "sample", "line_value"))
"""The same definitions, versions and dates «Cómo le va a PrediGol» states (``transparency.DEFINITIONS``)."""


def params(user_id: int, flt: PickFilter, tz: str, at: datetime) -> dict[str, object]:
    return {"user": user_id, "now": at, **flt.params(tz)}


# ── the totals ──────────────────────────────────────────────────────────────────

def tally_fields(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """A tally of saved picks with the sample rule of «Cómo le va a PrediGol» - the same function, then named for Mis picks."""
    c = transparency.count(rows)
    fields = transparency.tally_fields(c)
    enough = c.staked >= transparency.MIN_SAMPLE
    wins, decided = c.won + c.half_won, c.won + c.half_won + c.lost + c.half_lost
    return {
        "total": fields.pop("published"),
        **{k: v for k, v in fields.items() if k != "conclusive"},
        "hit_rate": (Decimal(wins) / Decimal(decided)).quantize(Decimal("0.0001")) if enough and decided else None,
        "sample": "counts_only" if not enough else "conclusive" if fields["conclusive"] else "inconclusive",
    }


def badge(r: Mapping[str, Any]) -> CompetitionBadge:
    return CompetitionBadge(id=int(r["competition_id"]), name=r["competition_name"], country=r["competition_country"],
                            logo_url=r["competition_logo"], flag_url=r["competition_flag"])


def band_of(price: Decimal | None) -> str | None:
    if price is None:
        return None
    for key in BAND_ORDER:
        low, high = BANDS[key]
        if price >= low and (high is None or price < high):
            return key
    return None


def markets_of(rows: Sequence[Mapping[str, Any]]) -> list[MarketRow]:
    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by[str(r["market_key"])].append(r)
    order = {m: i for i, m in enumerate(MARKET_ORDER)}
    return [MarketRow(market=m, **tally_fields(rs))
            for m, rs in sorted(by.items(), key=lambda kv: (-len(kv[1]), order.get(kv[0], len(order)), kv[0]))]


def competitions_of(rows: Sequence[Mapping[str, Any]]) -> list[CompetitionRow]:
    by: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by[int(r["competition_id"])].append(r)
    return [CompetitionRow(competition=badge(rs[0]), **tally_fields(rs))
            for _, rs in sorted(by.items(), key=lambda kv: (-len(kv[1]), str(kv[1][0]["competition_name"]), kv[0]))]


def bands_of(rows: Sequence[Mapping[str, Any]]) -> list[BandRow]:
    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        key = band_of(None if r["price"] is None else Decimal(r["price"]))
        if key is not None:
            by[key].append(r)
    return [BandRow(band=key, **tally_fields(by[key])) for key in BAND_ORDER if by[key]]


def line_value_of(rows: Sequence[Mapping[str, Any]]) -> MyLineValue:
    priced = [r for r in rows if r["p_close"] is not None and r["price"] is not None]
    values = [closing_value.clv(Decimal(r["price"]), Decimal(r["p_close"])) for r in priced]
    minutes = [(r["kickoff_at"] - r["close_at"]).total_seconds() / 60 for r in priced]
    enough = len(values) >= transparency.MIN_SAMPLE
    return MyLineValue(
        version=closing_value.VERSION, since=transparency.LINE_VALUE_SINCE, n=len(values),
        mean=(sum(values, Decimal(0)) / len(values)).quantize(Decimal("0.0001")) if enough else None,
        positive=(Decimal(sum(1 for v in values if v > 0)) / len(values)).quantize(Decimal("0.0001")) if enough else None,
        minutes=round(statistics.median(minutes)) if minutes else None)


def options(conn: Conn, user_id: int) -> FilterOptions:
    rows = fetch_all(conn, OPTIONS_SQL, {"user": user_id})
    order = {m: i for i, m in enumerate(MARKET_ORDER)}
    markets = sorted({str(r["market_key"]) for r in rows}, key=lambda m: (order.get(m, len(order)), m))
    seen: dict[int, CompetitionBadge] = {}
    for r in rows:
        seen.setdefault(int(r["competition_id"]), badge(r))
    return FilterOptions(markets=markets, competitions=sorted(seen.values(), key=lambda b: (b.name, b.id)))


def applied(flt: PickFilter) -> AppliedFilter:
    return AppliedFilter(result=flt.result, market=flt.market, competition=flt.competition, origin=flt.origin,
                         band=flt.band, since=flt.since, until=flt.until, search=flt.search, active=flt.active)


def summary(conn: Conn, *, user_id: int, flt: PickFilter, tz: str, at: datetime | None = None) -> PicksSummary:
    """The reader's saved picks under the filter: totals, by kind of bet, by league, by odds range, and the line value."""
    moment = at or now()
    rows = fetch_all(conn, SUMMARY_SQL, params(user_id, flt, tz, moment))
    return PicksSummary(
        timezone=tz, min_sample=transparency.MIN_SAMPLE, conclusive=transparency.CONCLUSIVE, filter=applied(flt),
        tally=PicksTally(**tally_fields(rows)), markets=markets_of(rows), competitions=competitions_of(rows),
        bands=bands_of(rows), line_value=line_value_of(rows), options=options(conn, user_id),
        definitions=list(DEFINITIONS))


# ── the CSV files ───────────────────────────────────────────────────────────────

HEADINGS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "picks": {
        "es": ("guardado", "inicio", "liga", "pais", "local", "visitante", "mercado", "seleccion", "linea", "origen",
               "cuota_mostrada", "casa", "tu_cuota", "resultado", "unidades", "liquidado", "prob_cierre", "valor_de_linea"),
        "en": ("saved_at", "kickoff", "league", "country", "home", "away", "market", "selection", "line", "origin",
               "odds_shown", "bookmaker", "your_odds", "result", "units", "settled_at", "p_close", "line_value"),
    },
    "parlays": {
        "es": ("parlay", "nombre", "creado", "cuota_combinada", "estado", "unidades", "liquidado", "pierna", "inicio",
               "liga", "local", "visitante", "mercado", "seleccion", "linea", "cuota", "resultado_pierna"),
        "en": ("parlay", "name", "created_at", "combined_odds", "status", "units", "settled_at", "leg", "kickoff",
               "league", "home", "away", "market", "selection", "line", "odds", "leg_result"),
    },
}
WORDS: Final[dict[str, dict[str, str]]] = {
    "es": {"PENDING": "Pendiente", "WIN": "Ganado", "LOSS": "Perdido", "HALF_WIN": "Medio ganado",
           "HALF_LOSS": "Medio perdido", "PUSH": "Devuelto", "VOID": "Anulado", "predigol_pick": "PrediGol",
           "market": "Tu selección", "READY": "Lista", "ACTIVE": "En juego", "WON": "Ganado", "LOST": "Perdido",
           "PARTIAL_VOID": "Ganado con anuladas", "BUILDING": "En preparación"},
    "en": {"PENDING": "Pending", "WIN": "Won", "LOSS": "Lost", "HALF_WIN": "Half won", "HALF_LOSS": "Half lost",
           "PUSH": "Push", "VOID": "Void", "predigol_pick": "PrediGol", "market": "Your selection", "READY": "Ready",
           "ACTIVE": "In play", "WON": "Won", "LOST": "Lost", "PARTIAL_VOID": "Won with voided legs",
           "BUILDING": "Being built"},
}
FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")


def text_cell(value: object) -> str:
    """A text a spreadsheet must not run: one that starts like a formula gets a leading apostrophe."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def number_cell(value: object) -> str:
    return "" if value is None else str(value)


def time_cell(value: datetime | None, zone: ZoneInfo) -> str:
    return "" if value is None else value.astimezone(zone).isoformat(timespec="minutes")


def language_of(language: str | None) -> str:
    return "en" if (language or "").lower().startswith("en") else "es"


def word(lang: str, code: object) -> str:
    return WORDS[lang].get(str(code), str(code))


def _csv(headings: Sequence[str], lines: Iterable[Sequence[str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(headings)
    writer.writerows(lines)
    return "﻿" + out.getvalue()


def picks_csv(conn: Conn, *, user_id: int, flt: PickFilter, tz: str, language: str | None,
              at: datetime | None = None) -> str:
    """Every saved pick of the reader under the filter, the newest kick-off first."""
    moment = at or now()
    lang = language_of(language)
    zone = ZoneInfo(tz)
    lines = []
    for r in fetch_all(conn, EXPORT_PICKS_SQL, params(user_id, flt, tz, moment)):
        price = r["user_odds"] if r["user_odds"] is not None else r["odds"]
        value = (closing_value.clv(Decimal(price), Decimal(r["p_close"])).quantize(Decimal("0.0001"))
                 if price is not None and r["p_close"] is not None else None)
        lines.append((
            time_cell(r["saved_at"], zone), time_cell(r["kickoff_at"], zone), text_cell(r["competition"]),
            text_cell(r["country"]), text_cell(r["home"]), text_cell(r["away"]), text_cell(r["market_key"]),
            text_cell(r["selection"]), number_cell(r["line"]), word(lang, r["origin"]), number_cell(r["odds"]),
            text_cell(r["bookmaker"]), number_cell(r["user_odds"]), word(lang, r["status"]),
            number_cell(r["profit_units"]), time_cell(r["settled_at"], zone), number_cell(r["p_close"]),
            number_cell(value)))
    return _csv(HEADINGS["picks"][lang], lines)


def parlays_csv(conn: Conn, *, user_id: int, tz: str, language: str | None) -> str:
    """Every parlay of the reader, the newest first, one line per leg."""
    lang = language_of(language)
    zone = ZoneInfo(tz)
    lines = [(
        str(r["id"]), text_cell(r["name"]), time_cell(r["created_at"], zone), number_cell(r["combined_odds"]),
        word(lang, r["status"]), number_cell(r["profit_units"]), time_cell(r["settled_at"], zone), str(r["leg_no"]),
        time_cell(r["kickoff_at"], zone), text_cell(r["competition"]), text_cell(r["home"]), text_cell(r["away"]),
        text_cell(r["market_key"]), text_cell(r["selection"]), number_cell(r["line"]), number_cell(r["odds"]),
        word(lang, r["leg_status"])) for r in fetch_all(conn, EXPORT_PARLAYS_SQL, {"user": user_id})]
    return _csv(HEADINGS["parlays"][lang], lines)


def filename(kind: str, at: datetime | None = None) -> str:
    """predigol-mis-picks-2026-10-27.csv / predigol-mis-parlays-2026-10-27.csv."""
    return f"predigol-mis-{kind}-{(at or now()):%Y-%m-%d}.csv"
