"""Match Center detail, Live board, Players and the private Admin view."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.center import (
    AdminOverview,
    CompetitionReference,
    CompetitionTable,
    LiveBoard,
    MatchCenter,
    PlayerDetail,
    PlayerSummary,
    ProviderPredictionView,
)
from fbi.api.contracts.profile import MatchMarkets, MatchProfile
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import center, profile

router = APIRouter(tags=["match center, live, players"])
admin_router = APIRouter(tags=["admin: system"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/matches/{fixture_id}/center", response_model=Envelope[MatchCenter | None])
def get_match_center(conn: Db, fixture_id: Annotated[int, Path(ge=1)]) -> Envelope[MatchCenter | None]:
    """Statistics, events, line-ups, player ratings, absences, table, form, head-to-head and in-play data."""
    return center.match_center(conn, fixture_id)


@router.get("/matches/{fixture_id}/profile", response_model=Envelope[MatchProfile | None])
def get_match_profile(conn: Db, fixture_id: Annotated[int, Path(ge=1)]) -> Envelope[MatchProfile | None]:
    """The two teams before the match: results, goals, xG, shots, corners, cards and penalties over their newest
    finished matches, in every competition and in this one - each figure with how many matches carry its data."""
    return profile.match_profile(conn, fixture_id)


@router.get("/matches/{fixture_id}/markets", response_model=Envelope[MatchMarkets | None])
def get_match_markets(conn: Db, fixture_id: Annotated[int, Path(ge=1)]) -> Envelope[MatchMarkets | None]:
    """Every price captured for the match: the captures (the numbers the Cronología shows) and each pre-match
    selection with every bookmaker's newest and first price, whether or not it passed a pick rule."""
    return profile.match_markets(conn, fixture_id)


@router.get("/live", response_model=Envelope[LiveBoard])
def get_live(conn: Db) -> Envelope[LiveBoard]:
    """Every tracked match in play: state, key events, statistics and the main in-play prices."""
    return center.live_board(conn)


@router.get("/players", response_model=Envelope[list[PlayerSummary]])
def get_players(
    conn: Db,
    q: Annotated[str | None, Query(max_length=60)] = None,
    team_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[PlayerSummary]]:
    """Search by name, list a team's players, or (no filter) the most productive of the last 30 days."""
    return center.players(conn, q=q, team_id=team_id, limit=limit, offset=offset)


@router.get("/players/{player_id}", response_model=Envelope[PlayerDetail | None])
def get_player(conn: Db, player_id: Annotated[int, Path(ge=1)]) -> Envelope[PlayerDetail | None]:
    return center.player(conn, player_id)


@admin_router.get("/system", response_model=Envelope[AdminOverview])
def get_admin_overview(conn: Db) -> Envelope[AdminOverview]:
    """Private operations view: worker, quota, migration, captures, errors, quality, backups, versions."""
    return center.admin_overview(conn)


@router.get("/competitions/{competition_id}/standings", response_model=Envelope[CompetitionTable | None])
def get_competition_standings(
    conn: Db,
    competition_id: Annotated[int, Path(ge=1)],
    season: Annotated[int | None, Query(ge=1900, le=2100)] = None,
) -> Envelope[CompetitionTable | None]:
    """The latest stored league table: the newest season that has one, or the season asked for."""
    return center.competition_table(conn, competition_id, season=season)


@router.get("/competitions/{competition_id}/reference", response_model=Envelope[CompetitionReference | None])
def get_competition_reference(
    conn: Db,
    competition_id: Annotated[int, Path(ge=1)],
    season: Annotated[int | None, Query(ge=1900, le=2100)] = None,
) -> Envelope[CompetitionReference | None]:
    """The provider's top scorers, assists and cards, and the round calendar, with the payload each comes from."""
    return center.competition_reference(conn, competition_id, season=season)


@admin_router.get("/matches/{fixture_id}/provider-prediction", response_model=Envelope[ProviderPredictionView | None])
def get_provider_prediction(conn: Db, fixture_id: Annotated[int, Path(ge=1)]) -> Envelope[ProviderPredictionView | None]:
    """The provider's own forecast of a match (auxiliary, labelled): every version kept. Admin only - it is
    not PrediGol's model and never feeds a pick."""
    return center.provider_prediction(conn, fixture_id)
