from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.analytics import ModelsOverview, PerformanceSummary, PicksOverview
from fbi.api.contracts.funnel import SelectionFunnel
from fbi.api.contracts.matches import MatchSummary
from fbi.api.contracts.odds import FixtureOdds, OddsIntelligence
from fbi.api.contracts.research import ResearchOverview
from fbi.api.contracts.settlement import SettlementLatency
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import analytics, odds, research, selection, settlement

router = APIRouter(tags=["market"])
admin_router = APIRouter(tags=["admin: market & research"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/odds", response_model=Envelope[list[MatchSummary]])
def get_odds(
    conn: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[MatchSummary]]:
    """Fixtures that have at least one captured price."""
    return odds.list_fixtures_with_odds(conn, limit=limit, offset=offset)


@admin_router.get("/odds/intelligence", response_model=Envelope[OddsIntelligence])
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


@admin_router.get("/models", response_model=Envelope[ModelsOverview])
def get_models(conn: Db) -> Envelope[ModelsOverview]:
    return analytics.models(conn)


@admin_router.get("/research/v2", response_model=Envelope[ResearchOverview])
def get_research_v2(conn: Db) -> Envelope[ResearchOverview]:
    """The latest research-V2 run: every model's role against the market (CHAMPION, CHALLENGER,
    RESEARCH, REJECTED) with its evidence, the prospective evaluation by segment, the shadow-pick
    audit - and the runs kept from before the rebuild (LEGACY_RESEARCH_RUN)."""
    return research.overview(conn)


@admin_router.get("/picks", response_model=Envelope[PicksOverview])
def get_picks(
    conn: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[PicksOverview]:
    """Every pick the research pipeline made - candidates, rejections, shadow and qualified."""
    return analytics.picks(conn, limit=limit, offset=offset, public=False)


@admin_router.get("/picks/settlement", response_model=Envelope[SettlementLatency])
def get_settlement_latency(conn: Db, days: Annotated[int, Query(ge=1, le=60)] = 7) -> Envelope[SettlementLatency]:
    """How long each match's bets waited after it ended (first settlement per match), and the matches that ended
    and still have bets open - none for long, unless a human must decide (postponed, abandoned, awarded)."""
    return settlement.latency(conn, days=days)


@admin_router.get("/picks/funnel", response_model=Envelope[SelectionFunnel])
def get_selection_funnel(
    conn: Db, source: Annotated[Literal["evaluation", "qualified"], Query()] = "evaluation",
) -> Envelope[SelectionFunnel]:
    """The day's selection funnel (REVIEW B1): the next 24 hours' candidates stage by stage - data, market, model,
    calibration, value, risk, PrediGol Intelligence, selection - why the others stopped, what the next build of the
    day's set would choose and what nearly made it. ``evaluation``: with shadow picks (the owner's preview)."""
    return selection.selection_funnel(conn, source=source)


@admin_router.get("/performance", response_model=Envelope[PerformanceSummary])
def get_performance(conn: Db) -> Envelope[PerformanceSummary]:
    return analytics.performance(conn)
