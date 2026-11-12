"""The odds explorer (plan Cuotas, ola 2, BE-011): what ``/odds/families``, ``/odds/board``, ``/matches/{id}/odds-book``,
``/odds/fixtures/{id}/movement`` and ``/admin/odds/health`` answer.

Everything is read from the current-price book (``market.book_current``, built by ``fbi.odds.book`` from the provider's answer in
force) and the stored history; no request reaches the provider, whoever reads. Each answer is the same for every reader and kept
in the shared cache (``fbi.api.cache``): 60 s, the movement 5 min. A price's ``state`` and whether it may go to Mi Parlay follow
``fbi.odds.freshness`` - the one rule - with the capture's windows and tolerance and, while the book refreshes run, their points.
Prices only: nothing here reads a model, a pick or the shadow layer.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from fbi.api.cache import shared
from fbi.api.contracts.odds_explorer import (
    BookState,
    MatchOddsBook,
    OddsBoardPage,
    OddsBoardRow,
    OddsBookFamily,
    OddsBookLine,
    OddsBookmaker,
    OddsBookMarket,
    OddsBookPrices,
    OddsFamilies,
    OddsFamily,
    OddsHealth,
    OddsHorizonHealth,
    OddsMarketInfo,
    OddsMovement,
    OddsMovementPoint,
    OddsMovementSeries,
    OddsSelectionPrice,
    OddsStatus,
    OddsStatusHorizon,
    OddsStatusMatch,
    Period,
    Sort,
    Subject,
)
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import odds_explorer as repo
from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.intel.day_priority import group_of
from fbi.odds import book, freshness
from fbi.odds.book_markets import PLAYER_SELECTION, Market, index
from fbi.odds.book_parse import Read, format_number
from fbi.odds.book_taxonomy import PERIODS, BookSpec
from fbi.odds.quote_current import LOOKBACK

CACHE_SECONDS = 60
MOVEMENT_SECONDS = 300
MAX_LIMIT = 50
CLASSIC_MARKETS: Mapping[int, str] = {1: "1X2", 4: "AH", 5: "OU", 8: "BTTS", 12: "DC"}
"""The five markets of ``market.odds_snapshots`` (the capture's own series) by provider bet id."""
HORIZONS: tuple[tuple[str, int, int], ...] = (("0-6h", 0, 6), ("6-24h", 6, 24), ("24-72h", 24, 72))
DEFAULT_PARTITION_CAP = 100_000
EXTRACTION_LOOKBACK = timedelta(days=1)


# ── shared pieces ─────────────────────────────────────────────────────────────────────────────────────────────────


def schedule_points() -> tuple[int, ...]:
    """The scheduled asks a price is judged against: the model windows and, while the book refreshes run, their points."""
    cfg = settings.odds
    return freshness.schedule(cfg.prematch_windows, refreshes=cfg.book_refresh_enabled)


def tolerance() -> int:
    return settings.odds.odds_window_tolerance


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _row_state(checked_at: datetime, kickoff_at: datetime, moment: datetime) -> freshness.State:
    return freshness.price_state(checked_at=checked_at, kickoff_at=kickoff_at, now=moment, points=schedule_points(),
                                 tolerance=tolerance())


def selection_price(spec: BookSpec, group_line: Any, sel: Mapping[str, Any], *, state: str, kickoff_at: datetime,
                    moment: datetime) -> OddsSelectionPrice:
    """One selection of a summary line, as the explorer shows it."""
    token = str(sel["sel"])
    own = _dec(sel.get("line", group_line))
    player: str | None = None
    selection = token
    if spec.reader in ("player", "player_count") and token not in set(spec.vocabulary.values()):
        player, selection = token, PLAYER_SELECTION
    priced = "fair" in sel
    outlier = bool(sel.get("outlier", False))
    best = _dec(sel["best"])
    assert best is not None
    return OddsSelectionPrice(
        selection=selection, player=player, line=own, best_odds=best, bookmaker_id=int(sel["best_bk"]),
        n_books=int(sel["n"]), fair_odds=_dec(sel["fair"]) if priced else None,
        price_edge=_dec(sel["edge"]) if priced else None, outlier=outlier,
        parlay_ok=freshness.parlay_ok(parlay_market=spec.parlay, line=own, outlier=outlier, state=state,
                                      kickoff_at=kickoff_at, now=moment))


def _bookmakers(conn: Conn, ids: Iterable[int]) -> list[OddsBookmaker]:
    return [OddsBookmaker(id=int(r["id"]), name=str(r["name"])) for r in repo.bookmakers(conn, list(ids))]


def _definitions(conn: Conn) -> dict[int, int]:
    """provider bet id -> ``market.market_definitions.id`` (the book's rows are keyed by the definition)."""
    return book.definition_ids(conn)


def _market(key: str, period: str) -> Market:
    found = index().find(key, period)
    if found is None:
        periods = index().periods_of(key)
        if not periods:
            raise ApiError(422, "unknown_market", f"no market {key!r} in the taxonomy")
        raise ApiError(422, "unknown_period", f"market {key!r} has the periods {', '.join(periods)}")
    return found


def _info(market: Market, *, periods: Sequence[str], fixtures: int, max_books: int) -> OddsMarketInfo:
    return OddsMarketInfo(key=market.key, family=market.family, kind=market.kind, subject=cast(Subject, market.subject),
                          periods=[cast(Period, p) for p in PERIODS if p in periods], has_line=market.has_line,
                          fair=market.fair, parlay=market.parlay, fixtures=fixtures, max_books=max_books)


@dataclass(frozen=True, slots=True)
class Window:
    hours: int
    country: str | None
    competition: int | None

    def params(self, moment: datetime) -> dict[str, Any]:
        return {"now": moment, "until": moment + timedelta(hours=self.hours), "country": self.country,
                "competition": self.competition}


# ── /odds/families ────────────────────────────────────────────────────────────────────────────────────────────────


@shared(CACHE_SECONDS)
def families(conn: Conn, *, hours: int, country: str | None = None, competition: int | None = None,
             at: datetime | None = None) -> Envelope[OddsFamilies]:
    """The families and markets with prices in the window, with how many matches and the most bookmakers each has."""
    moment = at or clock_now()
    window = Window(hours, country, competition)
    definitions = _definitions(conn)
    defs: list[int] = []
    fams: list[str] = []
    keys: list[str] = []
    periods: list[str] = []
    for market in index().markets:
        for spec in market.specs:
            definition = definitions.get(spec.bet_id)
            if definition is not None:
                defs.append(definition)
                fams.append(market.family)
                keys.append(market.key)
                periods.append(spec.period)
    rows = repo.families(conn, {**window.params(moment), "defs": defs, "families": fams, "markets": keys,
                                "periods": periods}) if defs else []
    family_rows = {r["family"]: r for r in rows if r["market"] is None}
    market_rows = {(r["family"], r["market"]): r for r in rows if r["market"] is not None and r["period"] is None}
    priced_periods: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r["market"] is not None and r["period"] is not None and int(r["fixtures"]) > 0:
            priced_periods[(r["family"], r["market"])].add(str(r["period"]))
    out: list[OddsFamily] = []
    by_family: dict[str, list[OddsMarketInfo]] = defaultdict(list)
    for market in index().markets:
        held = market_rows.get((market.family, market.key))
        if held is None or int(held["fixtures"]) == 0:
            continue
        by_family[market.family].append(_info(market, periods=sorted(priced_periods[(market.family, market.key)]),
                                              fixtures=int(held["fixtures"]), max_books=int(held["max_books"])))
    for family, markets in by_family.items():
        out.append(OddsFamily(key=family, fixtures=int(family_rows[family]["fixtures"]), markets=markets))
    body = OddsFamilies(window_hours=hours, families=out, book_enabled=settings.odds.book_enabled, generated_at=moment)
    if not out:
        return unavailable(body, "no_prices_in_window", status=DataStatus.EMPTY, count=0)
    return ok(body, count=len(out))


# ── /odds/board ───────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BoardQuery:
    market: str
    period: str = "FT"
    line: Decimal | None = None
    hours: int = 24
    country: str | None = None
    competition: int | None = None
    q: str | None = None
    bookmaker: int | None = None
    min_books: int | None = None
    odds_min: Decimal | None = None
    odds_max: Decimal | None = None
    fair_only: bool = False
    sort: Sort = "time"
    cursor: str | None = None
    limit: int = 20


def _like(text: str | None) -> str | None:
    """A substring pattern for ILIKE with the wildcards of the reader's text taken literally."""
    if text is None or not text.strip():
        return None
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def sort_key(row: Mapping[str, Any], sort: str) -> tuple[Any, ...]:
    """The order of the board: kick-off; the owner's competition priority (comp-priority-v1) then name; or the widest
    difference with the fair price first. The match id breaks every tie."""
    kickoff = row["kickoff_at"].isoformat()
    if sort == "competition":
        return (group_of(row["provider_league_id"]), str(row["competition_name"]), kickoff, int(row["fixture_id"]))
    if sort == "edge":
        return (-Decimal(row["edge"]), kickoff, int(row["fixture_id"]))
    return (kickoff, int(row["fixture_id"]))


def encode_cursor(sort: str, key: tuple[Any, ...]) -> str:
    plain = [str(v) if isinstance(v, Decimal) else v for v in key]
    raw = json.dumps({"s": sort, "k": plain}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, sort: str) -> tuple[Any, ...]:
    """The key of the last row of the previous page; 422 ``invalid_cursor`` for anything else (another sort's included)."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or data.get("s") != sort or not isinstance(data.get("k"), list):
            raise ValueError("not a cursor of this sort")
        key = list(data["k"])
        shapes = {"time": (str, int), "competition": (int, str, str, int), "edge": (str, str, int)}[sort]
        if len(key) != len(shapes) or not all(isinstance(v, t) and not isinstance(v, bool) for v, t in zip(key, shapes,
                                                                                                          strict=True)):
            raise ValueError("a cursor of another shape")
        if sort == "edge":
            key[0] = Decimal(key[0])
        return tuple(key)
    except (ValueError, TypeError, binascii.Error, InvalidOperation, UnicodeDecodeError) as exc:
        raise ApiError(422, "invalid_cursor", "the cursor is not one this board gave") from exc


def _board_params(query: BoardQuery, market: Market, definitions: Mapping[int, int], moment: datetime,
                  fixtures: list[int] | None) -> dict[str, Any]:
    defs = [definitions[s.bet_id] for s in market.specs_of(query.period) if s.bet_id in definitions]
    line = query.line if market.has_line else None
    return {**Window(query.hours, query.country, query.competition).params(moment), "defs": defs, "fixtures": fixtures,
            "q": _like(query.q), "line": None if line is None else format_number(line), "odds_min": query.odds_min,
            "odds_max": query.odds_max, "fair_only": query.fair_only,
            "bookmaker": None if query.bookmaker is None else str(query.bookmaker), "min_books": query.min_books}


def _market_info(conn: Conn, market: Market, definitions: Mapping[int, int], window: Window,
                 moment: datetime) -> OddsMarketInfo:
    pairs = [(definitions[s.bet_id], s.period) for s in market.specs if s.bet_id in definitions]
    rows = repo.market(conn, {**window.params(moment), "defs": [d for d, _ in pairs],
                              "periods": [p for _, p in pairs]}) if pairs else []
    total = next((r for r in rows if r["period"] is None), None)
    periods = [str(r["period"]) for r in rows if r["period"] is not None and int(r["fixtures"]) > 0]
    return _info(market, periods=periods, fixtures=int(total["fixtures"]) if total else 0,
                 max_books=int(total["max_books"]) if total else 0)


def _team(r: Row, side: str) -> TeamBadge:
    return TeamBadge(id=int(r[f"{side}_team_id"]), name=str(r[f"{side}_name"]), logo_url=r[f"{side}_logo"])


def _competition(r: Row) -> CompetitionBadge:
    return CompetitionBadge(id=int(r["competition_id"]), name=str(r["competition_name"]), country=r["competition_country"],
                            logo_url=r["competition_logo"], flag_url=r["competition_flag"])


def _spec_of(market: Market, definitions: Mapping[int, int], definition_id: int, period: str) -> BookSpec:
    for spec in market.specs_of(period):
        if definitions.get(spec.bet_id) == definition_id:
            return spec
    return market.specs_of(period)[0]


@shared(CACHE_SECONDS)
def board(conn: Conn, query: BoardQuery, *, at: datetime | None = None) -> Envelope[OddsBoardPage]:
    """One market's board: a row per match of the window with the line asked for (or each match's main line), the best price
    of each selection, its bookmaker and the fair price where it means something - filtered, ordered and paged here."""
    moment = at or clock_now()
    market = _market(query.market, query.period)
    definitions = _definitions(conn)
    window = Window(query.hours, query.country, query.competition)
    info = _market_info(conn, market, definitions, window, moment)
    keys = repo.board_keys(conn, _board_params(query, market, definitions, moment, None))
    if query.sort == "edge":
        keys = [k for k in keys if k["edge"] is not None and _row_state(k["checked_at"], k["kickoff_at"], moment) == "current"]
    ordered = sorted(keys, key=lambda k: sort_key(k, query.sort))
    total = len(ordered)
    if query.cursor:
        after = decode_cursor(query.cursor, query.sort)
        ordered = [k for k in ordered if sort_key(k, query.sort) > after]
    limit = max(1, min(query.limit, MAX_LIMIT))
    page = ordered[:limit]
    next_cursor = encode_cursor(query.sort, sort_key(page[-1], query.sort)) if len(ordered) > limit else None
    ids = [int(k["fixture_id"]) for k in page]
    details = {int(r["fixture_id"]): r for r in
               repo.board_page(conn, _board_params(query, market, definitions, moment, ids))} if ids else {}
    rows: list[OddsBoardRow] = []
    competitions: dict[int, CompetitionBadge] = {}
    bookmaker_ids: set[int] = set()
    for fixture_id in ids:
        r = details.get(fixture_id)
        if r is None:  # the book moved between the two reads: the row is left out of this page, never shown half
            continue
        spec = _spec_of(market, definitions, int(r["definition_id"]), query.period)
        state = _row_state(r["checked_at"], r["kickoff_at"], moment)
        grp = r["grp"]
        selections = [selection_price(spec, grp["line"], s, state=state, kickoff_at=r["kickoff_at"], moment=moment)
                      for s in grp["sels"]]
        bookmaker_ids.update(s.bookmaker_id for s in selections)
        competitions.setdefault(int(r["competition_id"]), _competition(r))
        rows.append(OddsBoardRow(
            fixture_id=fixture_id, kickoff_at=r["kickoff_at"], competition_id=int(r["competition_id"]),
            home=_team(r, "home"), away=_team(r, "away"), line=_dec(grp["line"]), lines=[Decimal(x) for x in r["lines"]],
            selections=selections, captured_at=r["captured_at"], provider_update_at=r["provider_update_at"], state=state))
    body = OddsBoardPage(market=info, period=cast(Period, query.period), rows=rows, total=total, next_cursor=next_cursor,
                         competitions=sorted(competitions.values(), key=lambda c: (c.name, c.id)),
                         bookmakers=_bookmakers(conn, bookmaker_ids), generated_at=moment)
    if not rows:
        return unavailable(body, "no_rows_match", status=DataStatus.EMPTY, count=0, total=body.total)
    return ok(body, count=len(rows), total=body.total, next_cursor=next_cursor,
              data_as_of=max(row.captured_at for row in rows))


# ── /matches/{id}/odds-book ───────────────────────────────────────────────────────────────────────────────────────


def _book_line(spec: BookSpec, group: Mapping[str, Any], *, state: str, kickoff_at: datetime,
               moment: datetime) -> OddsBookLine:
    sels = list(group["sels"])
    selections = [selection_price(spec, group["line"], s, state=state, kickoff_at=kickoff_at, moment=moment) for s in sels]
    books = sorted({int(b) for s in sels for b in s["odds"]})
    return OddsBookLine(line=_dec(group["line"]), selections=selections, books=[
        OddsBookPrices(bookmaker_id=b, odds=[_dec(s["odds"].get(str(b))) for s in sels]) for b in books])


@shared(CACHE_SECONDS)
def match_book(conn: Conn, fixture_id: int, *, family: str | None = None,
               at: datetime | None = None) -> Envelope[MatchOddsBook]:
    """A match's whole book (or one family of it): every market and period with prices, every line, each selection's best
    price and every bookmaker's."""
    moment = at or clock_now()
    if family is not None and family not in {m.family for m in index().markets}:
        raise ApiError(422, "unknown_family", f"no family {family!r} in the taxonomy")
    fixture = repo.fixture(conn, fixture_id)
    if fixture is None:
        raise ApiError(404, "not_found", f"fixture {fixture_id} not found")
    rows = repo.match_rows(conn, fixture_id)
    kickoff: datetime = fixture["kickoff_at"]
    checked = min((r["checked_at"] for r in rows), default=None)
    state: BookState = freshness.book_state(checked_at=checked, kickoff_at=kickoff, now=moment, points=schedule_points(),
                                            tolerance=tolerance())
    chosen: dict[tuple[str, str, str], tuple[BookSpec, Row]] = {}
    for r in rows:  # by bet id: an alias (307 beside 339) keeps the lower id's row
        market = index().by_bet.get(int(r["bet_id"]))
        if market is None or (family is not None and market.family != family):
            continue
        spec = next(s for s in market.specs if s.bet_id == int(r["bet_id"]))
        chosen.setdefault((market.family, market.key, spec.period), (spec, r))
    periods_of: dict[tuple[str, str], set[str]] = defaultdict(set)
    books_of: dict[tuple[str, str], int] = defaultdict(int)
    for (fam, key, period), (_, r) in chosen.items():
        periods_of[(fam, key)].add(period)
        books_of[(fam, key)] = max(books_of[(fam, key)], int(r["books"] or r["summary"].get("books", 0)))
    by_family: dict[str, list[OddsBookMarket]] = defaultdict(list)
    bookmaker_ids: set[int] = set()
    rank = index().rank
    for (fam, key, period), (spec, r) in sorted(chosen.items(), key=lambda kv: (
            rank[(kv[0][0], kv[0][1])], PERIODS.index(kv[0][2]))):
        market = index().by_bet[spec.bet_id]
        lines = [_book_line(spec, g, state=state, kickoff_at=kickoff, moment=moment) for g in r["summary"]["lines"]]
        for line in lines:
            bookmaker_ids.update(b.bookmaker_id for b in line.books)
        info = _info(market, periods=sorted(periods_of[(fam, key)]), fixtures=1, max_books=books_of[(fam, key)])
        by_family[fam].append(OddsBookMarket(info=info, period=cast(Period, period),
                                             main_line=_dec(r["summary"].get("main")), lines=lines))
    families_out = [OddsBookFamily(key=fam, markets=markets) for fam, markets in by_family.items()]
    lead = rows[0] if rows else None
    body = MatchOddsBook(fixture_id=fixture_id, kickoff_at=kickoff, captured_at=lead["captured_at"] if lead else None,
                         provider_update_at=lead["provider_update_at"] if lead else None, state=state,
                         families=families_out, bookmakers=_bookmakers(conn, bookmaker_ids))
    if not families_out:
        return unavailable(body, "no_prices_in_force" if state == "none" else "no_prices_in_family",
                           status=DataStatus.EMPTY, count=0)
    return ok(body, count=sum(len(f.markets) for f in families_out), data_as_of=body.captured_at)


