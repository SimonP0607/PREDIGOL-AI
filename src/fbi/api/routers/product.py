"""The product's screens in one request each: home, picks, parlays, best prices.

``preview=shadow`` lays unqualified shadow picks out exactly as a user would see
qualified ones, so the owner can review the design while no model has qualified. It
is refused (403) to every account without the shadow-preview permission, and every
answer says which source it was built from.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query

from fbi.api.contracts.product import BestOddsBoard, Home, Parlay, PicksBoard
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import product
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["product"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: show unqualified shadow picks laid out as the product would. Never a user's view.")]
Market = Annotated[str | None, Query(max_length=10, pattern=r"^(1X2|OU|BTTS|AH|DC)$")]


def _shadow(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/home", response_model=Envelope[Home])
def get_home(conn: Db, principal: App, preview: Preview = None) -> Envelope[Home]:
    """Top picks with value now, the parlay of the day and the multi-day parlay, live matches with the most
    data, best prices against the market, and the next relevant fixtures."""
    return product.home(conn, include_shadow=_shadow(preview, principal))


@router.get("/picks", response_model=Envelope[PicksBoard])
def get_picks(
    conn: Db,
    principal: App,
    preview: Preview = None,
    competition_id: Annotated[int | None, Query(ge=1)] = None,
    market: Market = None,
    min_odds: Annotated[Decimal | None, Query(ge=1, le=1000)] = None,
    max_odds: Annotated[Decimal | None, Query(ge=1, le=1000)] = None,
    hours: Annotated[int, Query(ge=1, le=168)] = 72,
    fixture_id: Annotated[int | None, Query(ge=1)] = None,
) -> Envelope[PicksBoard]:
    """Qualified picks kicking off in the next ``hours``, re-priced at the best price available now; and, in
    ``started``, the pre-match picks of today's matches that already kicked off, as they were taken, with the
    match's state and the result. ``fixture_id``: one match only, whenever it kicks off or kicked off."""
    return product.picks_board(conn, include_shadow=_shadow(preview, principal), competition_id=competition_id,
                               market=market, min_odds=min_odds, max_odds=max_odds, hours=hours,
                               fixture_id=fixture_id)


@router.get("/parlays/{kind}", response_model=Envelope[Parlay])
def get_parlay(conn: Db, principal: App, kind: Literal["daily", "multiday"], preview: Preview = None) -> Envelope[Parlay]:
    """Daily: five legs in the next 24 hours. Multi-day: six or seven legs in the next 48 hours. Every leg must
    pass the value gate; when not enough do, the answer is ``no_valid_parlay`` - never a padded parlay."""
    return product.parlay_board(conn, kind, include_shadow=_shadow(preview, principal))


@router.get("/odds/best", response_model=Envelope[BestOddsBoard])
def get_best_odds(
    conn: Db,
    principal: App,
    preview: Preview = None,
    market: Market = None,
    hours: Annotated[int, Query(ge=1, le=168)] = 48,
) -> Envelope[BestOddsBoard]:
    """The best price per selection for upcoming fixtures, next to the market's fair (de-vigged) price."""
    return product.best_odds_board(conn, hours=hours, market=market, include_shadow=_shadow(preview, principal))
