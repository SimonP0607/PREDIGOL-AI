"""PrediGol Intelligence over HTTP (Admin Console, SUPER_ADMIN): the day, the decisions and their full record, the match
dossier and narrative, calibration and its gates, memory, the daily learning reports, the market registry, the runs
with the leakage audit, and the costs. Reading only: nothing here can change a decision, a pick, a model or a rule."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import intelligence as svc

router = APIRouter(tags=["admin: predigol intelligence"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Day = Annotated[date | None, Query(description="A Bogotá day (default: today).")]
State = Literal["RECHAZADO", "INVESTIGACION", "CAUTELA", "APROBADO", "PICK_DEL_DIA", "CANDIDATO_PARLAY", "PICK_PREMIUM"]
Market = Literal["1X2", "OU", "BTTS", "DC", "AH"]
EntityType = Literal["team", "player", "coach", "referee", "competition", "market"]


@router.get("/intelligence/day", response_model=Envelope[dict[str, Any]])
def get_day(conn: Db, day: Day = None) -> Envelope[dict[str, Any]]:
    """EL DÍA DE PREDIGOL INTELLIGENCE: analysed, candidates by state and context, depth, cost and tokens, sources,
    the picks of the day (v6 shadow beside v5), the calibration behind them and the day's learning report."""
    return svc.day_view(conn, day=day)


@router.get("/intelligence/decisions", response_model=Envelope[dict[str, Any]])
def get_decisions(conn: Db, day: Day = None, state: State | None = None, market: Market | None = None,
                  fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                  limit: Annotated[int, Query(ge=1, le=1000)] = 300) -> Envelope[dict[str, Any]]:
    """The newest decision of every selection of the day's matches, filtered."""
    return svc.decisions(conn, day=day, state=state, market=market, fixture_id=fixture_id, limit=limit)


@router.get("/intelligence/decisions/{decision_id}", response_model=Envelope[dict[str, Any]])
def get_decision(conn: Db, decision_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[dict[str, Any]]:
    """One decision whole: the model and its version, the calibrator, the market, price and bookmaker, the ten
    filters, the score and the stake with their components, the AI's review and the evidence, the outcome, the
    post-mortem and the selection's history."""
    return svc.decision_detail(conn, decision_id)


@router.get("/intelligence/matches/{fixture_id}/dossier", response_model=Envelope[dict[str, Any]])
def get_dossier(conn: Db, fixture_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[dict[str, Any]]:
    """The match's MATCH INTELLIGENCE PACKAGE (dossier-v1), its narrative and its decisions."""
    return svc.dossier(conn, fixture_id)


@router.get("/intelligence/calibration", response_model=Envelope[dict[str, Any]])
def get_calibration(conn: Db) -> Envelope[dict[str, Any]]:
    """Champions and challengers per (market, model), the gates fixed in advance, every promotion and retirement, the
    prospective evaluations."""
    return svc.calibration(conn)


@router.get("/intelligence/memory", response_model=Envelope[dict[str, Any]])
def get_memory(conn: Db, entity_type: EntityType | None = None,
               q: Annotated[str | None, Query(max_length=80)] = None,
               limit: Annotated[int, Query(ge=1, le=500)] = 100) -> Envelope[dict[str, Any]]:
    return svc.memory(conn, entity_type=entity_type, q=q, limit=limit)


@router.get("/intelligence/memory/{entity_type}/{entity_id}", response_model=Envelope[dict[str, Any]])
def get_memory_history(conn: Db, entity_type: EntityType,
                       entity_id: Annotated[str, Path(max_length=120)]) -> Envelope[dict[str, Any]]:
    return svc.memory_history(conn, entity_type, entity_id)


@router.get("/intelligence/reports", response_model=Envelope[dict[str, Any]])
def get_reports(conn: Db, day: Day = None) -> Envelope[dict[str, Any]]:
    """The DAILY LEARNING REPORT of a day (its newest revision) and the days that have one."""
    return svc.reports(conn, day=day)


@router.get("/intelligence/markets", response_model=Envelope[dict[str, Any]])
def get_markets(conn: Db) -> Envelope[dict[str, Any]]:
    """MARKET DISCOVERY ENGINE: every pre-match market of the provider with its ten criteria and status."""
    return svc.markets(conn)


@router.get("/intelligence/runs", response_model=Envelope[dict[str, Any]])
def get_runs(conn: Db, limit: Annotated[int, Query(ge=1, le=500)] = 60) -> Envelope[dict[str, Any]]:
    """The jobs' record (duration, status, counts, errors, version) and the latest data-leakage audit."""
    return svc.runs(conn, limit=limit)


@router.get("/intelligence/costs", response_model=Envelope[dict[str, Any]])
def get_costs(conn: Db) -> Envelope[dict[str, Any]]:
    """Cost per match, candidate, pick, research and post-mortem, per day, and the month against the budget."""
    return svc.costs(conn)
