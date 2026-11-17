"""The owner's readings of the evaluations after the match (IA-112/113): the board over a period and one selection's evaluation.

Read only, under a statement timeout: ``intel.selection_evaluations`` (revision 0158) and nothing else. Where the table does not exist yet
(a database behind the code) every reading answers None, never an error: the private screens say «sin datos» for that block alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.evaluation import board as board_module
from fbi.evaluation.selection import VERSION

TIMEOUT_MS: Final = 30_000
EXISTS_SQL: Final = "SELECT to_regclass('intel.selection_evaluations') IS NOT NULL"
BOARD_SQL: Final = """
SELECT layer, family, market_key, kickoff_at, p_judged, seal, hit, p_market, clv, taken
  FROM intel.selection_evaluations
 WHERE version = %(version)s AND kickoff_at >= %(start)s AND kickoff_at < %(end)s
"""
ONE_SQL: Final = """
SELECT version, result, verdict, clv, evidence_held, evidence_contradicted, evidence_unevaluable, lineup_changed, taken
  FROM intel.selection_evaluations
 WHERE version = %(version)s AND decision_source = %(source)s AND decision_id = %(id)s
"""


def exists(conn: psycopg.Connection[Any]) -> bool:
    with conn.cursor() as cur:
        cur.execute(EXISTS_SQL)
        row = cur.fetchone()
    return bool(row and row[0])


def board(conn: psycopg.Connection[Any], *, start: datetime, end: datetime) -> dict[str, Any] | None:
    """The validation board (``board-v1``) over the evaluations of the matches that kicked off in ``[start, end)``; None without the
    table."""
    if not exists(conn):
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        cur.execute(BOARD_SQL, {"version": VERSION, "start": start, "end": end})
        rows = cur.fetchall()
    return board_module.build(board_module.from_rows(rows))


def evaluation_of(conn: psycopg.Connection[Any], source: str, decision_id: int) -> dict[str, Any] | None:
    """The evaluation of the selection whose standing decision is this one, or None."""
    if not exists(conn):
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ONE_SQL, {"version": VERSION, "source": source, "id": decision_id})
        row = cur.fetchone()
    return None if row is None else dict(row)
