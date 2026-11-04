"""Postpartido over HTTP (plan UX, B4). Reading only.

* ``GET /matches/{fixture_id}/postmatch`` (product) - what a finished match did to what the signed-in reader saved on it (each with its
  result and units once settled) and to every pick PrediGol published for it: how it ended and why, from the match's own facts. Shown to
  readers while they see the knowledge of a finished match (``FBI_KNOWLEDGE_USERS``); ``preview=shadow`` (SUPER_ADMIN only) shows it either
  way and adds the shadow picks.

No route here settles anything, builds a post-mortem or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.postmatch import PostMatch
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import postmatch
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["postmatch"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the Postpartido whether or not readers are shown it yet, with the shadow picks. Never a reader's view.")]


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/postmatch", response_model=Envelope[PostMatch | None])
def get_match_postmatch(conn: Db, principal: App, fixture_id: FixtureId,
                        preview: Preview = None) -> Envelope[PostMatch | None]:
    """POSTPARTIDO: how what you saved on the match ended, and how and why each of PrediGol's published picks did."""
    return postmatch.postmatch(conn, fixture_id, user_id=principal.user_id, preview=_preview(preview, principal))
