"""What the R4 comparison reads (IA-029; the comparison itself is ``fbi.ai.r4_compare``). Reads only: the caller opens the connection read-only.

Two statements read ``ai.pick_reviews``, one for the engines of production (``llm``, ``rules``) and one for those of the shadow (``ma-v1``,
``ma-v1-h``, ``cs-v1``), each naming its engines - the rule of ``tests/unit/test_engine_filter_guard.py``: a row of the shadow is never counted
by a reader of production by accident. Each gives the newest review of each selection made before the kick-off that judged something, with the
kick-off, the regulation score when the match has one, and the closing fair probability of the selection (the Shin consensus of
``market.market_consensus`` before the kick-off). A third reads the spend of the window from ``ai.usage``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.r4_compare import Review, review_of

PRODUCTION_SQL: Final = """
WITH newest AS (
  SELECT DISTINCT ON (r.engine, r.fixture_id, r.market_key, r.selection, r.line)
         r.id, r.engine, r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.decision, r.status, r.reviewed_at, r.model, r.cost_usd,
         f.kickoff_at, res.reg_goals_home, res.reg_goals_away
    FROM ai.pick_reviews r
    JOIN core.fixtures f ON f.id = r.fixture_id
    LEFT JOIN core.fixture_results res ON res.fixture_id = f.id AND f.status_group = 'finished'
   WHERE r.engine IN ('llm', 'rules') AND r.status IN ('ok', 'fallback')
     AND r.reviewed_at < f.kickoff_at AND r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s
   ORDER BY r.engine, r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC)
SELECT n.*, cp.p_fair AS p_close
  FROM newest n
  LEFT JOIN LATERAL (SELECT m.p_fair FROM market.market_consensus m
                      WHERE m.fixture_id = n.fixture_id AND m.market_key = n.market_key AND m.selection = n.selection AND m.line = n.line
                        AND m.devig_method = 'shin' AND m.as_of < n.kickoff_at
                      ORDER BY m.as_of DESC LIMIT 1) cp ON true
"""
"""The engines of production."""

SHADOW_SQL: Final = """
WITH newest AS (
  SELECT DISTINCT ON (r.engine, r.fixture_id, r.market_key, r.selection, r.line)
         r.id, r.engine, r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.decision, r.status, r.reviewed_at, r.model, r.cost_usd,
         f.kickoff_at, res.reg_goals_home, res.reg_goals_away
    FROM ai.pick_reviews r
    JOIN core.fixtures f ON f.id = r.fixture_id
    LEFT JOIN core.fixture_results res ON res.fixture_id = f.id AND f.status_group = 'finished'
   WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.status IN ('ok', 'fallback')
     AND r.reviewed_at < f.kickoff_at AND r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s
   ORDER BY r.engine, r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC)
SELECT n.*, cp.p_fair AS p_close
  FROM newest n
  LEFT JOIN LATERAL (SELECT m.p_fair FROM market.market_consensus m
                      WHERE m.fixture_id = n.fixture_id AND m.market_key = n.market_key AND m.selection = n.selection AND m.line = n.line
                        AND m.devig_method = 'shin' AND m.as_of < n.kickoff_at
                      ORDER BY m.as_of DESC LIMIT 1) cp ON true
"""
"""The engines of the shadow: an experiment's rows, read here only to be set beside production's, never counted as production."""

USAGE_SQL: Final = """
SELECT purpose, prompt_version, model, count(*) AS calls, sum(cost_usd) AS usd
  FROM ai.usage
 WHERE at >= %(since)s AND at < %(until)s
 GROUP BY purpose, prompt_version, model
"""


def reviews(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> list[Review]:
    """The newest pre-match review of each selection by each engine compared (``fbi.ai.r4_compare.ENGINES``) in ``[since, until)``."""
    out: list[Review] = []
    with conn.cursor(row_factory=dict_row) as cur:
        for sql in (PRODUCTION_SQL, SHADOW_SQL):
            cur.execute(sql, {"since": since, "until": until})
            out += [review_of(dict(r)) for r in cur.fetchall()]
    return out


def usage(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> list[dict[str, Any]]:
    """The spend of the window by purpose, prompt and model (``ai.usage``)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(USAGE_SQL, {"since": since, "until": until})
        return [dict(r) for r in cur.fetchall()]


__all__ = ["PRODUCTION_SQL", "SHADOW_SQL", "USAGE_SQL", "reviews", "usage"]
