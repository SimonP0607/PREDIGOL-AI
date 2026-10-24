"""The evolution loop (Admin Console): results become memory and proposals; the owner decides."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.ai_layer import EvolutionDashboard
from fbi.api.contracts.evolution import (
    CodePromotions,
    DecisionIn,
    EvolutionOverview,
    HypothesisIn,
    PromoteIn,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.security import Admin
from fbi.api.services import ai_layer, evolution

router = APIRouter(tags=["evolution loop"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/evolution", response_model=Envelope[EvolutionOverview])
def get_evolution(conn: Db) -> Envelope[EvolutionOverview]:
    return evolution.overview(conn)


@router.get("/evolution/code-promotions", response_model=Envelope[CodePromotions])
def get_code_promotions(conn: Db, days: Annotated[int, Query(ge=1, le=365)] = 30) -> Envelope[CodePromotions]:
    """The model code against its promotions (plan F12): which fingerprints of the model packages forecast in production in the last ``days``
    days, the decision on record that covers each, and ``traced / counted``. Reading only; kept five minutes."""
    return evolution.code_promotions(conn, days=days)


@router.post("/evolution/hypotheses", response_model=Envelope[dict[str, int]])
def propose(body: HypothesisIn, principal: Admin) -> Envelope[dict[str, int]]:
    """The owner's own proposal: PROPOSED until decided, like any other."""
    return ok({"id": evolution.propose(body)})


@router.get("/evolution/dashboard", response_model=Envelope[EvolutionDashboard])
def get_dashboard(conn: Db, day: Annotated[date | None, Query()] = None) -> Envelope[EvolutionDashboard]:
    """The day in the decision center: what was analysed (matches, news, injuries, line-ups, market moves), the
    reviews and their decisions, the findings, the errors detected after the results, the AI's shadow verdict and
    what it cost."""
    return ai_layer.dashboard(conn, day=day)


@router.post("/evolution/hypotheses/{hypothesis_id}/decision", response_model=Envelope[dict[str, str]])
def decide(hypothesis_id: Annotated[int, Path(ge=1, le=2**62)], body: DecisionIn,
           principal: Admin) -> Envelope[dict[str, str]]:
    """RECHAZAR, INVESTIGAR or APROBAR EXPERIMENTO (queued in research). Changes no rule, model or pick."""
    status = evolution.decide(hypothesis_id, decision=body.decision, user_id=principal.user_id, note=body.note)
    return ok({"status": status})


@router.post("/evolution/hypotheses/{hypothesis_id}/promote", response_model=Envelope[dict[str, str]])
def promote(hypothesis_id: Annotated[int, Path(ge=1, le=2**62)], body: PromoteIn,
            principal: Admin) -> Envelope[dict[str, str]]:
    """The owner's explicit promotion of a DONE experiment whose gate passed (409 otherwise). Never automatic."""
    return ok({"status": evolution.promote(hypothesis_id, user_id=principal.user_id, note=body.note)})
