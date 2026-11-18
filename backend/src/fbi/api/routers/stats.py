"""C-13, the statistical profiles (plan EA, EA-007). Read only; 404 while ``FBI_STATS_V2`` is off (the private routes serve the owner
either way)."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.intelligence.market_probs import MarketProbs, MarketProbsPrivate
from fbi.api.contracts.intelligence.stats_profile import (
    StatsContext,
    StatsProfile,
    StatsProfilePrivate,
    StatsScope,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import market_probs
from fbi.api.services import stats_profile as svc

router = APIRouter(tags=["stats"])
admin_router = APIRouter(tags=["admin: stats"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Id = Annotated[int, Path(ge=1, le=2**62)]
Season = Annotated[int | None, Query(ge=1, le=2**62, description="A competition season; by default the main one.")]
Scope = Annotated[StatsScope, Query(description="The last 5, 10 or 20 matches, or the whole season.")]
Context = Annotated[StatsContext, Query(description="Every match, only at home or only away.")]
Other = Annotated[int, Query(ge=1, le=2**62)]


@router.get("/teams/{team_id}/stats", response_model=Envelope[StatsProfile])
def get_team_stats(conn: Db, team_id: Id, season: Season = None, scope: Scope = "season",
                   context: Context = "all") -> Envelope[StatsProfile]:
    """C-13: a team's figures with percentiles, radar, xG series, halves, game states, pulse, goals by interval, survival of 0-0
    and trends, in one competition season, scope and context."""
    return svc.public_team(conn, team_id, season=season, scope=scope, context=context)


@router.get("/players/{player_id}/stats", response_model=Envelope[StatsProfile])
def get_player_stats(conn: Db, player_id: Id, season: Season = None) -> Envelope[StatsProfile]:
    """C-13: a player's template of his position - rates per 90 with percentile and the position's distribution - and his last
    five appearances."""
    return svc.public_player(conn, player_id, season=season)


@router.get("/stats/compare/teams", response_model=Envelope[StatsProfile])
def compare_teams(conn: Db, a: Other, b: Other, scope: Scope = "season", context: Context = "all") -> Envelope[StatsProfile]:
    """C-13: two teams, each against its own league."""
    return svc.public_compare(conn, "equipo", a, b, scope=scope, context=context)


@router.get("/stats/compare/players", response_model=Envelope[StatsProfile])
def compare_players(conn: Db, a: Other, b: Other) -> Envelope[StatsProfile]:
    """C-13: two players, each against his own position."""
    return svc.public_compare(conn, "jugador", a, b)


@router.get("/matches/{fixture_id}/stats-preview", response_model=Envelope[StatsProfile])
def match_stats_preview(conn: Db, fixture_id: Id, scope: Scope = "season") -> Envelope[StatsProfile]:
    """C-13: the two sides of a match, the home side at home and the away side away."""
    return svc.public_preview(conn, fixture_id, scope=scope)


@admin_router.get("/intelligence/teams/{team_id}/stats", response_model=Envelope[StatsProfilePrivate])
def get_team_stats_private(conn: Db, team_id: Id, season: Season = None, scope: Scope = "season",
                           context: Context = "all") -> Envelope[StatsProfilePrivate]:
    """C-13, private projection: the public answer plus the audit of the calculation (run, version, coverage of every metric)."""
    return svc.private_team(conn, team_id, season=season, scope=scope, context=context)


@admin_router.get("/intelligence/players/{player_id}/stats", response_model=Envelope[StatsProfilePrivate])
def get_player_stats_private(conn: Db, player_id: Id, season: Season = None) -> Envelope[StatsProfilePrivate]:
    return svc.private_player(conn, player_id, season=season)


@router.get("/matches/{fixture_id}/market-probs", response_model=Envelope[MarketProbs])
def match_market_probs(conn: Db, fixture_id: Id) -> Envelope[MarketProbs]:
    """C-14: every price in force of the match with its three marks - the model's figure (only on an evaluable market), the implied
    probability without margin and the history with its Wilson interval - and whether Mi parlay takes it. 404 while
    ``FBI_MARKET_PROBS`` is off."""
    return market_probs.public(conn, fixture_id)


@admin_router.get("/intelligence/matches/{fixture_id}/market-probs", response_model=Envelope[MarketProbsPrivate])
def match_market_probs_private(conn: Db, fixture_id: Id) -> Envelope[MarketProbsPrivate]:
    """C-14, private projection: adds the figure of every model still in calibration (owner's evaluation, D-EA-2)."""
    return market_probs.private(conn, fixture_id)
