from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.analytics import ModelsOverview, PerformanceSummary, PicksOverview
from fbi.api.contracts.matches import MatchSummary
from fbi.api.contracts.odds import FixtureOdds, OddsIntelligence
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import analytics, odds

router = APIRouter(tags=["market & analytics"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/odds", response_model=Envelope[list[MatchSummary]])
def get_odds(
    conn: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[MatchSummary]]:
    """Fixtures that have at least one captured price."""
    return odds.list_fixtures_with_odds(conn, limit=limit, offset=offset)


@router.get("/odds/intelligence", response_model=Envelope[OddsIntelligence])
def get_odds_intelligence(conn: Db) -> Envelope[OddsIntelligence]:
    """Bookmaker margins and pre-closing -> closing movement from the historical source."""
    return odds.intelligence(conn)


@router.get("/odds/fixtures/{fixture_id}", response_model=Envelope[FixtureOdds])
def get_fixture_odds(
    conn: Db,
    fixture_id: Annotated[int, Path(ge=1, le=2**62)],
    market: Annotated[str | None, Query(max_length=40, pattern=r"^[A-Za-z0-9_.\-]+$")] = None,
) -> Envelope[FixtureOdds]:
    return odds.fixture_odds(conn, fixture_id, market_key=market)


@router.get("/models", response_model=Envelope[ModelsOverview])
def get_models(conn: Db) -> Envelope[ModelsOverview]:
    return analytics.models(conn)


@router.get("/picks", response_model=Envelope[PicksOverview])
def get_picks(
    conn: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[PicksOverview]:
    return analytics.picks(conn, limit=limit, offset=offset)


@router.get("/performance", response_model=Envelope[PerformanceSummary])
def get_performance(conn: Db) -> Envelope[PerformanceSummary]:
    return analytics.performance(conn)
