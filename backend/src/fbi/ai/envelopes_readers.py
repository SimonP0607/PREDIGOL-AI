"""What the owner's cost panel reads for the envelopes of decision 12 (IA-058; the panel is ``fbi.ai.costs_v3``, the arithmetic
``fbi.ai.budget_v3.figures_of`` and ``fbi.ai.capability_budget``).

Production's envelope (US$185) pays Intelligence's Claude AND the readers' chronicle, so the panel reads the readers' own ledger
(``ai.user_usage``) beside ``ai.usage``. That ledger is the readers' AI (plan UX, A11): nothing of Intelligence's cycle, budget or
decisions reads it, and this module is how the panel does without making them load it - only the panel imports it (a test of
``tests/unit/test_user_layer_isolation.py`` says so). The budget's state and its cuts still count ``ai.usage`` alone.

Four things, all read-only:

* ``readers_by_day``: the readers' spend per Bogotá day;
* ``month_rows``: the month by envelope, prompt and purpose from both ledgers, which the register of capabilities attributes;
* ``attribution_inputs``: the month by ledger, prompt, purpose, tier and agent, with its batches, cache and repeated inputs, and both
  ledgers' own totals - every dollar given to one capability (IA-137, ``fbi.ai.capability_costs``);
* ``log_warnings``: the warnings at 80 / 95 % that the panel shows, written to this process's log once per process and month (a
  restart may write one again). It writes no row and notifies no one - no reader, no message."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.ai.budget_v3 import EnvelopeWarning
from fbi.ai.capability_budget import Row
from fbi.ai.capability_costs import Row as CostRow
from fbi.ai.capability_costs import Totals
from fbi.ai.usage import _money

log = logging.getLogger("fbi.ai.envelopes")

READERS_SQL: Final = """
SELECT (at AT TIME ZONE 'America/Bogota')::date AS day, sum(cost_usd) AS cost
  FROM ai.user_usage WHERE at >= %(since)s AND at < %(until)s GROUP BY 1
"""

MONTH_SQL: Final = """
SELECT scope, prompt_version, purpose, sum(cost_usd) FROM ai.usage_scoped WHERE at >= %(since)s AND at < %(until)s GROUP BY 1, 2, 3
UNION ALL
SELECT 'production', prompt_version, purpose, sum(cost_usd) FROM ai.user_usage WHERE at >= %(since)s AND at < %(until)s GROUP BY 2, 3
"""
"""The month by envelope, prompt and purpose: Intelligence's ledger with its scope, and the readers', paid from production's envelope."""


ATTRIBUTION_SQL: Final = """
WITH u AS (
  SELECT s.scope, s.prompt_version, s.purpose, s.tier, s.agent, s.cost_usd, s.batch_id IS NOT NULL AS batch, s.input_tokens, s.cached_tokens,
         s.input_hash IS NOT NULL AND s.status = 'ok' AND s.cost_usd > 0 AS paid, s.input_hash, s.id
    FROM ai.usage_scoped s WHERE s.at >= %(since)s AND s.at < %(until)s
), n AS (
  SELECT u.*, CASE WHEN u.paid THEN row_number() OVER (PARTITION BY u.paid, u.prompt_version, u.input_hash ORDER BY u.id) END AS nth FROM u
)
SELECT 'usage' AS ledger, scope, prompt_version, purpose, tier, agent, count(*) AS calls, coalesce(sum(cost_usd), 0) AS usd,
       count(*) FILTER (WHERE batch) AS batch_calls, coalesce(sum(input_tokens), 0) AS input_tokens,
       coalesce(sum(cached_tokens), 0) AS cached_tokens, count(*) FILTER (WHERE nth > 1) AS repeat_calls,
       coalesce(sum(cost_usd) FILTER (WHERE nth > 1), 0) AS repeat_usd
  FROM n GROUP BY scope, prompt_version, purpose, tier, agent
UNION ALL
SELECT 'readers', 'production', prompt_version, purpose, tier, NULL, count(*), coalesce(sum(cost_usd), 0), 0,
       coalesce(sum(input_tokens), 0), coalesce(sum(cached_tokens), 0), 0, 0
  FROM ai.user_usage WHERE at >= %(since)s AND at < %(until)s GROUP BY prompt_version, purpose, tier
"""
"""The month's calls by ledger, scope, prompt, purpose, tier and agent (IA-137, ``fbi.ai.capability_costs``). A paid call of
Intelligence's ledger REPEATS when an earlier paid call of the window had the same prompt and input hash (``nth > 1``)."""

TOTALS_SQL: Final = """
SELECT (SELECT count(*) FROM ai.usage WHERE at >= %(since)s AND at < %(until)s),
       (SELECT coalesce(sum(cost_usd), 0) FROM ai.usage WHERE at >= %(since)s AND at < %(until)s),
       (SELECT count(*) FROM ai.user_usage WHERE at >= %(since)s AND at < %(until)s),
       (SELECT coalesce(sum(cost_usd), 0) FROM ai.user_usage WHERE at >= %(since)s AND at < %(until)s)
"""
"""The ledgers' own count and sum of the window, apart from the rows: the check of the attribution's total."""


def attribution_inputs(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> tuple[list[CostRow], Totals]:
    """The rows and the totals of ``fbi.ai.capability_costs.report`` for [since, until), in the caller's snapshot. Reading only."""
    window = {"since": since, "until": until}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(ATTRIBUTION_SQL, window)
        rows = [CostRow(str(r[0]), str(r[1]), r[2], r[3], r[4], r[5], int(r[6]), Decimal(r[7] or 0), int(r[8] or 0), int(r[9] or 0),
                        int(r[10] or 0), int(r[11] or 0), Decimal(r[12] or 0)) for r in cur.fetchall()]
        cur.execute(TOTALS_SQL, window)
        t = cur.fetchone() or (0, 0, 0, 0)
    return rows, Totals(int(t[0] or 0), Decimal(t[1] or 0), int(t[2] or 0), Decimal(t[3] or 0))


def readers_by_day(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> dict[date, Decimal]:
    """What the readers' chronicle spent per Bogotá day in [since, until)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(READERS_SQL, {"since": since, "until": until})
        return {r[0]: Decimal(r[1] or 0) for r in cur.fetchall()}


def month_rows(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> list[Row]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(MONTH_SQL, {"since": since, "until": until})
        return [Row(str(r[0]), r[1], r[2], Decimal(r[3] or 0)) for r in cur.fetchall()]


_LOGGED: set[tuple[date, str, str, int]] = set()


def log_warnings(warnings: list[EnvelopeWarning]) -> list[EnvelopeWarning]:
    """Write each warning to the log once per process and month; returns those newly written."""
    new: list[EnvelopeWarning] = []
    for w in warnings:
        key = (w.month, w.kind, w.name, w.threshold)
        if key in _LOGGED:
            continue
        _LOGGED.add(key)
        new.append(w)
        log.warning("IA-058 %s %s reached %s %% of its month: US$%s of US$%s (%s)", w.kind, w.name, w.threshold,
                    _money(w.spent), w.budget, w.month.isoformat())
    return new


__all__ = ["ATTRIBUTION_SQL", "MONTH_SQL", "READERS_SQL", "TOTALS_SQL", "attribution_inputs", "log_warnings", "month_rows", "readers_by_day"]
