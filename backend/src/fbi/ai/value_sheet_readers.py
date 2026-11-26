"""The counts the value sheet (``fbi.ai.value_sheet``, RP-12.1) takes from the tables. Reading only: every statement is a SELECT. A claim of
research v2 counts only while it is visible (``fbi.ai.gates.typed_visible``), like every reader of ``ai.evidence`` that is not its own."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.gates import typed_visible
from fbi.ai.value_sheet import Counts

FIXTURES_SQL = """
SELECT count(*) AS fixtures,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ai.evidence e WHERE e.fixture_id = f.id AND e.origin = 'web'
                                         AND (e.subject_type IS NULL OR %(typed)s)
                                         AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s)) AS covered
  FROM core.fixtures f
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
"""
FACTS_SQL = """
SELECT count(*) AS facts,
       count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed,
       count(*) FILTER (WHERE status = 'PROBABLE') AS probable
  FROM ai.evidence
 WHERE origin = 'web' AND (subject_type IS NULL OR %(typed)s) AND retrieved_at >= %(since)s AND retrieved_at < %(until)s
"""
FACTS_BY_FIXTURE_SQL = """
SELECT fixture_id, count(*) AS facts, count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed
  FROM ai.evidence
 WHERE origin = 'web' AND fixture_id IS NOT NULL AND (subject_type IS NULL OR %(typed)s)
   AND retrieved_at >= %(since)s AND retrieved_at < %(until)s
 GROUP BY fixture_id
"""
FACT_ROWS_SQL = """
SELECT kind, origin, status, source_tier, fact_schema, side, fresh_until IS NOT NULL AS has_validity, published_at IS NOT NULL AS has_date,
       subject_type IS NOT NULL AS has_entity, (source_name IS NOT NULL AND btrim(source_name) <> '') AS has_source, count(*) AS n
  FROM ai.evidence
 WHERE (subject_type IS NULL OR %(typed)s) AND retrieved_at >= %(since)s AND retrieved_at < %(until)s
 GROUP BY kind, origin, status, source_tier, fact_schema, side, has_validity, has_date, has_entity, has_source
"""
CHRONICLES_SQL = """
SELECT count(*) FILTER (WHERE route <> 'none') AS written,
       count(*) FILTER (WHERE status IN ('ok', 'partial')) AS valid
  FROM ai.chronicles
 WHERE created_at >= %(since)s AND created_at < %(until)s AND status <> 'abstained'
"""


def facts_by_fixture(
    conn: psycopg.Connection[Any], *, since: datetime, until: datetime
) -> dict[int, tuple[int, int]]:
    """The web facts of each match in ``[since, until)`` and how many of them are CONFIRMED (EXP-E8's counters, ``fbi.ai.research_yield``).
    The claims of research v2 count only while they are visible, like every reader of ``ai.evidence`` that is not its own."""
    params = {"since": since, "until": until, "typed": typed_visible(conn)}
    with conn.cursor() as cur:
        cur.execute(FACTS_BY_FIXTURE_SQL, params)
        return {int(r[0]): (int(r[1]), int(r[2])) for r in cur.fetchall()}


def fact_rows(
    conn: psycopg.Connection[Any], *, since: datetime, until: datetime, typed: bool | None = None
) -> list[dict[str, Any]]:
    """The facts of ``[since, until)`` grouped by what the schema of a context fact looks at (RP-4.1, ``fbi.ai.factor_counts``): kind, origin,
    state, tier, the mark of the schema, the side and which of the attributes the row has, with how many. Research v2's claims count only while
    they are visible, like every reader of ``ai.evidence`` that is not its own - unless the caller says ``typed=True``: a context fact is a typed
    claim by nature (its entity is its ``subject``), so the owner's measure of the schema (``scripts/ia_context_facts.py``) counts them whatever the
    gate says. It counts; nothing it reads reaches a packet, a decision or a pick."""
    params = {"since": since, "until": until, "typed": typed_visible(conn) if typed is None else typed}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FACT_ROWS_SQL, params)
        return list(cur.fetchall())


def counts(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> Counts:
    """What the sheet counts in ``[since, until)``. Each statement in a savepoint of its own: one that fails leaves its counts at 0."""
    params = {"since": since, "until": until, "typed": typed_visible(conn)}
    vals: dict[str, int] = {}
    for name, sql in (
        ("fixtures", FIXTURES_SQL),
        ("facts", FACTS_SQL),
        ("chronicles", CHRONICLES_SQL),
    ):
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone() or ()
                for i, v in enumerate(row):
                    vals[f"{name}{i}"] = int(v or 0)
        except psycopg.Error:
            continue
    return Counts(
        fixtures=vals.get("fixtures0", 0),
        fixtures_with_web_facts=vals.get("fixtures1", 0),
        web_facts=vals.get("facts0", 0),
        web_facts_confirmed=vals.get("facts1", 0),
        web_facts_probable=vals.get("facts2", 0),
        chronicles_written=vals.get("chronicles0", 0),
        chronicles_valid=vals.get("chronicles1", 0),
    )


__all__ = [
    "CHRONICLES_SQL",
    "FACTS_BY_FIXTURE_SQL",
    "FACTS_SQL",
    "FACT_ROWS_SQL",
    "FIXTURES_SQL",
    "counts",
    "fact_rows",
    "facts_by_fixture",
]
