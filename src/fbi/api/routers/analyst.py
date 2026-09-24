from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from fbi.analyst.agent import SYSTEM_PROMPT, AnalystAgent, AnalystConfig
from fbi.analyst.tools import TOOLS, ToolError, run_tool
from fbi.api.contracts.analyst import AnalystReply, AnalystStatus, Citation, Question, ToolSpec
from fbi.api.deps import get_db
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable

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
    query: Annotated[str | None, Query(min_length=2, max_length=60)] = None,
    date_from: Annotated[str | None, Query(max_length=10)] = None,
    date_to: Annotated[str | None, Query(max_length=10)] = None,
    competition_id: Annotated[int | None, Query(ge=1)] = None,
    team_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> dict[str, Any]:
    """Run one analyst tool by hand: the exact input an LLM would get, with provenance."""
    args = {k: v for k, v in {"fixture_id": fixture_id, "query": query, "date_from": date_from, "date_to": date_to,
                              "competition_id": competition_id, "team_id": team_id, "limit": limit}.items()
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
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        agent.close()
    return ok(AnalystReply(
        text=answer.text, rounds=answer.rounds, stopped=answer.stopped, unverified_figures=answer.unverified_figures,
        citations=[Citation(id=c.id, tool=c.tool, arguments=c.arguments, ok=c.ok,
                            status=(c.result or {}).get("status"), provenance=(c.result or {}).get("provenance"),
                            error=c.error) for c in answer.calls]))