# ── /odds/fixtures/{id}/movement ──────────────────────────────────────────────────────────────────────────────────


def read_of(spec: BookSpec, selection: str, line: Decimal) -> Read:
    """A stored price (``odds_snapshots`` / ``odds_quotes``: the selection and ITS line, 0 without one) as ``tax-v3`` reads it:
    an Asian handicap's away side is grouped under the home line (-its own)."""
    if spec.reader == "signed_line":
        own = Decimal(0) if line == 0 else line
        return Read(selection, own, own if selection == "Home" else (Decimal(0) if own == 0 else -own))
    if spec.has_line:
        return Read(selection, line, line)
    return Read(selection, None, None)


def movement_points(spec: BookSpec, rows: Sequence[Mapping[str, Any]], line: Decimal | None) -> dict[
        tuple[str, Decimal | None], list[OddsMovementPoint]]:
    """(selection, own line) -> the best price at each capture of the line followed, outliers left out: a price more than 25 %
    above the market's fair price of that capture (``book.summarize``, the book's own rule) is not a price to follow; without a
    fair price (fewer than three complete bookmakers) the best price stands."""
    by_instant: dict[datetime, list[tuple[int, Read, Decimal]]] = defaultdict(list)
    for r in rows:
        by_instant[r["captured_at"]].append((int(r["bookmaker"]), read_of(spec, str(r["selection"]), Decimal(r["line"])),
                                             Decimal(r["odds"])))
    wanted = None if line is None else float(line)
    series: dict[tuple[str, Decimal | None], list[OddsMovementPoint]] = defaultdict(list)
    for instant in sorted(by_instant):
        summary = book.summarize(spec, by_instant[instant])
        for group in summary["lines"]:
            if group["line"] != wanted or group.get("ways") == 3:
                continue
            for sel in group["sels"]:
                odds = {int(b): float(o) for b, o in sel["odds"].items()}
                if "p" in sel:
                    odds = {b: o for b, o in odds.items() if o * float(sel["p"]) - 1.0 <= book.OUTLIER_EDGE}
                if not odds:
                    continue
                best_bk = min(odds, key=lambda b: (-odds[b], b))
                own = _dec(sel.get("line", group["line"]))
                series[(str(sel["sel"]), own)].append(OddsMovementPoint(
                    at=instant, best_odds=Decimal(str(odds[best_bk])), bookmaker_id=best_bk, n_books=len(odds)))
    return series


