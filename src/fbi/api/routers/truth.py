"""Admin: data truth - the audit against the provider, freshness, the league tables, the model gate."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.truth import (
    DataRepair,
    FreshnessReport,
    GateReport,
    OddsCoverageReport,
    StandingsAuditRow,
    TruthFinding,
    TruthRun,
    TruthSummary,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.services import truth

router = APIRouter(tags=["admin: data truth"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/truth/runs", response_model=Envelope[list[TruthRun]])
def get_truth_runs(conn: Db, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> Envelope[list[TruthRun]]:
    return truth.runs(conn, limit=limit)


@router.get("/truth/latest", response_model=Envelope[TruthSummary | None])
def get_truth_latest(conn: Db) -> Envelope[TruthSummary | None]:
    """The newest completed (or partial) audit: matrix, freshness at the time, gate, datasets."""
    return truth.summary(conn, None)


@router.get("/truth/runs/{run_id}", response_model=Envelope[TruthSummary | None])
def get_truth_run(conn: Db, run_id: Annotated[int, Path(ge=1)]) -> Envelope[TruthSummary | None]:
    return truth.summary(conn, run_id)


@router.get("/truth/runs/{run_id}/findings", response_model=Envelope[list[TruthFinding]])
def get_truth_findings(
    conn: Db,
    run_id: Annotated[int, Path(ge=1)],
    dataset: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z_]+$")] = None,
    severity: Literal["critical", "high", "medium", "low", "info"] | None = None,
    kind: Literal["mismatch", "missing_in_db", "missing_in_api", "not_stored", "stale", "provider_lag",
                  "inconsistent"] | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[TruthFinding]]:
    return truth.findings(conn, run_id, dataset=dataset, severity=severity, kind=kind, limit=limit, offset=offset)


@router.get("/data/freshness", response_model=Envelope[FreshnessReport])
def get_freshness(conn: Db) -> Envelope[FreshnessReport]:
    """Every dataset against its service level, measured now (kept for two minutes)."""
    return truth.freshness(conn)


@router.get("/data/gate", response_model=Envelope[GateReport])
def get_gate(conn: Db, horizon_hours: Annotated[int, Query(ge=1, le=168)] = 72) -> Envelope[GateReport]:
    """MODEL_DATA_GATE: which upcoming fixtures each model has the data to price."""
    return truth.gate(conn, horizon_hours=horizon_hours)


@router.get("/data/standings", response_model=Envelope[list[StandingsAuditRow]])
def get_standings_audit(conn: Db) -> Envelope[list[StandingsAuditRow]]:
    """Every current league table: when it was read, when it changed, and whether it reflects the last match."""
    return truth.standings(conn)


@router.get("/data/repairs", response_model=Envelope[list[DataRepair]])
def get_repairs(conn: Db, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> Envelope[list[DataRepair]]:
    """Every correction applied to stored data outside normal ingestion."""
    return truth.repairs(conn, limit=limit)


@router.get("/data/odds-coverage", response_model=Envelope[OddsCoverageReport])
def get_odds_coverage(conn: Db, days: Annotated[int, Query(ge=1, le=30)] = 14) -> Envelope[OddsCoverageReport]:
    """BOOKMAKER_COVERAGE_REPORT: who prices which competition, market and country, what our capture
    missed and why, the Colombian operators, and every price source evaluated."""
    return truth.odds_coverage(conn, days=days)
