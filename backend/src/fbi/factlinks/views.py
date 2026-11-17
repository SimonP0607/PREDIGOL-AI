"""The reads C-07 («Fuentes del análisis») is served from (IA-122, AD-G08): the lists the evaluations wrote, as rows. Read only.

Nothing here builds a relation: it reads what each evaluation wrote at its moment (``intel.eval_source_lists``, ``intel.eval_sources``) and
the names of the entities it linked (``core.teams``, ``core.players``). Whether the match's analysis was published is the day's
``qualified`` set (``picks.daily_set_items``) - what a reader is shown as a pick, empty in the whole history on 16-nov-2026. No read of
``ai.evidence``: the quote of a fact is a third party's words and is not served."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

MAX_LISTS: Final = 40
MAX_ROWS: Final = 500


@dataclass(frozen=True, slots=True)
class SourceList:
    id: int
    run_id: int
    evaluation: str
    evaluation_version: int
    known_at: datetime
    candidates: int
    linked: int
    rejected: int
    by_relation: Mapping[str, int]
    by_rejection: Mapping[str, int]
    version: str


@dataclass(frozen=True, slots=True)
class SourceRow:
    id: int
    list_id: int
    evidence_id: int
    item_id: int | None
    linked: bool
    rejection: str | None
    relation: str | None
    level: str | None
    warning: str | None
    entity_type: str | None
    entity_id: int | None
    entity_name: str | None
    team_id: int | None
    team_name: str | None
    named_as: str | None
    kind: str
    assertion: str | None
    source_name: str
    source_url: str | None
    source_tier: str
    source_type: str
    fact_at: datetime | None
    fact_known_at: datetime
    decided_at: datetime
    e2_action: str | None
    selections: Sequence[Mapping[str, Any]]
    version: str


TABLES_SQL: Final = "SELECT to_regclass('intel.eval_source_lists') IS NOT NULL AND to_regclass('intel.eval_sources') IS NOT NULL"
LISTS_SQL: Final = """
SELECT id, run_id, evaluation, evaluation_version, known_at, candidates, linked, rejected, by_relation, by_rejection, version
  FROM intel.eval_source_lists
 WHERE fixture_id = %(fixture)s AND known_at <= %(until)s
 ORDER BY known_at DESC, id DESC LIMIT %(limit)s
"""
ROWS_SQL: Final = """
SELECT s.id, s.list_id, s.evidence_id, s.item_id, s.linked, s.rejection, s.relation, s.level, s.warning, s.entity_type, s.entity_id,
       CASE s.entity_type WHEN 'team' THEN t.name WHEN 'player' THEN p.name END AS entity_name, s.team_id, tt.name AS team_name,
       s.named_as, s.kind, s.assertion, s.source_name, s.source_url, s.source_tier, s.source_type, s.fact_at, s.fact_known_at,
       s.decided_at, s.e2_action, s.selections, s.version
  FROM intel.eval_sources s
  LEFT JOIN core.teams t ON s.entity_type = 'team' AND t.id = s.entity_id
  LEFT JOIN core.players p ON s.entity_type = 'player' AND p.id = s.entity_id
  LEFT JOIN core.teams tt ON tt.id = s.team_id
 WHERE s.list_id = ANY(%(lists)s)
 ORDER BY s.list_id, s.linked DESC, s.fact_known_at, s.id
 LIMIT %(limit)s
"""
PUBLISHED_SQL: Final = """
SELECT min(i.selected_at) FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id
 WHERE i.fixture_id = %(fixture)s AND s.source = 'qualified' AND i.selected_at <= %(at)s
"""


@dataclass(frozen=True, slots=True)
class ItemUse:
    """An evaluation that linked a fact read from one of these articles."""

    item_id: int
    fixture_id: int
    kickoff_at: datetime
    evaluation: str
    evaluation_version: int
    known_at: datetime
    relation: str
    entity_name: str | None
    entity_type: str | None
    kind: str
    assertion: str | None


BY_ITEMS_SQL: Final = """
SELECT s.item_id, s.fixture_id, f.kickoff_at, l.evaluation, l.evaluation_version, l.known_at, s.relation, s.entity_type, s.kind,
       s.assertion, CASE s.entity_type WHEN 'team' THEN t.name WHEN 'player' THEN p.name END AS entity_name
  FROM intel.eval_sources s
  JOIN intel.eval_source_lists l ON l.id = s.list_id
  JOIN core.fixtures f ON f.id = s.fixture_id
  LEFT JOIN core.teams t ON s.entity_type = 'team' AND t.id = s.entity_id
  LEFT JOIN core.players p ON s.entity_type = 'player' AND p.id = s.entity_id
 WHERE s.item_id = ANY(%(items)s) AND s.linked
 ORDER BY l.known_at DESC, s.id DESC
 LIMIT %(limit)s
"""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def tables_exist(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute(TABLES_SQL).fetchone()
    return bool(row and row[0])


def lists(conn: psycopg.Connection[Any], fixture_id: int, *, until: datetime) -> list[SourceList]:
    """The match's lists, one per evaluation, newest first (as of ``until``)."""
    return [SourceList(int(r["id"]), int(r["run_id"]), str(r["evaluation"]), int(r["evaluation_version"]), r["known_at"],
                       int(r["candidates"]), int(r["linked"]), int(r["rejected"]), dict(r["by_relation"] or {}),
                       dict(r["by_rejection"] or {}), str(r["version"]))
            for r in _rows(conn, LISTS_SQL, {"fixture": fixture_id, "until": until, "limit": MAX_LISTS})]


def rows(conn: psycopg.Connection[Any], list_ids: Sequence[int]) -> list[SourceRow]:
    if not list_ids:
        return []
    return [SourceRow(**{k: r[k] for k in SourceRow.__dataclass_fields__ if k != "selections"}, selections=list(r["selections"] or []))
            for r in _rows(conn, ROWS_SQL, {"lists": list(list_ids), "limit": MAX_ROWS})]


def by_items(conn: psycopg.Connection[Any], item_ids: Sequence[int]) -> list[ItemUse]:
    """The evaluations that linked a fact read from these articles (``news.items``), newest first."""
    if not item_ids or not tables_exist(conn):
        return []
    return [ItemUse(**{k: r[k] for k in ItemUse.__dataclass_fields__})
            for r in _rows(conn, BY_ITEMS_SQL, {"items": list(item_ids), "limit": MAX_ROWS})]


def published_at(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> datetime | None:
    """When the match's analysis was first published to readers (its first item of a ``qualified`` set), or None: never."""
    row = conn.execute(PUBLISHED_SQL, {"fixture": fixture_id, "at": at}).fetchone()
    return None if row is None else row[0]


__all__ = ["ItemUse", "SourceList", "SourceRow", "by_items", "lists", "published_at", "rows", "tables_exist"]
