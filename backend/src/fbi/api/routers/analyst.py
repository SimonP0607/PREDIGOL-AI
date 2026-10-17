"""The AI layer, Admin Console only (mounted under /api/v1/admin with the admin permission).

* ``/analyst`` and ``/analyst/tools/{name}`` - the whitelisted tools, runnable by hand;
* ``/analyst/ask`` - a question to the model, priced, capped and recorded;
* ``/ai/*`` - status and budget, runs, the daily research report with its claims, and the pick
  reviewer's flags; ``POST /ai/report/run`` and ``/ai/review/run`` run them now.

Nothing here can change a pick: the reviewer writes flags, the report writes text and claims.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from fbi.analyst import budget
from fbi.analyst.agent import (
    SYSTEM_PROMPT,
    AnalystAgent,
    AnalystConfig,
    NotConfiguredError,
    QuestionLimitError,
)
from fbi.analyst.research import run_daily_report
from fbi.analyst.reviewer import run_pick_review
from fbi.analyst.tools import TOOLS, ToolError, run_tool
from fbi.api.contracts.analyst import (
    AiFlags,
    AiReport,
    AiRunRow,
    AiStatus,
    AnalystReply,
    AnalystStatus,
    Citation,
    Question,
    RunReportIn,
    ToolSpec,
)
from fbi.api.deps import get_db
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.services import ai as ai_service

router = APIRouter(tags=["ai analyst"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]

RULES = [line.removeprefix("- ").strip() for line in SYSTEM_PROMPT.splitlines() if line.startswith("- ")]


def _status() -> AnalystStatus:
    cfg = AnalystConfig.from_env()
    return AnalystStatus(
        configured=cfg.configured, missing=cfg.missing, rules=RULES,
        tools=[ToolSpec(name=t.name, description=t.description, parameters=t.parameters, endpoint=t.endpoint)
               for t in TOOLS.values()])


@router.get("/analyst", response_model=Envelope[AnalystStatus])
def get_analyst() -> Envelope[AnalystStatus]:
    s = _status()
    if not s.configured:
        return unavailable(s, "No LLM is configured on the API host ("
                           + ", ".join(s.missing) + " unset). The tools below work without one.")
    return ok(s)


@router.get("/analyst/tools/{name}")
def get_tool(
    conn: Db,
    name: Annotated[str, Path(max_length=40, pattern=r"^[a-z_]+$")],
    fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
    team_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
    player_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
    competition_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
    season: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    market_key: Annotated[str | None, Query(pattern=r"^(1X2|OU|BTTS|AH|DC)$")] = None,
    query: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    date_from: Annotated[str | None, Query(max_length=10)] = None,
    date_to: Annotated[str | None, Query(max_length=10)] = None,
    days: Annotated[int | None, Query(ge=1, le=60)] = None,
    source: Annotated[Literal["qualified", "evaluation"] | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> dict[str, Any]:
    """Run one tool by hand: the exact input an LLM would get, with provenance."""
    args = {k: v for k, v in {"fixture_id": fixture_id, "team_id": team_id, "player_id": player_id,
                              "competition_id": competition_id, "season": season, "market_key": market_key,
                              "query": query, "date_from": date_from, "date_to": date_to, "days": days,
                              "source": source, "limit": limit}.items()
            if v is not None}
    try:
        return run_tool(conn, name, args)
    except ToolError as exc:
        raise HTTPException(status_code=404 if "unknown tool" in str(exc) else 422, detail=str(exc)) from exc


@router.post("/analyst/ask", response_model=Envelope[AnalystReply | None])
def ask(conn: Db, body: Question) -> Envelope[AnalystReply | None]:
    cfg = AnalystConfig.from_env()
    if not cfg.configured:
        return Envelope[AnalystReply | None](
            status=DataStatus.NOT_AVAILABLE, data=None,
            reason="No LLM is configured on the API host (" + ", ".join(cfg.missing) + " unset). "
                   "Nothing was sent anywhere.")
    agent = AnalystAgent(conn, cfg)
    try:
        answer = agent.ask(body.question)
    except NotConfiguredError as exc:
        return Envelope[AnalystReply | None](status=DataStatus.NOT_AVAILABLE, data=None, reason=str(exc))
    except budget.OverBudgetError as exc:
        return Envelope[AnalystReply | None](status=DataStatus.NOT_AVAILABLE, data=None,
                                             reason=f"{exc}. Nothing was sent.")
    except QuestionLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        agent.close()
    return ok(AnalystReply(
        text=answer.text, rounds=answer.rounds, stopped=answer.stopped, unverified_figures=answer.unverified_figures,
        citations=[Citation(id=c.id, tool=c.tool, arguments=c.arguments, ok=c.ok,
                            status=(c.result or {}).get("status"), provenance=(c.result or {}).get("provenance"),
                            error=c.error) for c in answer.calls]))


@router.get("/ai/status", response_model=Envelope[AiStatus])
def ai_status(conn: Db) -> Envelope[AiStatus]:
    return ai_service.status(conn)


@router.get("/ai/runs", response_model=Envelope[list[AiRunRow]])
def ai_runs(conn: Db, kind: Annotated[Literal["ask", "daily_report", "pick_review"] | None, Query()] = None,
            limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[AiRunRow]]:
    return ai_service.runs(conn, kind=kind, limit=limit)


@router.get("/ai/report", response_model=Envelope[AiReport | None])
def ai_report(conn: Db, day: Annotated[date | None, Query()] = None,
              source: Annotated[Literal["qualified", "evaluation"] | None, Query()] = None
              ) -> Envelope[AiReport | None]:
    return ai_service.report(conn, day=day, source=source)


@router.get("/ai/flags", response_model=Envelope[AiFlags])
def ai_flags(conn: Db, day: Annotated[date | None, Query()] = None,
             source: Annotated[Literal["qualified", "evaluation"], Query()] = "evaluation") -> Envelope[AiFlags]:
    return ai_service.flags(conn, day=day, source=source)


@router.post("/ai/report/run", response_model=Envelope[AiReport | None])
def ai_report_run(conn: Db, body: RunReportIn) -> Envelope[AiReport | None]:
    """Write the day's report now (the data part always; research only with a configured LLM,
    inside the monthly budget)."""
    result = run_daily_report(conn, day=body.day, source=body.source)
    return ai_service.report(conn, day=result.day, source=result.source)


@router.post("/ai/review/run", response_model=Envelope[AiFlags])
def ai_review_run(conn: Db, body: RunReportIn) -> Envelope[AiFlags]:
    source = body.source or "evaluation"
    run_pick_review(conn, day=body.day, source=source)
    return ai_service.flags(conn, day=body.day, source=source)
