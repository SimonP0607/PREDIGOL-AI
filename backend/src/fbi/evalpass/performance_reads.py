"""What the performance of the readers and of the sources is made of (IA-135, AD-K03), read from the database. Read only, under a statement
timeout; nothing here writes.

* the stances: ``intel.agent_attributions`` (``attr-v1``, the code's own rows, signal ``VERDICT``) of the matches that kicked off in the
  window, one per selection and reader - the Match and the Statistics agents are written once per engine of the shadow with the same
  stance, so the row of ``ma-v1`` is preferred; each arm of the Council is a reader of its own - with the newest ``ok`` review of the rules
  (``ai.pick_reviews``, engine ``rules``) written before kick-off;
* the facts cited: the items of ``intel.selection_evaluations`` (``eval-sel-v1``) of the window, and their sources by id through the one
  statement of ``fbi.evaluation.sources`` (with the question of ``gates.typed_visible``: research v2's claims only when it is visible).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

from fbi.ai.gates import typed_visible
from fbi.core.calendar import local_day
from fbi.evalpass.performance import Cited, Judged, reader_key
from fbi.evaluation.selection import VERSION as EVALUATION_VERSION
from fbi.evaluation.sources import SOURCES_SQL

ATTRIBUTION_VERSION: Final = "attr-v1"
"""``fbi.ai.agents.attribution.VERSION`` (held equal by a test: this package may not import the agents)."""
TIMEOUT_MS: Final = 90_000
CHUNK: Final = 500

STANCES_SQL: Final = """
WITH a AS (
    SELECT DISTINCT ON (a.fixture_id, a.market_key, a.selection, a.line, a.agent, a.agent_version,
                        CASE WHEN a.agent = 'council' THEN a.engine ELSE '*' END)
           a.fixture_id, a.market_key, a.selection, a.line, a.agent, a.agent_version,
           CASE WHEN a.agent = 'council' THEN a.engine ELSE '*' END AS arm,
           a.stance, a.outcome, a.toward_close, a.clv, f.kickoff_at
      FROM intel.agent_attributions a JOIN core.fixtures f ON f.id = a.fixture_id
     WHERE a.signal = 'VERDICT' AND a.classified_by = 'code' AND a.attribution_version = %(version)s
       AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
     ORDER BY a.fixture_id, a.market_key, a.selection, a.line, a.agent, a.agent_version,
              CASE WHEN a.agent = 'council' THEN a.engine ELSE '*' END, (a.engine = 'ma-v1') DESC, a.engine, a.id
)
SELECT a.*, r.decision AS rules_word
  FROM a
  LEFT JOIN LATERAL (
      SELECT x.decision FROM ai.pick_reviews x
       WHERE x.fixture_id = a.fixture_id AND x.market_key = a.market_key AND x.selection = a.selection AND x.line = a.line
         AND x.engine = 'rules' AND x.status = 'ok' AND x.reviewed_at < a.kickoff_at
       ORDER BY x.reviewed_at DESC, x.id DESC LIMIT 1) r ON true
 ORDER BY a.fixture_id, a.market_key, a.selection, a.line, a.agent, a.agent_version, a.arm
"""
"""One stance per settled selection and reader of the window, with the rules' newest word before kick-off (None: the rules did not
review it, and the selection is not examined)."""

CITED_SQL: Final = """
SELECT e.fixture_id, e.market_key, e.selection, e.line, e.kickoff_at, e.clv::float8 AS clv,
       (i ->> 'id')::bigint AS evidence_id, i ->> 'claim' AS claim, i ->> 'status' AS status
  FROM intel.selection_evaluations e
 CROSS JOIN LATERAL jsonb_array_elements(COALESCE(e.detail -> 'evidence' -> 'items', '[]'::jsonb)) i
 WHERE e.version = %(version)s AND e.kickoff_at >= %(start)s AND e.kickoff_at < %(end)s
