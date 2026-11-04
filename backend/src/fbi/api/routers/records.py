"""The day's board, a user's own picks and parlays, and the user's history.

``GET /daily`` is what PrediGol chose for a product day, as persisted: the picks frozen at
selection, the daily and multi-day parlays, each with its result once settled. A user sees
the qualified records only; ``preview=shadow`` (the Admin Console) shows the evaluation
records built from shadow picks, labelled as such.

``/me/*`` is the signed-in user's own: picks they saved (a snapshot of what we showed), the
parlays they built (validated before they are stored), and their history.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Response

from fbi.api.contracts.mypicks import Band, Origin, PicksSummary, Result
from fbi.api.contracts.records import (
    DailyBoard,
    History,
    ParlayIn,
    ParlayValidation,
    SavePickIn,
    UserOddsIn,
    UserParlay,
    UserPick,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import mypicks, records
from fbi.api.services.pick_filter import FilterError, PickFilter
from fbi.auth.roles import Permission
from fbi.auth.service import Principal
from fbi.core.clock import now
from fbi.userdata import records as userdata
from fbi.userdata.db import write_connection

router = APIRouter(tags=["records"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the evaluation records built from shadow picks. Never a user's view.")]


def _shadow(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


def _refused(exc: userdata.RecordError) -> ApiError:
    status = 404 if exc.code in ("unknown_fixture", "unknown_pick") else 409 if exc.code == "already_saved" else 422
    return ApiError(status, exc.code, str(exc))


@router.get("/daily", response_model=Envelope[DailyBoard])
def get_daily(conn: Db, principal: App, preview: Preview = None,
              day: Annotated[date | None, Query(description="Product day (America/Bogota); today if omitted.")] = None
              ) -> Envelope[DailyBoard]:
    """The day's picks (up to five, frozen when chosen) and its daily and multi-day parlays, with results."""
    return records.daily_board(conn, day=day, include_shadow=_shadow(preview, principal))


Cursor = Annotated[str | None, Query(max_length=200, description=(
    "The `meta.next_cursor` of the previous page; omitted for the first page."))]


def _cursor_refused(exc: records.CursorError) -> ApiError:
    return ApiError(422, "invalid_cursor", str(exc))


def pick_filter_of(
    result: Annotated[Result | None, Query(description="pending, won (a half win too), lost (a half loss too), push or void.")] = None,
    market: Annotated[str | None, Query(max_length=8, description="A kind of bet: 1X2, OU, BTTS, AH or DC.")] = None,
    competition: Annotated[int | None, Query(ge=1, description="A league's id (meta of /me/picks/summary: options).")] = None,
    origin: Annotated[Origin | None, Query(description="predigol: PrediGol's picks the reader saved; mine: their own.")] = None,
    band: Annotated[Band | None, Query(description="The odds range of the price the reader counts.")] = None,
    since: Annotated[date | None, Query(description="The first day of the matches, in the reader's time zone.")] = None,
    until: Annotated[date | None, Query(description="The last day of the matches, in the reader's time zone.")] = None,
    q: Annotated[str | None, Query(max_length=60, description="Found in the teams' or the league's names, without accents.")] = None,
) -> PickFilter:
    """The filter of Mis picks (plan UX, B5): the same for the list, its totals and breakdown, and its CSV."""
    try:
        return PickFilter.of(result=result, market=market, competition=competition, origin=origin, band=band,
                             since=since, until=until, search=q)
    except FilterError as exc:
        raise ApiError(422, "invalid_filter", str(exc)) from exc


Filter = Annotated[PickFilter, Depends(pick_filter_of)]


@router.get("/me/picks", response_model=Envelope[list[UserPick]])
def get_my_picks(conn: Db, principal: App, flt: Filter,
                 status: Annotated[Literal["open", "settled"] | None, Query()] = None,
                 limit: Annotated[int, Query(ge=1, le=500)] = 200,
                 cursor: Cursor = None) -> Envelope[list[UserPick]]:
    """The user's saved picks, newest kick-off first, a page at a time: `meta.total` counts all of them (with the
    filter) and `meta.next_cursor` leads to the next page."""
    try:
        return records.user_picks(conn, user_id=principal.user_id, status=status, limit=limit, cursor=cursor, flt=flt,
                                  tz=principal.timezone)
    except records.CursorError as exc:
        raise _cursor_refused(exc) from exc


@router.get("/me/picks/summary", response_model=Envelope[PicksSummary])
def get_my_picks_summary(conn: Db, principal: App, flt: Filter) -> Envelope[PicksSummary]:
    """The reader's saved picks under the filter (plan UX, B5): totals, by kind of bet, by league and by odds range, always
    with their sample (units, ROI, hit rate and margin from 25 settled picks), the line value of their prices, and the
    filter's choices from their own picks."""
    return ok(mypicks.summary(conn, user_id=principal.user_id, flt=flt, tz=principal.timezone))


def _csv(body: str, kind: str) -> Response:
    return Response(content=body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"content-disposition": f'attachment; filename="{mypicks.filename(kind)}"',
                             "cache-control": "no-store"})


@router.get("/me/picks/export", response_class=Response,
            responses={200: {"content": {"text/csv": {}}, "description": "The reader's saved picks, as CSV."}})
