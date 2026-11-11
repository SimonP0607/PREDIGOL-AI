"""What the report of the cost by path of decision reads (IA-034; the report itself is ``fbi.ai.cost_paths``). Reads only: the caller opens the
connection read-only and in ONE snapshot (``REPEATABLE READ``), so that the rows and the ledger's own sum are the same rows.

Seven statements:

* ``CALLS_SQL``: every row of ``ai.usage`` of the window, with the kick-off of its match (how long before it the call was made);
* ``LEDGER_SQL``: the ledger's own count and sum of the same window - the check of the total, read apart from the rows;
* ``PRODUCTION_LINKS_SQL`` and ``SHADOW_LINKS_SQL``: the rows of ``ai.pick_reviews`` that hold a call's usage id, one statement for the engine of
  production (``llm``: the selection, and the ``role`` and ``tier`` the cycle recorded) and one for the engines of the shadow, each naming its
  engines - the rule of ``tests/unit/test_engine_filter_guard.py``. The window of the reviews is the calls' window widened by ``READ_MARGIN``
  (a review that waited in a batch is stored when its answer arrives); a link to a call outside the window is never used;
* ``ROUTES_SQL``: for each call to Opus, the shadow's task that asked it (``ai.agent_tasks``, by the input hash and the match: every attempt of
  the task, not only the last one its run points at) and the routing ``router-v1`` recorded;
* ``LAB_ITEMS_SQL``: for each call to Opus answered in a batch, what its item says of itself (``ai.batch_items.context``: the battery's base);
* ``USER_LEDGER_SQL``: the readers' chronicle from its own ledger (``ai.user_usage``), by prompt and model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.cost_paths import Call, LabItem, Ledger, Link, Route

READ_MARGIN: Final = timedelta(days=1)

CALLS_SQL: Final = """
SELECT u.id, u.at, u.purpose, u.tier, u.provider, u.model, u.prompt_version, u.status, u.cost_usd, u.fixture_id, f.kickoff_at,
       (u.batch_id IS NOT NULL) AS batch, u.input_tokens, u.output_tokens, u.cached_tokens,
       COALESCE(u.cache_write_tokens, 0) AS cache_write_tokens, COALESCE(u.cache_write_1h_tokens, 0) AS cache_write_1h_tokens,
       u.agent, u.workspace
  FROM ai.usage u
  LEFT JOIN core.fixtures f ON f.id = u.fixture_id
 WHERE u.at >= %(since)s AND u.at < %(until)s
 ORDER BY u.id
"""

LEDGER_SQL: Final = """
SELECT count(*) AS calls, COALESCE(sum(cost_usd), 0) AS usd FROM ai.usage WHERE at >= %(since)s AND at < %(until)s
"""

PRODUCTION_LINKS_SQL: Final = """
SELECT DISTINCT ON (x.usage_id) x.usage_id, r.engine, r.fixture_id, r.market_key, r.selection, r.line,
       r.output ->> 'role' AS role, r.output ->> 'tier' AS tier
  FROM ai.pick_reviews r
  CROSS JOIN LATERAL unnest(r.usage_ids) AS x(usage_id)
 WHERE r.engine = 'llm' AND r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s
 ORDER BY x.usage_id, r.reviewed_at, r.id
"""
"""The engine of production. A review reused from an identical input carries the usage ids of the first one: the earliest row is the one read."""

SHADOW_LINKS_SQL: Final = """
SELECT x.usage_id, min(r.engine) AS engine, r.fixture_id, r.market_key, r.selection, r.line
  FROM ai.pick_reviews r
  CROSS JOIN LATERAL unnest(r.usage_ids) AS x(usage_id)
 WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s
 GROUP BY x.usage_id, r.fixture_id, r.market_key, r.selection, r.line
