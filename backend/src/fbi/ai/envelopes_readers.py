"""What the owner's cost panel reads for the envelopes of decision 12 (IA-058; the panel is ``fbi.ai.costs_v3``, the arithmetic
``fbi.ai.budget_v3.figures_of`` and ``fbi.ai.capability_budget``).

Production's envelope (US$185) pays Intelligence's Claude AND the readers' chronicle, so the panel reads the readers' own ledger
(``ai.user_usage``) beside ``ai.usage``. That ledger is the readers' AI (plan UX, A11): nothing of Intelligence's cycle, budget or
decisions reads it, and this module is how the panel does without making them load it - only the panel imports it (a test of
``tests/unit/test_user_layer_isolation.py`` says so). The budget's state and its cuts still count ``ai.usage`` alone.

Three things, all read-only:

* ``readers_by_day``: the readers' spend per Bogotá day;
* ``month_rows``: the month by envelope, prompt and purpose from both ledgers, which the register of capabilities attributes;
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


__all__ = ["MONTH_SQL", "READERS_SQL", "log_warnings", "month_rows", "readers_by_day"]
