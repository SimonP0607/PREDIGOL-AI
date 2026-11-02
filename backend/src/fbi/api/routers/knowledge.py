"""A finished match put together as one object, over HTTP (plan F7). Reading only.

* ``GET /matches/{fixture_id}/knowledge`` (product) - what happened in the match, layer by layer: the result, the statistics of the
  teams, the events, the players, the tactics and the story of the score, and the market from its opening to its close. Facts of a
  match that is over, with how far each layer can be trusted; no pick, no forecast and no recommendation. Shown to users only once the
  owner decides (``FBI_KNOWLEDGE_USERS``); until then it answers ``not_available``. ``preview=shadow`` (SUPER_ADMIN only) shows it either
  way, with the row as stored (the picks and post-mortems among its layers) and the chain of rebuilds.

No route here builds a row, calls the provider or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.knowledge import MatchKnowledge
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import knowledge
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["knowledge"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the knowledge whether or not users are shown it yet, with the row as stored and the chain of "
                "rebuilds. Never a user's view.")]


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/knowledge", response_model=Envelope[MatchKnowledge | None])
def get_match_knowledge(conn: Db, principal: App, fixture_id: FixtureId,
                        preview: Preview = None) -> Envelope[MatchKnowledge | None]:
    """POSTPARTIDO: a finished match as PrediGol put it together once the provider had had its last look at it - what happened, in
    layers, each one saying how far it can be trusted. A match that is not over, not settled or not followed says so."""
    return knowledge.match_knowledge(conn, fixture_id, preview=_preview(preview, principal))
