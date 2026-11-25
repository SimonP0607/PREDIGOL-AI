"""«Solo fútbol» and the voluntary pause over HTTP (plan PM, PM-14-07, OP-46). Behind ``FBI_WELLBEING`` (off by default): off, 404.

* ``GET /me/wellbeing`` - what the reader chose and whether it is in force now.
* ``PUT /me/wellbeing`` - choose the mode and/or a pause (1, 7 or 30 days). A pause that runs is never shortened (``fbi.customer.wellbeing``).

Never behind the wellbeing guard itself: a reader in the mode can always see and change their choice (their way back). Reading only
what the reader chose; nothing here prices a selection or changes a pick.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from fbi.api.contracts.wellbeing import WellbeingIn, WellbeingState
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services.wellbeing_state import state_of
from fbi.api.switches import wellbeing_on
from fbi.core.clock import now
from fbi.customer import wellbeing
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/me", tags=["wellbeing"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def _gate() -> None:
    if not wellbeing_on():
        raise ApiError(404, "not_found", "not found")


@router.get("/wellbeing", response_model=WellbeingState)
def get_wellbeing(conn: Db, principal: App) -> WellbeingState:
    """LO QUE ELEGISTE: «solo fútbol» and the pause, and whether they are in force now."""
    _gate()
    return state_of(wellbeing.read(conn, principal.user_id))


@router.put("/wellbeing", response_model=WellbeingState)
def put_wellbeing(body: WellbeingIn, conn: Db, principal: App) -> WellbeingState:
    """Choose «solo fútbol» and/or a pause; what is left out stays. A running pause cannot be shortened (409 ``pause_running``)."""
    _gate()
    try:
        return state_of(wellbeing.write(principal.user_id, football_only=body.football_only,
                                        pause_days=body.pause_days, at=now()))
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