def _history_line(rows: Sequence[Mapping[str, Any]], spec: BookSpec) -> Decimal | None:
    """The line quoted most often in the history (by group), for a match the book no longer holds."""
    counts: dict[Decimal | None, int] = defaultdict(int)
    for r in rows:
        counts[read_of(spec, str(r["selection"]), Decimal(r["line"])).group] += 1
    return min(counts, key=lambda g: (-counts[g], abs(g) if g is not None else 0, g or 0)) if counts else None


@shared(MOVEMENT_SECONDS)
def movement(conn: Conn, fixture_id: int, *, market_key: str, period: str = "FT", line: Decimal | None = None,
             at: datetime | None = None) -> Envelope[OddsMovement]:
    """The best price of each selection over the stored history of one line: the capture's own series for the five classic
    markets (``odds_snapshots``), the price clock's for the 55 extracted types (``odds_quotes``); outliers left out. A type with
    neither has no history: ``available`` false."""
    market = _market(market_key, period)
    fixture = repo.fixture(conn, fixture_id)
    if fixture is None:
        raise ApiError(404, "not_found", f"fixture {fixture_id} not found")
    kickoff: datetime = fixture["kickoff_at"]
    specs = market.specs_of(period)
    spec = specs[0]
    classic = CLASSIC_MARKETS.get(spec.bet_id)
    source: str | None = None
    rows: list[Row] = []
    if classic is not None:
        source = "snapshots"
        rows = repo.snapshot_series(conn, fixture_id, classic, kickoff)
    else:
        extracted = repo.extracted(conn, [s.bet_id for s in specs])
        if extracted:
            source = "quotes"
            rows = repo.quote_series(conn, fixture_id, sorted(extracted.values()), kickoff, kickoff - LOOKBACK)
    followed = line if market.has_line else None
    if market.has_line and followed is None:
        definitions = _definitions(conn)
        held = repo.main_line(conn, fixture_id, [definitions[s.bet_id] for s in specs if s.bet_id in definitions])
        followed = _dec(held) if held is not None else _history_line(rows, spec)
    series = movement_points(spec, rows, followed) if rows else {}
    out = [OddsMovementSeries(selection=sel, line=own, points=points) for (sel, own), points in series.items()]
    ids = {p.bookmaker_id for s in out for p in s.points}
    body = OddsMovement(fixture_id=fixture_id, market=market.key, period=cast(Period, period), line=followed,
                        available=source is not None, source=cast(Any, source), series=out,
                        bookmakers=_bookmakers(conn, ids))
    if source is None:
        return unavailable(body, "no_history_for_this_type")
    if not out:
        return unavailable(body, "no_history_for_this_match", status=DataStatus.EMPTY, count=0)
    return ok(body, count=len(out), data_as_of=max(p.at for s in out for p in s.points))


