"""«Explícame» over HTTP (plan UX, B9). Reading only.

* ``GET /explain?entity=match|pick&id=&intent=`` (product) - the answer to one frequent question of a match or a pick, from
  what PrediGol already keeps: the structured reading (A9), the forecast, the pick's state and explanation (B3). Lines are
  stable codes and the reading's facts; the web words them in the reader's language.
* ``POST /explain/parlay`` (product) - «¿Por qué baja la probabilidad de mi parlay?» for the legs the slip holds, checked as
  ``POST /me/parlays/validate`` checks them. Nothing is stored.

``FBI_EXPLAIN=0`` takes both away (404; ``/auth/me`` says ``explain: false``). ``preview=shadow`` (SUPER_ADMIN only) answers
as the owner's preview reads a match or a pick. At most 30 questions a minute per account.

No route here calls an AI, estimates anything or can change a pick: every number is one PrediGol already stored or the slip's
own check computes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query

from fbi.api.contracts.explain import ExplainIntent, Explanation, SlipIn
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.limits import SlidingWindow
from fbi.api.security import App
from fbi.api.services import explain
from fbi.api.switches import explain_on
from fbi.auth.roles import Permission
from fbi.auth.service import Principal
from fbi.userdata.records import LegIn

router = APIRouter(prefix="/explain", tags=["explain"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the answer as the owner's preview reads the match or the pick (evaluation picks, the "
                "reading whatever its switch says). Never a reader's view.")]
LIMIT = SlidingWindow(per_window=30, window_s=60.0)
"""Questions per account per minute (per API process): a reader asks a few; a loop over every match is stopped here."""


def _door(principal: Principal) -> None:
    if not explain_on():
        raise ApiError(404, "explain_off", "«Explícame» is off")
    if not LIMIT.allow(str(principal.user_id)):
        raise ApiError(429, "rate_limited", "too many questions for this account", headers={"retry-after": "30"})


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("", response_model=Envelope[Explanation])
def get_explanation(
    conn: Db,
    principal: App,
    entity: Annotated[Literal["match", "pick"], Query(description="What the question is about.")],
    item_id: Annotated[int, Query(alias="id", ge=1, le=2**62, description="The match or the pick.")],
    intent: Annotated[ExplainIntent, Query(description="match: no_pick, forecast, risks. pick: risks, caution.")],
    preview: Preview = None,
) -> Envelope[Explanation]:
    """The answer to one question of a match or a pick: the lines (codes and the reading's facts), whether PrediGol had
    what the question needs (``answered=false``: the lines say what is missing, never a guess), the glossary's terms and
    where to read more. A pick a reader may not see is 404, as on its own page; a question that is not the place's is 422."""
    _door(principal)
    return explain.explain(conn, entity, item_id, intent, preview=_preview(preview, principal))


@router.post("/parlay", response_model=Envelope[Explanation])
def explain_parlay(body: SlipIn, conn: Db, principal: App) -> Envelope[Explanation]:
    """«¿Por qué baja la probabilidad de mi parlay?» for the parlay being built: every leg must win, each leg's
    probability, their product and the adjustment when legs depend on each other - the numbers of the slip's own check."""
    _door(principal)
    legs = [LegIn(fixture_id=leg.fixture_id, market_key=leg.market_key, selection=leg.selection, line=leg.line,
                  odds=leg.odds) for leg in body.legs]
    return explain.explain_slip(conn, legs)
