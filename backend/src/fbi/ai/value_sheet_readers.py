"""The counts the value sheet (``fbi.ai.value_sheet``, RP-12.1) takes from the tables. Reading only: every statement is a SELECT."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from fbi.ai.value_sheet import Counts

FIXTURES_SQL = """
SELECT count(*) AS fixtures,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ai.evidence e WHERE e.fixture_id = f.id AND e.origin = 'web'
                                         AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s)) AS covered
  FROM core.fixtures f
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
"""
FACTS_SQL = """
SELECT count(*) AS facts,
       count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed,
       count(*) FILTER (WHERE status = 'PROBABLE') AS probable
  FROM ai.evidence
 WHERE origin = 'web' AND retrieved_at >= %(since)s AND retrieved_at < %(until)s
"""
CHRONICLES_SQL = """
SELECT count(*) FILTER (WHERE route <> 'none') AS written,
       count(*) FILTER (WHERE status IN ('ok', 'partial')) AS valid
  FROM ai.chronicles
 WHERE created_at >= %(since)s AND created_at < %(until)s AND status <> 'abstained'
"""


def counts(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> Counts:
    """What the sheet counts in ``[since, until)``. Each statement in a savepoint of its own: one that fails leaves its counts at 0."""
    params = {"since": since, "until": until}
    vals: dict[str, int] = {}
    for name, sql in (("fixtures", FIXTURES_SQL), ("facts", FACTS_SQL), ("chronicles", CHRONICLES_SQL)):
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone() or ()
                for i, v in enumerate(row):
                    vals[f"{name}{i}"] = int(v or 0)
        except psycopg.Error:
            continue
    return Counts(fixtures=vals.get("fixtures0", 0), fixtures_with_web_facts=vals.get("fixtures1", 0), web_facts=vals.get("facts0", 0),
                  web_facts_confirmed=vals.get("facts1", 0), web_facts_probable=vals.get("facts2", 0),
                  chronicles_written=vals.get("chronicles0", 0), chronicles_valid=vals.get("chronicles1", 0))


__all__ = ["CHRONICLES_SQL", "FACTS_SQL", "FIXTURES_SQL", "counts"]
