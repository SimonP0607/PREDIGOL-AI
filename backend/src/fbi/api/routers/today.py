"""Today, for Home, over HTTP (plan UX, A9). Reading only.

* ``GET /today`` (product) - the matches from 48 hours ago to 36 hours ahead with PrediGol's result forecast labelled and one line
  of the reading, the leagues suggested until the reader picks theirs, and whether the day has published picks - or why not,
  from the published set's own funnel. The same board for every reader (kept a minute; the reason, five).

No route here computes a probability, prices a selection or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from fbi.api.contracts.today import Today
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.security import App
from fbi.api.services import today

router = APIRouter(tags=["today"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/today", response_model=Envelope[Today])
def get_today(conn: Db, _: App) -> Envelope[Today]:
    """HOY: the matches around today (live, to come and the last 48 hours' results) of the followed competitions, each with
    the likely result PrediGol forecast - labelled when uncalibrated - and what the match is about; the suggested leagues;
    and the day's picks state: published, still being read («reviewing», no hour promised) or none, with the furthest stage
    the day's selections reached and its commonest reason."""
    return today.today(conn)
