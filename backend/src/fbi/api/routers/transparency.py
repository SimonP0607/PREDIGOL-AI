"""«Cómo le va a PrediGol» over HTTP (plan UX, A12). Reading only.

* ``GET /transparency`` (product) - what PrediGol published and how it went in 7 days, 30 days and the whole history, the days
  without picks and why, the results by kind of bet, the line value, the forecast's calibration and what is still in
  evaluation, always with its sample (``fbi.api.services.transparency``). Kept ten minutes per time zone. Readers see it once
  the owner has reviewed it (``FBI_TRANSPARENCY``, P9); until then it answers ``not_available``.
  ``preview=shadow`` (SUPER_ADMIN only) shows it whatever the switch says - the owner's review.

* ``GET /transparency/picks`` (product) - the published picks one by one, newest kick-off first, a page at a time with its
  price, probability and result (``fbi.api.services.transparency_picks``). The same gate and the same preview.

No route here computes a probability, prices a selection or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query

from fbi.api.contracts.transparency import PublishedPick, Transparency
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok, unavailable
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import records, transparency, transparency_picks
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["transparency"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the page while readers do not see it yet (the owner's review, P9).")]


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/transparency", response_model=Envelope[Transparency | None])
def get_transparency(conn: Db, principal: App, preview: Preview = None) -> Envelope[Transparency | None]:
    """CÓMO LE VA A PREDIGOL: the published picks (won, lost, halves, pushed, voided; units, ROI and its margin only from 25
    settled picks), the days without picks and why, by kind of bet, the line value (clv-v1), the forecast's calibration and
    what is in evaluation - counts only, never a selection of it."""
    if not _preview(preview, principal) and not transparency.shown():
        return unavailable(None, "PrediGol's track record is not published yet: the owner reviews it first.")
    return ok(transparency.transparency(conn, tz=principal.timezone))


@router.get("/transparency/picks", response_model=Envelope[list[PublishedPick]])
def get_published_picks(
    conn: Db, principal: App, preview: Preview = None,
    limit: Annotated[int, Query(ge=1, le=transparency_picks.MAX_LIMIT)] = transparency_picks.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=200, description=(
        "The `meta.next_cursor` of the previous page; omitted for the first page."))] = None,
) -> Envelope[list[PublishedPick]]:
    """THE PUBLISHED PICKS one by one: what PrediGol chose, at the price and the probability it was frozen with, and how it
    ended - newest kick-off first, a page at a time (`meta.total` counts all of them, `meta.next_cursor` leads on). Only the
    qualified set: never an evaluation item."""
    if not _preview(preview, principal) and not transparency.shown():
        return unavailable([], "PrediGol's track record is not published yet: the owner reviews it first.")
    try:
        return transparency_picks.published_picks(conn, tz=principal.timezone, limit=limit, cursor=cursor)
    except records.CursorError as exc:
        raise ApiError(422, "invalid_cursor", str(exc)) from exc
