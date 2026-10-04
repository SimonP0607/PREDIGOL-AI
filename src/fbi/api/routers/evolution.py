"""The evolution loop (Admin Console): results become memory and proposals; the owner decides."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.evolution import DecisionIn, EvolutionOverview, HypothesisIn
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.security import Admin
from fbi.api.services import evolution

router = APIRouter(tags=["evolution loop"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/evolution", response_model=Envelope[EvolutionOverview])
def get_evolution(conn: Db) -> Envelope[EvolutionOverview]:
    return evolution.overview(conn)


@router.post("/evolution/hypotheses", response_model=Envelope[dict[str, int]])
def propose(body: HypothesisIn, principal: Admin) -> Envelope[dict[str, int]]:
    """The owner's own proposal: PROPOSED until decided, like any other."""
    return ok({"id": evolution.propose(body)})


@router.post("/evolution/hypotheses/{hypothesis_id}/decision", response_model=Envelope[dict[str, str]])
def decide(hypothesis_id: Annotated[int, Path(ge=1, le=2**62)], body: DecisionIn,
           principal: Admin) -> Envelope[dict[str, str]]:
    """Accept (queue an experiment in research) or reject. Changes no rule, model or pick."""
    status = evolution.decide(hypothesis_id, accept=body.decision == "accept", user_id=principal.user_id,
                              note=body.note)
    return ok({"status": status})
