"""The AI analyst's tools: the product API's own answers, each with where it came from.

An LLM never reads the database. It calls these tools, which call the same
read-only services the web app uses, and every result carries a provenance
block: the endpoint it is equivalent to, when it was generated, how fresh
the underlying data is, and the lineage the service reported (payload
hashes, model versions, backtest sessions). A figure in an answer that
cannot be found in a tool result is flagged as unverified, not trusted.

The tools work with no LLM configured - the web app exposes them as a
console - so the analyst's inputs can be checked by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from fbi.api.repositories import Conn
from fbi.api.repositories.fixtures import FixtureFilter
from fbi.api.services import analytics, matches, odds, ops
from fbi.api.services import search as search_service
from fbi.core.clock import now

ToolFn = Callable[[Conn, dict[str, Any]], BaseModel]


class ToolError(ValueError):
    """Bad arguments, or a thing that does not exist. Shown to the model as a tool error."""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    endpoint: str
    fn: ToolFn

    def spec(self) -> dict[str, Any]:
        """The tool definition as an LLM tool-use API expects it."""
        return {"name": self.name, "description": self.description, "input_schema": self.parameters}


def _int(args: dict[str, Any], key: str, *, required: bool = True) -> int | None:
    v = args.get(key)
    if v is None:
        if required:
            raise ToolError(f"'{key}' is required")
        return None
    try:
        i = int(v)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"'{key}' must be an integer") from exc
    if not 1 <= i <= 2**62:
        raise ToolError(f"'{key}' out of range")
    return i


def _date(args: dict[str, Any], key: str) -> date | None:
    v = args.get(key)
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError as exc:
        raise ToolError(f"'{key}' must be YYYY-MM-DD") from exc


def _fixture(args: dict[str, Any]) -> int:
    fid = _int(args, "fixture_id")
    assert fid is not None
    return fid


def _search(conn: Conn, args: dict[str, Any]) -> BaseModel:
    q = str(args.get("query", "")).strip()
    if not 2 <= len(q) <= 60:
        raise ToolError("'query' must be 2 to 60 characters")
    return search_service.search(conn, q, limit=10)


def _matches(conn: Conn, args: dict[str, Any]) -> BaseModel:
    flt = FixtureFilter(date_from=_date(args, "date_from"), date_to=_date(args, "date_to"),
                        competition_id=_int(args, "competition_id", required=False),
                        team_id=_int(args, "team_id", required=False))
    return matches.list_matches(conn, flt, limit=min(_int(args, "limit", required=False) or 20, 50), offset=0,
                                order="desc")


def _match(conn: Conn, args: dict[str, Any]) -> BaseModel:
    return matches.match_detail(conn, _fixture(args))


def _odds(conn: Conn, args: dict[str, Any]) -> BaseModel:
    return odds.fixture_odds(conn, _fixture(args), market_key=None)


def _predictions(conn: Conn, args: dict[str, Any]) -> BaseModel:
    env = matches.match_detail(conn, _fixture(args))
    return env.data.predictions


def _picks(conn: Conn, args: dict[str, Any]) -> BaseModel:
    return analytics.picks(conn, limit=50, offset=0)


def _performance(conn: Conn, _args: dict[str, Any]) -> BaseModel:
    return analytics.performance(conn)


def _quality(conn: Conn, _args: dict[str, Any]) -> BaseModel:
    return ops.quality(conn)


def _models(conn: Conn, _args: dict[str, Any]) -> BaseModel:
    return analytics.models(conn)


FIXTURE_ARG = {"type": "object", "properties": {"fixture_id": {"type": "integer", "description": "Our fixture id."}},
               "required": ["fixture_id"]}
NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}}

TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("search", "Find fixtures, teams or competitions by name. Use it to get ids.",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
         "/api/v1/search", _search),
    Tool("list_matches", "Fixtures filtered by date range (YYYY-MM-DD), competition id or team id, newest first.",
         {"type": "object", "properties": {"date_from": {"type": "string"}, "date_to": {"type": "string"},
                                           "competition_id": {"type": "integer"}, "team_id": {"type": "integer"},
                                           "limit": {"type": "integer"}}},
         "/api/v1/matches", _matches),
    Tool("get_match", "One fixture: teams, competition, kick-off, status, score (final and 90-minute basis), "
         "venue, lineage to the provider payload, and its capture timeline.", FIXTURE_ARG,
         "/api/v1/matches/{fixture_id}", _match),
    Tool("get_odds", "Prices for one fixture: what the platform captured (with capture time and payload), the "
         "near-close snapshot (not a closing line), the de-vigged consensus, and the historical market from the "
         "second source in its own terms.", FIXTURE_ARG, "/api/v1/odds/fixtures/{fixture_id}", _odds),
    Tool("get_model_prediction", "Model probabilities for one fixture with data cut-off, input hash and interval; "
         "each row says whether it is a backtest replay or a real-time forecast.", FIXTURE_ARG,
         "/api/v1/matches/{fixture_id} (predictions)", _predictions),
    Tool("get_pick", "Shadow picks with the whole lifecycle, the decision rule and each pick's lineage.", NO_ARGS,
         "/api/v1/picks", _picks),
    Tool("get_performance", "Settled shadow-pick performance; withheld below the minimum sample.", NO_ARGS,
         "/api/v1/performance", _performance),
    Tool("get_data_quality", "Freshness, coverage, capture state, quota and worker status, with the reason for "
         "every null.", NO_ARGS, "/api/v1/health/quality", _quality),
    Tool("get_model_evaluation", "The latest walk-forward backtest: every model against the de-vigged market on "
         "the same fixtures, with intervals and verdicts; betting results are hypothetical.", NO_ARGS,
         "/api/v1/models", _models),
)}


def run_tool(conn: Conn, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool. Returns a JSON-able dict; raises ToolError for bad input."""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}")
    try:
        result = tool.fn(conn, args)
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from exc
    payload = result.model_dump(mode="json")
    meta = payload.get("meta") if isinstance(payload, dict) else None
    endpoint = tool.endpoint.format(**{k: v for k, v in args.items() if isinstance(v, int | str)}) \
        if "{" in tool.endpoint else tool.endpoint
    return {
        "tool": name,
        "arguments": args,
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "reason": payload.get("reason") if isinstance(payload, dict) else None,
        "data": payload.get("data") if isinstance(payload, dict) and "data" in payload else payload,
        "provenance": {
            "endpoint": endpoint,
            "generated_at": (meta or {}).get("generated_at") or now().isoformat(),
            "data_as_of": (meta or {}).get("data_as_of"),
            "read_only": True,
        },
    }
