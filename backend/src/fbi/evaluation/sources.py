"""What the owner's C-02 reads of a settled selection beyond its evaluation (IA-112, AD-J03): the sources its decision cited
and when the official line-up of its match was first seen. Read only.

It lives apart from the pass (``fbi.evalpass``) because the API layer reads it: it imports nothing of the AI layer or of the picks,
so the evaluation stays out of the import cycle (``tests/unit/test_architecture.py``). The one question every reader of
``ai.evidence`` asks - research v2's claims only when ``fbi.ai.gates.typed_visible`` says they are part of what the system reads -
is asked by the caller and passed in as ``typed``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

LINEUP_AT_SQL: Final = """
SELECT fixture_id, min(seen) AS first_seen FROM (
    SELECT fixture_id, first_seen_at AS seen FROM core.fixture_lineups
     WHERE fixture_id = ANY(%(fixtures)s) AND first_seen_at IS NOT NULL
    UNION ALL
    SELECT fixture_id, observed_at FROM core.fixture_lineup_arrivals WHERE fixture_id = ANY(%(fixtures)s) AND starters > 0
) x GROUP BY fixture_id
"""
"""When the official line-up was first seen: the arrivals' ledger (``core.fixture_lineup_arrivals``, IA-069) or the line-up's own
``first_seen_at``. ``fetched_at`` is NOT a first sight - the provider is read again after the match - so a line-up with neither has no
known time and the evaluation says so (``hora_de_la_alineacion_desconocida``) instead of guessing it."""

SOURCES_SQL: Final = """
SELECT e.id, e.kind, e.source_name, e.source_url, e.retrieved_at
  FROM ai.evidence e
 WHERE e.id = ANY(%(ids)s) AND (e.subject_type IS NULL OR %(typed)s)
 ORDER BY e.id
"""
"""The sources a decision cited (C-02, «Fuentes usadas»), by id, with the same question: its kind, where it was read and when PrediGol knew
it - never its words (no third-party text travels)."""


def sources(conn: psycopg.Connection[Any], ids: Sequence[int], *, typed: bool) -> list[dict[str, Any]]:
    """The sources a decision cited, at most 40, oldest id first."""
    wanted = sorted({int(i) for i in ids})[:40]
    if not wanted:
        return []
    return _rows(conn, SOURCES_SQL, {"ids": wanted, "typed": typed})


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def lineup_seen(conn: psycopg.Connection[Any], fixture_id: int) -> datetime | None:
    """When the official line-up of a match was first seen (``LINEUP_AT_SQL``), or None."""
    rows = _rows(conn, LINEUP_AT_SQL, {"fixtures": [fixture_id]})
    return rows[0]["first_seen"] if rows else None
