from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.audit import MatchAudit
from fbi.api.contracts.catalog import CompetitionDetail, CompetitionSummary, TeamDetail, TeamSummary
from fbi.api.contracts.intelligence.profiles import Profile, ProfilePrivate
from fbi.api.contracts.intelligence.search import SearchV2, SearchV2Private
from fbi.api.contracts.matches import MatchDetail, MatchSummary, MatchView
from fbi.api.contracts.rankings import Rankings
from fbi.api.contracts.search import SearchHit
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.repositories.fixtures import FixtureFilter
from fbi.api.services import audit, catalog, matches, profiles, search_v2
from fbi.api.services import rankings as rankings_service
from fbi.api.services import search as search_service

router = APIRouter(tags=["football"])
admin_router = APIRouter(tags=["admin: football"])
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
    kickoff_after: Annotated[datetime | None, Query(description="Inclusive instant; with kickoff_before, a "
                                                    "day in the reader's own time zone.")] = None,
    kickoff_before: Annotated[datetime | None, Query(description="Exclusive instant.")] = None,
    status: StatusFilter | None = None,
    competition_id: Annotated[int | None, Query(ge=1)] = None,
    team_id: Annotated[int | None, Query(ge=1)] = None,
    order: Literal["asc", "desc"] = "desc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> Envelope[list[MatchSummary]]:
    flt = FixtureFilter(date_from=date_from, date_to=date_to, status=status,
                        competition_id=competition_id, team_id=team_id,
                        kickoff_after=kickoff_after, kickoff_before=kickoff_before)
    return matches.list_matches(conn, flt, limit=limit, offset=offset, order=order)


@router.get("/matches/{fixture_id}", response_model=Envelope[MatchView])
def get_match(conn: Db, fixture_id: Id) -> Envelope[MatchView]:
    """The match, its venue and its latest prices. Model output and lineage: /admin/matches/{id}."""
    return matches.match_view(conn, fixture_id)


@admin_router.get("/matches/{fixture_id}", response_model=Envelope[MatchDetail])
def get_match_detail(conn: Db, fixture_id: Id) -> Envelope[MatchDetail]:
    return matches.match_detail(conn, fixture_id)


@admin_router.get("/matches/{fixture_id}/audit", response_model=Envelope[MatchAudit])
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


@router.get("/teams/{team_id}/profile", response_model=Envelope[Profile])
def get_team_profile(conn: Db, team_id: Id) -> Envelope[Profile]:
    """C-09 (AD-H07, IA-090), public projection: the profile of a club or a national team (``kind`` says which) - header with
    crest, stadium and current coach, form, season figures each with its sample, availability (state, basis, source and date
    only), squad, campaign, computed honours and, for a national team, its latest list and leaders. Additive: /teams/{id}
    keeps its shape. 404 while ``FBI_PROFILES`` is off."""
    return profiles.public_team(conn, team_id)


@router.get("/competitions/{competition_id}/profile", response_model=Envelope[Profile])
def get_competition_profile(conn: Db, competition_id: Id) -> Envelope[Profile]:
    """C-09, public projection: a competition - its season, table, next matches, scorers and the coverage of its statistics.
    404 while ``FBI_PROFILES`` is off."""
    return profiles.public_competition(conn, competition_id)


@admin_router.get("/intelligence/teams/{team_id}/profile", response_model=Envelope[ProfilePrivate])
def get_team_profile_private(conn: Db, team_id: Id) -> Envelope[ProfilePrivate]:
    """C-09, private projection (``require_admin``): the public profile plus the section «Intelligence» - the selections in
    shadow of the team's matches with their state, and its external ids."""
    return profiles.private_team(conn, team_id)


@admin_router.get("/intelligence/competitions/{competition_id}/profile", response_model=Envelope[ProfilePrivate])
def get_competition_profile_private(conn: Db, competition_id: Id) -> Envelope[ProfilePrivate]:
    """C-09, private projection of a competition: plus its external ids."""
    return profiles.private_competition(conn, competition_id)


@router.get("/search", response_model=Envelope[list[SearchHit]])
def get_search(
    conn: Db,
    q: Annotated[str, Query(min_length=2, max_length=60)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> Envelope[list[SearchHit]]:
    return search_service.search(conn, q, limit)


SearchQuery = Annotated[str, Query(min_length=2, max_length=60)]


@router.get("/search/v2", response_model=Envelope[SearchV2])
def get_search_v2(conn: Db, q: SearchQuery) -> Envelope[SearchV2]:
    """C-10 (AD-I02): the search in groups - teams, national teams, players, competitions, coaches, referees, stadiums,
    matches and news - in three passes (prefix, words, trigrams), up to 8 per group, with the aliases in force. Additive:
    /search keeps its list."""
    return ok(search_v2.public_answer(conn, q))


@admin_router.get("/search/v2", response_model=Envelope[SearchV2Private])
def get_search_v2_private(conn: Db, q: SearchQuery) -> Envelope[SearchV2Private]:
    """C-10, private projection: each hit's score, popularity and rank, and the state of the index (for calibrating)."""
    return ok(search_v2.private_answer(conn, q))


@admin_router.get("/rankings", response_model=Envelope[Rankings | None])
def get_rankings(
    conn: Db,
    competition_id: Annotated[int | None, Query(ge=1, description="Teams whose LAST rated match was here.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    pool: Annotated[Literal["men", "women", "youth", "all"], Query(
        description="Rating pool: senior men (default), women, youth, or all of them in one list.")] = "men",
) -> Envelope[Rankings | None]:
    """Current Elo per team from the stored rating history, one rating pool at a time."""
    return rankings_service.rankings(conn, competition_id=competition_id, limit=limit, pool=pool)
