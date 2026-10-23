"""The calendar of a match over HTTP (plan F4). Reading only.

* ``GET /matches/{fixture_id}/calendar`` (product) - what each team has played and has coming in every competition, and how sure
  that is. Context, not a pick: no price, no probability. Shown to users only once the owner decides (``FBI_CALENDAR_USERS``);
  until then it answers ``not_available``. ``preview=shadow`` (SUPER_ADMIN only) shows it either way.

No route here fetches anything from the provider or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.match_calendar import MatchCalendar
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import match_calendar
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["calendar"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the calendar whether or not users are shown it yet. Never a user's view.")]


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/calendar", response_model=Envelope[MatchCalendar | None])
def get_match_calendar(conn: Db, principal: App, fixture_id: FixtureId,
                       preview: Preview = None) -> Envelope[MatchCalendar | None]:
    """CALENDARIO: per team, the days since its last match, the matches of the last fortnight and month, the last matches played
    and the next ones, in every competition it plays - and whether the list behind it is whole."""
    return match_calendar.match_calendar(conn, fixture_id, preview=_preview(preview, principal))
