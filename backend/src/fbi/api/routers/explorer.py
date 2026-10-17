"""Analytics page: /analytics/* - competitions, teams, market, experiments, coverage, migration."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.explorer import (
    CompetitionProfile,
    CoverageCell,
    ExperimentSummary,
    MarketAnalytics,
    MigrationProgress,
    TeamAnalytics,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import explorer

router = APIRouter(prefix="/analytics", tags=["analytics"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Id = Annotated[int, Path(ge=1, le=2**62)]


@router.get("/competitions", response_model=Envelope[list[CompetitionProfile]])
def get_competition_profiles(conn: Db) -> Envelope[list[CompetitionProfile]]:
    """Per competition and season: outcome rates, goals, home edge, and how much data each fixture has."""
    return explorer.competitions(conn)


@router.get("/teams/{team_id}", response_model=Envelope[TeamAnalytics])
def get_team_analytics(conn: Db, team_id: Id) -> Envelope[TeamAnalytics]:
    """Record splits, Elo history, shot statistics and the team's side of its newest feature set."""
    return explorer.team(conn, team_id)


@router.get("/market", response_model=Envelope[MarketAnalytics])
def get_market_analytics(conn: Db) -> Envelope[MarketAnalytics]:
    """Calibration of the de-vigged Pinnacle close and closing-versus-pre-closing log loss by season."""
    return explorer.market(conn)


@router.get("/experiments", response_model=Envelope[list[ExperimentSummary]])
def get_experiments(conn: Db) -> Envelope[list[ExperimentSummary]]:
    """The research registry with each experiment's model gate."""
    return explorer.experiments(conn)


@router.get("/coverage", response_model=Envelope[list[CoverageCell]])
def get_data_coverage(conn: Db) -> Envelope[list[CoverageCell]]:
    """Per competition and season, how many fixtures have each kind of data."""
    return explorer.coverage(conn)


@router.get("/migration", response_model=Envelope[MigrationProgress])
def get_migration(conn: Db) -> Envelope[MigrationProgress]:
    """The historical migration: the newest plan and its units by kind, status and tier."""
    return explorer.migration(conn)