"""
"""The facts each kept evaluation judged, one row per (evaluation, fact)."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _selection(market_key: str, selection: str, line: Any) -> str:
    return f"{market_key}:{selection}:{format(Decimal(line).normalize(), 'f')}"


def judged_of(rows: Iterable[Mapping[str, Any]]) -> list[Judged]:
    return [Judged(reader=reader_key(str(r["agent"]), str(r["agent_version"]), r.get("arm")), fixture_id=int(r["fixture_id"]),
                   selection=_selection(str(r["market_key"]), str(r["selection"]), r["line"]), day=local_day(r["kickoff_at"]),
                   stance=str(r["stance"]), rules_word=r.get("rules_word"), clv=None if r["clv"] is None else float(r["clv"]),
                   outcome=str(r["outcome"]), toward_close=r.get("toward_close"))
            for r in rows]


def stances(conn: psycopg.Connection[Any], *, start: datetime, end: datetime) -> list[Judged]:
    return judged_of(_rows(conn, STANCES_SQL, {"version": ATTRIBUTION_VERSION, "start": start, "end": end}))


def source_of(name: str | None, url: str | None) -> str | None:
    """The source of a fact: the host of its address without ``www.``, or its name; None when neither is known."""
    host = urlsplit(url).hostname if url else None
    if host:
        return host.lower().removeprefix("www.")
    return name.strip().lower() if name and name.strip() else None


def sources_by_id(conn: psycopg.Connection[Any], ids: Sequence[int], *, typed: bool) -> dict[int, str | None]:
    out: dict[int, str | None] = {}
    wanted = sorted(set(ids))
    for i in range(0, len(wanted), CHUNK):
        for r in _rows(conn, SOURCES_SQL, {"ids": wanted[i:i + CHUNK], "typed": typed}):
            out[int(r["id"])] = source_of(r.get("source_name"), r.get("source_url"))
    return out


def cited_of(rows: Iterable[Mapping[str, Any]], names: Mapping[int, str | None]) -> list[Cited]:
    return [Cited(evidence_id=int(r["evidence_id"]), source=names.get(int(r["evidence_id"])), fact_type=r.get("claim"),
                  status=str(r["status"]), day=local_day(r["kickoff_at"]), fixture_id=int(r["fixture_id"]),
                  selection=_selection(str(r["market_key"]), str(r["selection"]), r["line"]),
                  clv=None if r["clv"] is None else float(r["clv"]))
            for r in rows if r.get("evidence_id") is not None]


def cited(conn: psycopg.Connection[Any], *, start: datetime, end: datetime) -> list[Cited]:
    rows = _rows(conn, CITED_SQL, {"version": EVALUATION_VERSION, "start": start, "end": end})
    names = sources_by_id(conn, [int(r["evidence_id"]) for r in rows if r.get("evidence_id") is not None], typed=typed_visible(conn))
    return cited_of(rows, names)


def cited_from_evaluations(conn: psycopg.Connection[Any], evaluations: Iterable[Any]) -> list[Cited]:
    """The same facts from evaluations computed in a dry run (``fbi.evalpass.store.dry_run``), before the table has rows."""
    rows: list[dict[str, Any]] = []
    for ev in evaluations:
        r = ev.row
        for item in (ev.detail.get("evidence") or {}).get("items") or ():
            rows.append({"fixture_id": r["fixture_id"], "market_key": r["market_key"], "selection": r["selection"], "line": r["line"],
                         "kickoff_at": r["kickoff_at"], "clv": None if r["clv"] is None else float(r["clv"]),
                         "evidence_id": item.get("id"), "claim": item.get("claim"), "status": item.get("status")})
    names = sources_by_id(conn, [int(r["evidence_id"]) for r in rows if r.get("evidence_id") is not None], typed=typed_visible(conn))
    return cited_of(rows, names)


__all__ = ["ATTRIBUTION_VERSION", "CITED_SQL", "STANCES_SQL", "cited", "cited_from_evaluations", "cited_of", "judged_of", "source_of", "sources_by_id",
           "stances"]
