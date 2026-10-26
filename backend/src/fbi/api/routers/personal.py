"""What a reader's own use orders and suggests, over HTTP (plan UX, B2; section 38).

* ``GET /me/personal`` - the markets the reader consults most, first in a match's «Mercados», with how many times; and one
  league or team they keep opening and do not follow, with its reason («¿Sigues la Serie A? Agrégala»).
* ``POST /me/personal/suggestion/dismiss`` - «No, gracias»: that league or team is never suggested again.
* ``PUT /me/personal/markets`` - the usual order, or the reader's own again.

Accepting a suggestion is saving the favourites with it (``PUT /me/favorites``): nothing is followed without the reader's
tap. Behind the consent gate - it reads what is measured, like ``POST /events`` - and not the membership's. Only the
reader's own; no route here reads or changes a pick, a probability, a state or a price.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from fbi.api.contracts.personal import (
    MarketOrder,
    MarketOrderIn,
    PersonalView,
    Suggestion,
    SuggestionOut,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.core.clock import now
from fbi.customer import favorites, personal
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/me/personal", tags=["personal"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def personal_view(conn: psycopg.Connection[Any], user_id: int) -> PersonalView:
    """The reader's market order and suggestion now. FBI_PERSONALIZATION=0: the usual order and no suggestion."""
    on = favorites.personalization_on()
    at = now()
    common, dismissed = personal.marks(favorites.preferences(conn, user_id).hints_seen)
    subject = personal.subject_now(conn, user_id)
    used = subject if on else None
    order = personal.market_order(conn, used, at=at, common=common)
    own = favorites.chosen(conn, user_id)
    follows = own or favorites.suggested(conn)
    found = personal.suggestion(conn, used, follows, own=own, dismissed=dismissed, at=at)
    return PersonalView(
        personalization=on, counted=subject is not None,
        markets=MarketOrder.model_validate({
            "first": list(order.first), "views": [{"market": m, "views": n} for m, n in order.views],
            "common": common, "window_days": personal.WINDOW_DAYS, "min_views": personal.MIN_VIEWS}),
        suggestion=None if found is None else Suggestion(kind=found.kind, id=found.ref_id, name=found.name,
                                                         matches=found.matches, days=found.days))


@router.get("", response_model=PersonalView)
def get_personal(conn: Db, principal: App) -> PersonalView:
    """TU ORDEN: the markets the reader consulted most in the last 30 days (opened their bookmakers or all their lines, or
    chose one of their prices - two times or more), first in a match's «Mercados»; and one league or team whose matches
    they keep opening outside what they follow (three matches or more, on two days or more), to add with a tap."""
    return personal_view(conn, principal.user_id)


@router.post("/suggestion/dismiss", response_model=PersonalView)
def dismiss_suggestion(body: SuggestionOut, conn: Db, principal: App) -> PersonalView:
    """«No, gracias»: this league or team is never suggested to the reader again (422 for one PrediGol does not follow)."""
    try:
        personal.dismiss_suggestion(conn, principal.user_id, body.kind, body.id, at=now())
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    conn.rollback()  # a fresh snapshot: written by another connection
    return personal_view(conn, principal.user_id)


@router.put("/markets", response_model=PersonalView)
def put_market_order(body: MarketOrderIn, conn: Db, principal: App) -> PersonalView:
    """The markets in the usual order (``common``: true) or in the reader's own again (false)."""
    personal.keep_usual_order(principal.user_id, body.common, at=now())
    conn.rollback()
    return personal_view(conn, principal.user_id)
