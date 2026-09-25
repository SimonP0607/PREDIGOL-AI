from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.audit import MatchAudit
from fbi.api.contracts.catalog import CompetitionDetail, CompetitionSummary, TeamDetail, TeamSummary
from fbi.api.contracts.matches import MatchDetail, MatchSummary
from fbi.api.contracts.rankings import Rankings
from fbi.api.contracts.search import SearchHit
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.repositories.fixtures import FixtureFilter
from fbi.api.services import audit, catalog, matches
from fbi.api.services import rankings as rankings_service
from fbi.api.services import search as search_service

router = APIRouter(tags=["football"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Id = Annotated[int, Path(ge=1, le=2**62)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
StatusFilter = Literal["scheduled", "live", "finished", "cancelled", "postponed"]


@router.get("/matches", response_model=Envelope[list[MatchSummary]])
def get_matches(
    conn: Db,
    date_from: date | None = None,
    date_to: date | None = None,
    status: StatusFilter | None = None,
    competition_id: Annotated[int | None, Query(ge=1)] = None,
    team_id: Annotated[int | None, Query(ge=1)] = None,
    order: Literal["asc", "desc"] = "desc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> Envelope[list[MatchSummary]]:
    flt = FixtureFilter(date_from=date_from, date_to=date_to, status=status,
                        competition_id=competition_id, team_id=team_id)
    return matches.list_matches(conn, flt, limit=limit, offset=offset, order=order)


@router.get("/matches/{fixture_id}", response_model=Envelope[MatchDetail])
def get_match(conn: Db, fixture_id: Id) -> Envelope[MatchDetail]:
    return matches.match_detail(conn, fixture_id)


@router.get("/matches/{fixture_id}/audit", response_model=Envelope[MatchAudit])
def get_match_audit(conn: Db, fixture_id: Id) -> Envelope[MatchAudit]:
    """The chain behind every number shown for a fixture, provider to settlement."""
    return audit.match_audit(conn, fixture_id)


@router.get("/competitions", response_model=Envelope[list[CompetitionSummary]])
def get_competitions(
    conn: Db,
    tracked: bool | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Envelope[list[CompetitionSummary]]:
    return catalog.list_competitions(conn, tracked=tracked, q=q, limit=limit, offset=offset)


@router.get("/competitions/{competition_id}", response_model=Envelope[CompetitionDetail])
def get_competition(conn: Db, competition_id: Id) -> Envelope[CompetitionDetail]:
    return catalog.competition_detail(conn, competition_id)


@router.get("/teams", response_model=Envelope[list[TeamSummary]])
def get_teams(
    conn: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
    competition_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Envelope[list[TeamSummary]]:
    return catalog.list_teams(conn, q=q, competition_id=competition_id, limit=limit, offset=offset)


@router.get("/teams/{team_id}", response_model=Envelope[TeamDetail])
def get_team(conn: Db, team_id: Id) -> Envelope[TeamDetail]:
    return catalog.team_detail(conn, team_id)


@router.get("/search", response_model=Envelope[list[SearchHit]])
def get_search(
    conn: Db,
    q: Annotated[str, Query(min_length=2, max_length=60)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> Envelope[list[SearchHit]]:
    return search_service.search(conn, q, limit)


@router.get("/rankings", response_model=Envelope[Rankings | None])
def get_rankings(
    conn: Db,
    competition_id: Annotated[int | None, Query(ge=1, description="Teams whose LAST rated match was here.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Envelope[Rankings | None]:
    """Current Elo per team from the stored rating history."""
    return rankings_service.rankings(conn, competition_id=competition_id, limit=limit)
