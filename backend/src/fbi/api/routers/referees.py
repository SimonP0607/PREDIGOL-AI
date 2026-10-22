"""Referees as people (Admin Console, plan F3): the queue of doubts, a referee's page and the decisions of a person.

The rules (``fbi.people.referee_identity``) place every spelling the provider used; what they are not sure of waits here as a pair
of referees. Every decision is reversible and leaves an event (``core.referee_events``) with who took it and what moved."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.referees import (
    ActionResult,
    MergeIn,
    PairIn,
    PairStatus,
    RefereeDetail,
    RefereeList,
    RefereeQueue,
    RenameIn,
    SplitIn,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.security import Admin
from fbi.api.services import referees as svc
from fbi.auth.service import Principal

router = APIRouter(tags=["referees"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
RefereeId = Annotated[int, Path(ge=1, le=2**62)]
EventId = Annotated[int, Path(ge=1, le=2**62)]


def _actor(principal: Principal) -> str:
    return f"admin:{principal.email}"


@router.get("/referees", response_model=Envelope[RefereeList])
def list_referees(conn: Db, q: Annotated[str | None, Query(max_length=80)] = None,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50,
                  offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> Envelope[RefereeList]:
    """The people, the busiest first - or those whose name, under any spelling, holds the words of `q` - with the figures that
    say whether the identity is healthy."""
    return svc.referees(conn, q=q, limit=limit, offset=offset)


@router.get("/referees/queue", response_model=Envelope[RefereeQueue])
def get_queue(conn: Db, status: Annotated[PairStatus, Query()] = "open",
              reason: Annotated[str | None, Query(max_length=40)] = None,
              limit: Annotated[int, Query(ge=1, le=200)] = 50,
              offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> Envelope[RefereeQueue]:
    """The pairs the rules doubt (`open`) or a person already decided (`rejected`, `merged`), the ones that touch most matches first."""
    return svc.queue(conn, status=status, reason=reason, limit=limit, offset=offset)


@router.get("/referees/{referee_id}", response_model=Envelope[RefereeDetail])
def get_referee(conn: Db, referee_id: RefereeId) -> Envelope[RefereeDetail]:
    """One person: his spellings and the matches each is the newest word on, his newest matches, the doubts about him and what
    was changed (404 when he does not exist)."""
    return svc.referee(conn, referee_id)


@router.post("/referees/{referee_id}/merge", response_model=Envelope[ActionResult])
def merge(referee_id: RefereeId, body: MergeIn, principal: Admin) -> Envelope[ActionResult]:
    """`merge_id` is the same person as the referee in the path: his spellings move to him. 409 when the two have matches at the
    same time (they are two men) unless `force`; reversible with `undo`."""
    return svc.merge(referee_id, body, actor=_actor(principal))


@router.post("/referees/events/{event_id}/undo", response_model=Envelope[ActionResult])
def undo(event_id: EventId, principal: Admin) -> Envelope[ActionResult]:
    """Take a merge back: the spellings it moved return to the referee it merged. 409 when it was undone already or the referee
    was merged again since."""
    return svc.undo(event_id, actor=_actor(principal))


@router.post("/referees/{referee_id}/split", response_model=Envelope[ActionResult])
def split(referee_id: RefereeId, body: SplitIn, principal: Admin) -> Envelope[ActionResult]:
    """Two men were taken for one: the listed spellings go to a NEW referee and the pair is never suggested again."""
    return svc.split(referee_id, body, actor=_actor(principal))


@router.post("/referees/{referee_id}/reject", response_model=Envelope[ActionResult])
def reject(referee_id: RefereeId, body: PairIn, principal: Admin) -> Envelope[ActionResult]:
    """The two referees are different people: the pair leaves the queue and is not suggested again."""
    return svc.reject(referee_id, body, actor=_actor(principal))


@router.post("/referees/{referee_id}/reopen", response_model=Envelope[ActionResult])
def reopen(referee_id: RefereeId, body: PairIn, principal: Admin) -> Envelope[ActionResult]:
    """Take a rejection back: the pair is a question again."""
    return svc.reopen(referee_id, body, actor=_actor(principal))


@router.post("/referees/{referee_id}/rename", response_model=Envelope[ActionResult])
def rename(referee_id: RefereeId, body: RenameIn, principal: Admin) -> Envelope[ActionResult]:
    """Set the name he is shown with (the rules keep it from then on); null gives the naming back to the rules."""
    return svc.rename(referee_id, body, actor=_actor(principal))
