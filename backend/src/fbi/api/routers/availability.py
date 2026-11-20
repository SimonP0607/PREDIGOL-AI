"""C-16, availability (plan PM, PM-02-05): the matrix of what PrediGol has per competition, season, datum and market, and the seven
states of a match. Read only. Every route answers 404 while ``FBI_AVAILABILITY`` is off (the default)."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.intelligence.availability import Availability, AvailabilityPrivate
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import availability as svc

router = APIRouter(tags=["availability"])
admin_router = APIRouter(tags=["admin: availability"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Id = Annotated[int, Path(ge=1, le=2**62)]


@router.get("/availability/competitions", response_model=Envelope[Availability])
def get_directory(conn: Db) -> Envelope[Availability]:
    """C-16: every tracked competition with its summary and its seven families (the directory; no page decides with it)."""
    return svc.directory(conn)


@router.get("/availability/competitions/{competition_id}", response_model=Envelope[Availability])
def get_competition(conn: Db, competition_id: Id) -> Envelope[Availability]:
    """C-16: one competition, its seasons and every cell - level, sample, share, provisional, why and when."""
    return svc.competition(conn, competition_id)


@router.get("/matches/{fixture_id}/availability", response_model=Envelope[Availability])
def get_match(conn: Db, fixture_id: Id) -> Envelope[Availability]:
    """C-16: the blocks and markets of a match with their seven states and the reason."""
    return svc.match(conn, fixture_id)


@admin_router.get("/availability/matrix", response_model=Envelope[AvailabilityPrivate])
def get_matrix(conn: Db) -> Envelope[AvailabilityPrivate]:
    """C-16, private projection: the whole matrix with what each recalculation measured, and the week's changes and discrepancies."""
    return svc.matrix(conn)


@admin_router.get("/availability/changes", response_model=Envelope[AvailabilityPrivate])
def get_changes(conn: Db) -> Envelope[AvailabilityPrivate]:
    """C-16, private projection: the changes of level and the shadow comparison's discrepancies of the last seven days."""
    return svc.changes(conn)
