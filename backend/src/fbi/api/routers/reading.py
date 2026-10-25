"""The structured reading of a match over HTTP (plan UX, A9). Reading only.

* ``GET /matches/{fixture_id}/reading`` (product) - six sections of facts (summary, context, data, market, risks and PrediGol's
  conclusion), each a code with its parameters and its reference; the web writes them in the reader's language. Shown to
  users unless the owner turns it off (``FBI_READING_USERS=0``: then ``not_available``). ``preview=shadow`` (SUPER_ADMIN
  only) reads it whatever the switch says.

No route here calls an AI, computes a probability or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.reading import MatchReading
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import reading
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["reading"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the reading whatever FBI_READING_USERS says. It is the same reading a user gets.")]


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/reading", response_model=Envelope[MatchReading | None])
def get_match_reading(conn: Db, principal: App, fixture_id: FixtureId,
                      preview: Preview = None) -> Envelope[MatchReading | None]:
    """LECTURA PREDIGOL: what the match is and what is expected, the context, the figures, what the market says (implied
    probability without the bookmakers' margin), the risks - never empty - and the conclusion: the likely outcome of each
    market with its probability, labelled when it is uncalibrated. Facts with their references; no advice."""
    return reading.match_reading(conn, fixture_id, preview=_preview(preview, principal))
