"""A match's statistics by half (plan PM, PM-10-03). Read only; 404 while ``FBI_MATCH_HALVES`` is off (the default)."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.period_stats import MatchPeriodStats
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import period_stats as svc

router = APIRouter(tags=["period stats"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Id = Annotated[int, Path(ge=1, le=2**62)]


@router.get("/matches/{fixture_id}/period-stats", response_model=Envelope[MatchPeriodStats])
def get_match_period_stats(conn: Db, fixture_id: Id) -> Envelope[MatchPeriodStats]:
    """The match, the first half and the second half of the statistics the competition has built; a figure the provider did not send
    is null. 404 while ``FBI_MATCH_HALVES`` is off."""
    return svc.match(conn, fixture_id)
