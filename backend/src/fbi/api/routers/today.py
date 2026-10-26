"""Today, for Home, over HTTP (plan UX, A9). Reading only.

* ``GET /today`` (product) - the matches from 48 hours ago to 36 hours ahead with PrediGol's result forecast labelled and one line
  of the reading, the leagues suggested until the reader picks theirs, and whether the day has published picks - or why not,
  from the published set's own funnel. The same board for every reader (kept a minute; the reason, five).
* ``GET /today/no-pick`` (product) - only the day's picks state and its reason, for the Picks page: the same answer as
  ``/today``'s ``no_pick``, without the list of matches.

No route here computes a probability, prices a selection or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from fbi.api.contracts.today import NoPick, Today
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
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


@router.get("/today/no-pick", response_model=Envelope[NoPick])
def get_no_pick(conn: Db, _: App) -> Envelope[NoPick]:
    """The day's picks state - published, still being read or none with its furthest stage and commonest reason - as
    ``/today`` says it, for a page that does not need the matches (Picks)."""
    reason = today.no_pick(conn)
    return ok(reason.data)