def export_my_picks(conn: Db, principal: App, flt: Filter) -> Response:
    """Every saved pick of the reader under the filter, as a CSV file (plan UX, B5: the reader's own data - still readable
    with a limited membership). Times in the reader's time zone, headings in their language."""
    return _csv(mypicks.picks_csv(conn, user_id=principal.user_id, flt=flt, tz=principal.timezone,
                                  language=principal.language), "picks")


@router.get("/me/parlays/export", response_class=Response,
            responses={200: {"content": {"text/csv": {}}, "description": "The reader's parlays, as CSV."}})
def export_my_parlays(conn: Db, principal: App) -> Response:
    """Every parlay of the reader, one line per leg, as a CSV file (plan UX, B5)."""
    return _csv(mypicks.parlays_csv(conn, user_id=principal.user_id, tz=principal.timezone,
                                    language=principal.language), "parlays")


@router.post("/me/picks", response_model=Envelope[dict[str, Any]], status_code=201)
def save_my_pick(body: SavePickIn, principal: App) -> Envelope[dict[str, Any]]:
    """Save a selection: from one of PrediGol's picks (``pick_id``) or straight from the market."""
    try:
        with write_connection() as conn:
            saved = userdata.save_pick(
                conn, user_id=principal.user_id, fixture_id=body.fixture_id, market_key=body.market_key,
                selection=body.selection, line=body.line, at=now(), pick_id=body.pick_id, user_odds=body.user_odds,
                allow_shadow=principal.can(Permission.SHADOW_PREVIEW))
    except userdata.RecordError as exc:
        raise _refused(exc) from exc
    return ok(saved)


@router.delete("/me/picks/{record_id}", status_code=204)
def remove_my_pick(principal: App, record_id: Annotated[int, Path(ge=1)]) -> Response:
    """Only before the match starts: after kick-off a saved pick is history."""
    try:
        with write_connection() as conn:
            userdata.remove_pick(conn, user_id=principal.user_id, record_id=record_id, at=now())
    except userdata.RecordError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.patch("/me/picks/{record_id}", status_code=204)
def set_my_odds(body: UserOddsIn, principal: App, record_id: Annotated[int, Path(ge=1)]) -> Response:
    """The price the user got at their own bookmaker, until the match starts."""
    try:
        with write_connection() as conn:
            userdata.set_user_odds(conn, user_id=principal.user_id, record_id=record_id, user_odds=body.user_odds,
                                   at=now())
    except userdata.RecordError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


def _legs(body: ParlayIn) -> list[userdata.LegIn]:
    return [userdata.LegIn(fixture_id=leg.fixture_id, market_key=leg.market_key, selection=leg.selection,
                           line=leg.line, odds=leg.odds) for leg in body.legs]


@router.post("/me/parlays/validate", response_model=Envelope[ParlayValidation])
def validate_my_parlay(body: ParlayIn, conn: Db, principal: App) -> Envelope[ParlayValidation]:
    """Check a parlay against the rules without storing it."""
    v = userdata.validate_parlay(conn, _legs(body), at=now())
    return ok(ParlayValidation(ok=v.ok, errors=v.errors, warnings=v.warnings, legs=v.legs,
                               combined_odds=v.combined_odds, fair_probability=v.fair_probability,
                               model_probability=v.model_probability, expected_value=v.expected_value,
                               risk=v.risk, n_legs=len(v.legs), correlation=v.correlation,  # type: ignore[arg-type]
                               estimated_probability=v.estimated_probability, dependency=v.dependency))


@router.post("/me/parlays", response_model=Envelope[dict[str, Any]], status_code=201)
def build_my_parlay(body: ParlayIn, principal: App) -> Envelope[dict[str, Any]]:
    try:
        with write_connection() as conn:
            built = userdata.create_parlay(conn, user_id=principal.user_id, name=body.name, legs=_legs(body), at=now())
    except userdata.RecordError as exc:
        raise _refused(exc) from exc
    return ok(built)


@router.delete("/me/parlays/{record_id}", status_code=204)
def remove_my_parlay(principal: App, record_id: Annotated[int, Path(ge=1)]) -> Response:
    """Only before its first match starts: after that a parlay is history."""
    try:
        with write_connection() as conn:
            userdata.remove_parlay(conn, user_id=principal.user_id, record_id=record_id, at=now())
    except userdata.RecordError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.get("/me/parlays", response_model=Envelope[list[UserParlay]])
def get_my_parlays(conn: Db, principal: App,
                   limit: Annotated[int, Query(ge=1, le=200)] = 100,
                   cursor: Cursor = None) -> Envelope[list[UserParlay]]:
    """The user's parlays, newest first, a page at a time (`meta.total`, `meta.next_cursor`)."""
    try:
        return records.user_parlays(conn, user_id=principal.user_id, limit=limit, cursor=cursor)
    except records.CursorError as exc:
        raise _cursor_refused(exc) from exc


@router.get("/me/history", response_model=Envelope[History])
def get_my_history(conn: Db, principal: App, preview: Preview = None,
                   period: Annotated[Literal["today", "7d", "30d", "all"], Query()] = "7d") -> Envelope[History]:
    """PrediGol's picks and parlays next to the user's own, by the day their matches kick off in the user's
    time zone: counts, hit rate and profit at one unit per pick."""
    return records.history(conn, user_id=principal.user_id, period=period, tz=principal.timezone,
                           include_shadow=_shadow(preview, principal))