"""
"""The engines of the shadow: a call of the deliberation serves every candidate of its pass (the arms share the agents' calls), once each."""

ROUTES_SQL: Final = """
SELECT DISTINCT ON (u.id) u.id AS usage_id, t.task_kind, t.route ->> 'action' AS action, t.route ->> 'escalation' AS escalation,
       t.route -> 'fired' AS fired
  FROM ai.usage u
  JOIN ai.agent_tasks t ON t.input_hash = u.input_hash AND t.fixture_id = u.fixture_id
 WHERE u.at >= %(since)s AND u.at < %(until)s AND u.model LIKE '%%opus%%' AND u.input_hash IS NOT NULL
 ORDER BY u.id, (t.task_kind = 'escalation') DESC, t.id DESC
"""

LAB_ITEMS_SQL: Final = """
SELECT u.id AS usage_id, i.context ->> 'lab' AS lab, i.context ->> 'target' AS target, i.context ->> 'base' AS base,
       i.context ->> 'experiment' AS experiment
  FROM ai.usage u
  JOIN ai.batch_items i ON i.batch_id = u.batch_id AND i.custom_id = u.custom_id
 WHERE u.at >= %(since)s AND u.at < %(until)s AND u.model LIKE '%%opus%%' AND u.batch_id IS NOT NULL
"""

USER_LEDGER_SQL: Final = """
SELECT prompt_version, model, count(*) AS calls, COALESCE(sum(cost_usd), 0) AS usd
  FROM ai.user_usage
 WHERE at >= %(since)s AND at < %(until)s
 GROUP BY prompt_version, model
 ORDER BY 4 DESC, 1, 2
"""

STATEMENTS: Final[tuple[str, ...]] = (CALLS_SQL, LEDGER_SQL, PRODUCTION_LINKS_SQL, SHADOW_LINKS_SQL, ROUTES_SQL, LAB_ITEMS_SQL, USER_LEDGER_SQL)


def _int(x: Any) -> int:
    return 0 if x is None else int(x)


def call_of(r: Mapping[str, Any]) -> Call:
    return Call(int(r["id"]), r["at"], str(r["purpose"]), str(r["tier"]), str(r["provider"]), str(r["model"]), r.get("prompt_version"),
                str(r["status"]), Decimal(str(r["cost_usd"] or 0)), None if r.get("fixture_id") is None else int(r["fixture_id"]),
                r.get("kickoff_at"), bool(r.get("batch")), _int(r.get("input_tokens")), _int(r.get("output_tokens")),
                _int(r.get("cached_tokens")), _int(r.get("cache_write_tokens")), _int(r.get("cache_write_1h_tokens")), r.get("agent"),
                r.get("workspace"))


def link_of(r: Mapping[str, Any]) -> Link:
    return Link(int(r["usage_id"]), str(r["engine"]), int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]),
                Decimal(str(r["line"])), r.get("role"), r.get("tier"))


def route_of(r: Mapping[str, Any]) -> Route:
    fired = r.get("fired")
    return Route(int(r["usage_id"]), r.get("task_kind"), r.get("action"), r.get("escalation"),
                 tuple(str(x) for x in fired) if isinstance(fired, list) else ())


def item_of(r: Mapping[str, Any]) -> LabItem:
    return LabItem(int(r["usage_id"]), r.get("lab"), r.get("target"), r.get("base"), r.get("experiment"))


@dataclass(frozen=True, slots=True)
class Inputs:
    calls: Sequence[Call]
    links: Sequence[Link]
    routes: Sequence[Route]
    lab_items: Sequence[LabItem]
    ledger: Ledger
    user_ledger: Sequence[Mapping[str, Any]]


def read(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> Inputs:
    """Everything the report reads for ``[since, until)``, in the caller's transaction (one snapshot)."""
    window = {"since": since, "until": until}
    reviews = {"since": since - READ_MARGIN, "until": until + READ_MARGIN}
    with conn.cursor(row_factory=dict_row) as cur:
        calls = [call_of(r) for r in cur.execute(CALLS_SQL, window).fetchall()]
        total = cur.execute(LEDGER_SQL, window).fetchone() or {"calls": 0, "usd": 0}
        links = [link_of(r) for sql in (PRODUCTION_LINKS_SQL, SHADOW_LINKS_SQL) for r in cur.execute(sql, reviews).fetchall()]
        routes = [route_of(r) for r in cur.execute(ROUTES_SQL, window).fetchall()]
        items = [item_of(r) for r in cur.execute(LAB_ITEMS_SQL, window).fetchall()]
        user = [dict(r) for r in cur.execute(USER_LEDGER_SQL, window).fetchall()]
    return Inputs(calls, links, routes, items, Ledger(int(total["calls"]), Decimal(str(total["usd"]))), user)


__all__ = ["CALLS_SQL", "LAB_ITEMS_SQL", "LEDGER_SQL", "PRODUCTION_LINKS_SQL", "READ_MARGIN", "ROUTES_SQL", "SHADOW_LINKS_SQL", "STATEMENTS",
           "USER_LEDGER_SQL", "Inputs", "call_of", "item_of", "link_of", "read", "route_of"]
