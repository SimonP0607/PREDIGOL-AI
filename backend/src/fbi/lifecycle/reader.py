"""The private reading of the cycle for C-03, «Seguimiento privado» (IA-068, AD-D02; the contract itself is AD-J04).

``tracking`` answers what the screen asks of the cycle: how many selections are in each state over a period of matches
(``counts_by_state``, the ten states always present, zero included) and the selections themselves with their state, its reason,
when it was known, the evaluation and the result of the settlement, newest first with a cursor. It reads
``intel.selection_lifecycle`` and ``core.fixtures`` only, under a statement timeout, and writes nothing. It is for the owner: the
route that serves it lives under ``/api/v1/admin/`` with ``require_admin`` (AD-J04). The probability, the price taken and the CLV
of C-03 come from other pieces (AD-D01, AD-E05, AD-K01) and are not here.

The ``public_state`` each item carries is the server's (``machine.public_state``): None for every chain the shadow writer
wrote, since only the owner's authorisation makes a selection public.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_bounds
from fbi.lifecycle import machine
from fbi.lifecycle.machine import Step
from fbi.lifecycle.store import WRITER

MAX_DAYS: Final = 31
MAX_LIMIT: Final = 200
FAMILIES: Final = ("core", "corners", "cards", "goals_halves")


def family_of(market_key: str) -> str:
    """The family a market belongs to, as the screen groups them: corners, cards, the goals of the halves, the rest (core)."""
    m = market_key.upper()
    if m.startswith("CORNERS"):
        return "corners"
    if m.startswith("CARDS"):
        return "cards"
    if m.endswith(("_1H", "_2H")):
        return "goals_halves"
    return "core"


CHAINS_SQL: Final = """
SELECT s.id, s.chain_key, s.fixture_id, s.market_key, s.selection, s.line, s.layer, s.state, s.reason, s.actor,
       s.owner_signature, s.evaluation, s.evaluation_version, s.settlement_result, s.known_at,
       f.kickoff_at, cs.competition_id
  FROM intel.selection_lifecycle s
  JOIN core.fixtures f ON f.id = s.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE s.writer = %(writer)s AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
   AND (%(competition)s::bigint IS NULL OR cs.competition_id = %(competition)s)
 ORDER BY s.chain_key, s.id
"""


def tracking(conn: psycopg.Connection[Any], *, date_from: date, date_to: date, state: str | None = None,
             family: str | None = None, competition_id: int | None = None, cursor: int | None = None, limit: int = 50,
             writer: str = WRITER) -> dict[str, Any]:
    """C-03's reading of the cycle over the matches that kick off from ``date_from`` to ``date_to`` (Bogotá days, both included,
    at most ``MAX_DAYS``). ``state`` and ``family`` filter the items, never the counts of the other states; ``cursor`` is the
    ``next_cursor`` of the previous page."""
    if state is not None and state not in machine.STATES:
        raise ValueError(f"unknown state {state!r}")
    if family is not None and family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    if date_to < date_from or (date_to - date_from).days + 1 > MAX_DAYS:
        raise ValueError(f"a period is 1 to {MAX_DAYS} days")
    limit = max(1, min(limit, MAX_LIMIT))
    start, _ = day_bounds(date_from)
    _, end = day_bounds(date_to)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL statement_timeout = 30000")
        cur.execute(CHAINS_SQL, {"writer": writer, "start": start, "end": end, "competition": competition_id})
        rows = [dict(r) for r in cur.fetchall()]
    chains: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        chains.setdefault(str(r["chain_key"]), []).append(r)
    tips = []
    for chain in chains.values():
        tip = chain[-1]
        if family is not None and family_of(str(tip["market_key"])) != family:
            continue
        tips.append((tip, chain))
    counts: Counter[str] = Counter(str(t["state"]) for t, _ in tips)
    chosen = sorted((tc for tc in tips if state is None or tc[0]["state"] == state), key=lambda tc: -int(tc[0]["id"]))
    if cursor is not None:
        chosen = [tc for tc in chosen if int(tc[0]["id"]) < cursor]
    page = chosen[:limit]
    return {
        "machine_version": machine.VERSION, "writer": writer,
        "counts_by_state": {s: counts.get(s, 0) for s in machine.STATES},
        "items": [_item(t, chain) for t, chain in page],
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat(), "total": len(chosen)},
        "next_cursor": int(page[-1][0]["id"]) if len(chosen) > limit else None,
    }


def _step(r: Mapping[str, Any]) -> Step:
    return Step(str(r["state"]), str(r["reason"]), str(r["actor"]), r["owner_signature"], r["settlement_result"], r["evaluation"],
                r["evaluation_version"])


def _item(tip: Mapping[str, Any], chain: list[dict[str, Any]]) -> dict[str, Any]:
    first = chain[0]
    return {
        "fixture": {"id": int(tip["fixture_id"]), "kickoff_at": tip["kickoff_at"].isoformat(),
                    "competition_id": int(tip["competition_id"])},
        "selection": {"market": str(tip["market_key"]), "selection": str(tip["selection"]), "line": float(tip["line"]),
                      "family": family_of(str(tip["market_key"])), "layer": str(tip["layer"])},
        "state": str(tip["state"]), "reason": str(tip["reason"]), "known_at": tip["known_at"].isoformat(),
        "detected_at": first["known_at"].isoformat(), "moves": len(chain),
        "evaluation": tip["evaluation"], "evaluation_version": tip["evaluation_version"],
        "outcome": tip["settlement_result"] or _settled(chain),
        "public_state": machine.public_state([_step(r) for r in chain]),
    }


def _settled(chain: list[dict[str, Any]]) -> str | None:
    return next((str(r["settlement_result"]) for r in reversed(chain) if r["settlement_result"]), None)