# ── /admin/odds/health ────────────────────────────────────────────────────────────────────────────────────────────


def _brake_gb() -> float:
    from fbi.odds.quote_extract import DEFAULT_MAX_TABLE_GB

    try:
        return float(os.environ.get("FBI_QUOTES_MAX_TABLE_GB", str(DEFAULT_MAX_TABLE_GB)))
    except ValueError:
        return DEFAULT_MAX_TABLE_GB


@shared(CACHE_SECONDS)
def health(conn: Conn, *, at: datetime | None = None) -> Envelope[OddsHealth]:
    """The owner's «Salud de cuotas»: by horizon, the followed matches, those with a book, the age of their prices and the stale
    ones; the extractor's lag; the book's size; today's quota as we count it and as the provider says it; the DEFAULT partitions;
    the price clock's size against its brake. Database only."""
    from fbi.odds.quote_extract import SKIPPED_JOB, table_bytes
    from fbi.providers.quota import read_reported, read_usage

    moment = at or clock_now()
    points, tol = schedule_points(), tolerance()
    fixtures = repo.health_fixtures(conn, since=moment, until=moment + timedelta(hours=72))
    horizons: list[OddsHorizonHealth] = []
    for name, low, high in HORIZONS:
        held = [f for f in fixtures if moment + timedelta(hours=low) <= f["kickoff_at"] < moment + timedelta(hours=high)]
        booked = [f for f in held if f["checked_at"] is not None]
        ages = [(moment - f["checked_at"]).total_seconds() / 60.0 for f in booked]
        stale = sum(1 for f in booked if freshness.price_state(checked_at=f["checked_at"], kickoff_at=f["kickoff_at"],
                                                               now=moment, points=points, tolerance=tol) == "stale")
        horizons.append(OddsHorizonHealth(horizon=cast(Any, name), fixtures=len(held), with_book=len(booked),
                                          median_age_min=round(statistics.median(ages)) if ages else None, stale=stale))
    oldest = repo.extraction_oldest(conn, since=moment - EXTRACTION_LOOKBACK, skipped=SKIPPED_JOB)
    size = repo.book_size(conn)
    usage = read_usage(conn, budget=settings.provider_plan.effective_budget)
    reported = read_reported(conn, day=moment.date())
    body = OddsHealth(
        by_horizon=horizons,
        extraction_lag_min=0 if oldest is None else max(0, round((moment - oldest).total_seconds() / 60.0)),
        book_rows=int(size["book_rows"]), book_mb=round(int(size["book_bytes"]) / 1e6, 2), quota_today=usage.spent,
        quota_limit=usage.budget,
        provider_requests_remaining=reported.requests_remaining if reported is not None else None,
        default_partition_rows=repo.default_partition_rows(conn, cap=DEFAULT_PARTITION_CAP),
        odds_quotes_gb=round(table_bytes(conn) / 1e9, 3), odds_quotes_brake_gb=_brake_gb())
    return ok(body)


