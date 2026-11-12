"""The odds explorer (plan Cuotas, ola 2, BE-011): families, a market's board, a match's book, the movement of a line, and the
owner's health panel. Read from the current-price book and the stored history, kept in the shared cache: no reader ever causes a
request to the provider. The product tier (like ``/odds/best``, which stays until the web switch ``FBI_ODDS_EXPLORER`` is on and
verified); the health panel is SUPER_ADMIN's."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.odds_explorer import (
    MatchOddsBook,
    OddsBoardPage,
    OddsFamilies,
    OddsHealth,
    OddsMovement,
    OddsStatus,
    Sort,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.services import odds_explorer
from fbi.api.switches import odds_status_on

router = APIRouter(tags=["odds explorer"])
admin_router = APIRouter(tags=["admin: odds"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]

Hours = Annotated[int, Query(ge=1, le=72, description="Matches kicking off in the next N hours (24, 48 or 72 on the page).")]
Country = Annotated[str | None, Query(min_length=1, max_length=60, description="The competition's country, as it is named.")]
Competition = Annotated[int | None, Query(ge=1, le=2**31, description="A competition id.")]
MarketKey = Annotated[str, Query(min_length=3, max_length=80, pattern=r"^[a-z0-9_.]+$",
                                 description="A market key of /odds/families (corners.total, goals.total.home ...).")]
PeriodQ = Annotated[Literal["FT", "1H", "2H", "INTERVAL"], Query(description="FT, 1H, 2H or INTERVAL.")]
LineQ = Annotated[str | None, Query(max_length=9, pattern=r"^(main|-?\d{1,3}(\.\d{1,2})?)$",
                                    description="A line (an Asian handicap's: the home line) or main: each match's main "
                                                "line.")]
Fixture = Annotated[int, Path(ge=1, le=2**62)]


def _line(value: str | None) -> Decimal | None:
    if value is None or value == "main":
        return None
    try:
        line = Decimal(value)
    except InvalidOperation as exc:  # the pattern lets nothing else through; kept for the type
        raise ApiError(422, "invalid_line", "a line is a number or main") from exc
    if (line * 4) % 1 != 0:
        raise ApiError(422, "invalid_line", "a line is a multiple of 0.25")
    return Decimal(0) if line == 0 else line


@router.get("/odds/families", response_model=Envelope[OddsFamilies])
def get_odds_families(conn: Db, hours: Hours = 24, country: Country = None,
                      competition: Competition = None) -> Envelope[OddsFamilies]:
    """The families and markets with prices in the window: how many matches each has and the most bookmakers in one match.
    Only what has prices; in the explorer's order."""
    return odds_explorer.families(conn, hours=hours, country=country, competition=competition)


@router.get("/odds/board", response_model=Envelope[OddsBoardPage])
def get_odds_board(
    conn: Db,
    market: MarketKey,
    period: PeriodQ = "FT",
    line: LineQ = None,
    hours: Hours = 24,
    country: Country = None,
    competition: Competition = None,
    q: Annotated[str | None, Query(max_length=60, description="Part of a team's or a competition's name.")] = None,
    bookmaker: Annotated[int | None, Query(ge=1, le=2**31, description="Only the matches this bookmaker (the provider's "
                                                                       "id) quotes at the line shown.")] = None,
    min_books: Annotated[int | None, Query(ge=1, le=100, description="At least this many bookmakers at the line.")] = None,
    odds_min: Annotated[Decimal | None, Query(ge=1, le=1000, description="A selection's best price at least this.")] = None,
    odds_max: Annotated[Decimal | None, Query(ge=1, le=1000, description="A selection's best price at most this.")] = None,
    fair_only: Annotated[bool, Query(description="Only the rows with a fair price.")] = False,
    sort: Annotated[Sort, Query(description="time; competition (PrediGol's competition priority, comp-priority-v1); edge "
                                            "(the widest difference with the fair price first, current prices only).")]
    = "time",
    cursor: Annotated[str | None, Query(max_length=400, pattern=r"^[A-Za-z0-9_\-]+$")] = None,
    limit: Annotated[int, Query(ge=1, le=odds_explorer.MAX_LIMIT)] = 20,
) -> Envelope[OddsBoardPage]:
    """One market's board across the window's matches: a row per match with the line asked for (or each match's main line),
    each selection's best price, its bookmaker, how many quote it and - where it means something - the fair price, with the
    row's freshness. Filtered, ordered and paged on the server (``next_cursor``)."""
    if odds_min is not None and odds_max is not None and odds_min > odds_max:
        raise ApiError(422, "invalid_filters", "odds_min is above odds_max")
    query = odds_explorer.BoardQuery(
        market=market, period=period, line=_line(line), hours=hours, country=country, competition=competition, q=q,
        bookmaker=bookmaker, min_books=min_books, odds_min=odds_min, odds_max=odds_max, fair_only=fair_only, sort=sort,
        cursor=cursor, limit=limit)
    return odds_explorer.board(conn, query)


@router.get("/matches/{fixture_id}/odds-book", response_model=Envelope[MatchOddsBook])
def get_match_odds_book(
    conn: Db, fixture_id: Fixture,
    family: Annotated[str | None, Query(min_length=2, max_length=40, pattern=r"^[a-z_]+$",
                                        description="One family of the book; none: every family.")] = None,
) -> Envelope[MatchOddsBook]:
    """A match's book in force: every market and period with prices (or one family's), every line, each selection's best price
    and every bookmaker's, and the book's freshness."""
    return odds_explorer.match_book(conn, fixture_id, family=family)


@router.get("/odds/fixtures/{fixture_id}/movement", response_model=Envelope[OddsMovement])
def get_odds_movement(conn: Db, fixture_id: Fixture, market: MarketKey, period: PeriodQ = "FT",
                      line: LineQ = None) -> Envelope[OddsMovement]:
    """The best price of each selection of one line over the stored history, outliers left out: the capture's series for the
    five classic markets, the price clock's for the 55 extracted types; ``available`` false for the others."""
    return odds_explorer.movement(conn, fixture_id, market_key=market, period=period, line=_line(line))


@router.get("/odds/status", response_model=Envelope[OddsStatus])
def get_odds_status(conn: Db) -> Envelope[OddsStatus]:
    """«Estado de los precios» (plan maestro UX/UI 2026, decision 4): when the prices were last read, how many matches have one
    and how many are late, by the rule of freshness in force. Read only; behind ``FBI_ODDS_STATUS`` (404 while it is off)."""
    if not odds_status_on():
        raise ApiError(404, "not_found", "not found")
    return odds_explorer.status(conn)


@admin_router.get("/odds/health", response_model=Envelope[OddsHealth])
def get_odds_health(conn: Db) -> Envelope[OddsHealth]:
    """«Salud de cuotas»: prices by horizon (matches, with a book, median age, stale), the extractor's lag, the book's size,
    today's quota (ours and the provider's), the DEFAULT partitions and the price clock against its brake."""
    return odds_explorer.health(conn)
