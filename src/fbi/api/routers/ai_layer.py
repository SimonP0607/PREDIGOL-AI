"""The AI decision layer over HTTP. Reading only, except the owner's queued "run now".

* ``GET /matches/{fixture_id}/analysis`` (product) - the match's PrediGol analysis, at most three cards,
  computed once by the worker and read by every user (200 readers are not 200 model calls). ``preview=shadow``
  shows the evaluation cards, SUPER_ADMIN only.
* ``/admin/ai/...`` (Admin Console) - overview, reviews with their full audit trail, packets, evidence,
  costs and the simulation, the AI's shadow report, its memory, and run requests.

No route here calls a language model and none can change a pick, a rule or a model.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.ai_layer import (
    AiOverview,
    EvidenceRow,
    MatchAnalysis,
    MemoryEvent,
    PacketView,
    ReviewDetail,
    ReviewRow,
    RunIn,
    RunQueued,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.errors import ApiError
from fbi.api.security import Admin, App
from fbi.api.services import ai_layer
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["predigol analysis"])
admin_router = APIRouter(tags=["admin: ai decision layer"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Engine = Literal["combined", "rules", "llm"]
DecisionQ = Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]
EvidenceStatus = Literal["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"]
MemoryKind = Literal["match_result", "pick_result", "context_error", "news_signal", "injury_signal", "market_signal",
                     "model_failure", "model_success", "league_pattern", "team_pattern", "player_pattern",
                     "review_quality"]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: every card, the evaluation ones included. Never a user's view.")]


def _evaluation(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the evaluation view is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/analysis", response_model=Envelope[MatchAnalysis | None])
def get_match_analysis(conn: Db, principal: App, fixture_id: FixtureId,
                       preview: Preview = None) -> Envelope[MatchAnalysis | None]:
    """ANÁLISIS PREDIGOL: up to three cards (market, selection, price, best bookmaker, model and market
    probabilities, fair and minimum odds, edge, the review's verdict, confidence, main reason and risks). Without
    an observed price the card says so and never calls it value."""
    return ai_layer.match_analysis(conn, fixture_id, evaluation=_evaluation(preview, principal))


@admin_router.get("/ai/overview", response_model=Envelope[AiOverview])
def get_overview(conn: Db) -> Envelope[AiOverview]:
    """Mode (off/shadow/enforce), configured tiers (never a key), budget and its state, whether enforcement is
    on (it needs the owner's switch AND a passed shadow gate), the last cycles and today's counts."""
    return ai_layer.overview(conn)


@admin_router.get("/ai/reviews", response_model=Envelope[list[ReviewRow]])
def get_reviews(conn: Db, day: Annotated[date | None, Query()] = None, engine: Engine = "combined",
                decision: DecisionQ | None = None, fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[list[ReviewRow]]:
    return ai_layer.reviews(conn, day=day, engine=engine, decision=decision, fixture_id=fixture_id, limit=limit)


@admin_router.get("/ai/reviews/{review_id}", response_model=Envelope[ReviewDetail])
def get_review(conn: Db, review_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[ReviewDetail]:
    """The whole audit trail: the structured output, every claim with its type and references, the evidence and
    its sources, the packet it read (hash and content), the engines combined, and each call's tokens and cost."""
    return ai_layer.review_detail(conn, review_id)


@admin_router.get("/ai/packets/{fixture_id}", response_model=Envelope[PacketView | None])
def get_packet(conn: Db, fixture_id: FixtureId) -> Envelope[PacketView | None]:
    """The newest AI_MATCH_PACKET of a fixture (immutable, hashed, every item with its source) and its history."""
    return ai_layer.packet(conn, fixture_id)


@admin_router.get("/ai/evidence", response_model=Envelope[list[EvidenceRow]])
def get_evidence(conn: Db, fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                 status: EvidenceStatus | None = None,
                 limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[list[EvidenceRow]]:
    """News, injuries, line-ups: CONFIRMED / PROBABLE / RUMOR / CONTRADICTORY / OUTDATED, with the source, its
    tier, the dates and every status change."""
    return ai_layer.evidence(conn, fixture_id=fixture_id, status=status, limit=limit)


@admin_router.get("/ai/costs", response_model=Envelope[dict[str, Any]])
def get_costs(conn: Db) -> Envelope[dict[str, Any]]:
    """Measured spend (today, 7 and 30 days, the month; by purpose and model; per match, review and approved
    analysis), the budget, and the simulation of each provider profile on the platform's own volumes."""
    return ai_layer.cost_summary(conn)


@admin_router.get("/ai/shadow", response_model=Envelope[list[dict[str, Any]]])
def get_shadow(conn: Db) -> Envelope[list[dict[str, Any]]]:
    """Model alone vs model + AI vs the market, per engine, and the gate that decides whether the AI may ever
    filter what users see."""
    return ai_layer.shadow_reports(conn)


@admin_router.get("/ai/memory", response_model=Envelope[list[MemoryEvent]])
def get_memory(conn: Db, kind: MemoryKind | None = None,
               limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[list[MemoryEvent]]:
    return ai_layer.memory(conn, kind=kind, limit=limit)


@admin_router.get("/ai/run-requests", response_model=Envelope[list[dict[str, Any]]])
def get_run_requests(conn: Db) -> Envelope[list[dict[str, Any]]]:
    return ai_layer.run_requests(conn)


@admin_router.post("/ai/run-requests", response_model=Envelope[RunQueued])
def post_run_request(body: RunIn, principal: Admin) -> Envelope[RunQueued]:
    """Queue an analysis (of one fixture, or of the day) or a learning cycle; the worker runs it within two minutes
    under the same budget and caps. At most five requests wait at once."""
    return ok(ai_layer.request_run(body, user_id=principal.user_id))