# ── /odds/status ──────────────────────────────────────────────────────────────────────────────────────────────────


WITHOUT_PRICE_HOURS = 24
WITHOUT_PRICE_SHOWN = 20


@shared(CACHE_SECONDS)
def status(conn: Conn, *, at: datetime | None = None) -> Envelope[OddsStatus]:
    """The reader's «Estado de los precios» (plan maestro UX/UI 2026, decision 4): the judgement of ``health`` - the same
    matches, the same rule of freshness - with what a reader is shown and nothing of the machinery. Database only."""
    moment = at or clock_now()
    points, tol = schedule_points(), tolerance()
    fixtures = repo.status_fixtures(conn, since=moment, until=moment + timedelta(hours=72))
    horizons: list[OddsStatusHorizon] = []
    for name, low, high in HORIZONS:
        held = [f for f in fixtures if moment + timedelta(hours=low) <= f["kickoff_at"] < moment + timedelta(hours=high)]
        booked = [f for f in held if f["checked_at"] is not None]
        stale = sum(1 for f in booked if freshness.price_state(checked_at=f["checked_at"], kickoff_at=f["kickoff_at"],
                                                               now=moment, points=points, tolerance=tol) == "stale")
        horizons.append(OddsStatusHorizon(horizon=cast(Any, name), fixtures=len(held), with_price=len(booked), stale=stale))
    bare = [f for f in fixtures
            if f["checked_at"] is None and f["kickoff_at"] < moment + timedelta(hours=WITHOUT_PRICE_HOURS)]
    read = [f["checked_at"] for f in fixtures if f["checked_at"] is not None]
    body = OddsStatus(
        last_read_at=max(read) if read else None, by_horizon=horizons,
        without_price=[OddsStatusMatch(fixture_id=int(f["id"]), kickoff_at=f["kickoff_at"], home=f["home"], away=f["away"],
                                       competition=f["competition"]) for f in bare[:WITHOUT_PRICE_SHOWN]],
        without_price_total=len(bare), schedule_minutes=sorted(points, reverse=True), tolerance_minutes=tol)
    return ok(body, data_as_of=max(read) if read else None)
