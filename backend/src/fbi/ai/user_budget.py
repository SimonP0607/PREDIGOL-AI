"""The readers' AI budget (plan UX, A11): its own money and its own ledger - never PrediGol Intelligence's.

    FBI_AI_USER_MONTHLY_BUDGET_USD   the month's hard cap for the readers' AI (the owner's P8). Absent, empty, negative or
                                     unreadable: 0 - nothing is spent.

The calls of the readers' layer are recorded in ``ai.user_usage`` by ``UserUsageLedger``, a subclass of
``fbi.ai.usage.UsageLedger``; ``fbi.ai.usage`` itself is not changed. ``fbi.ai.usage.SPENT_SQL`` sums ``ai.usage`` and
``analytics.ai_runs`` only, so this spend never lowers what Intelligence may spend, and a call is made only while BOTH budgets
allow it: ``call_json`` still asks Intelligence's, the narrative asks this one first (``fbi.narrative.job``).

The day and the month are Bogotá's, as Intelligence's (``fbi.ai.calendar``). The day's budget is the pace - what is left of
the month before today over the days left, today included - and the day's ceiling is 1.5 times it: one heavy day cannot spend
the month. The state is ``fbi.ai.usage.state_of`` over those numbers (EXHAUSTED at the ceiling or with the month spent). The
month's spend crossing 50, 70, 85, 95 and 100 % drafts the owner's notice ``ai_user_budget`` once each (``audit.notifications``,
keyed by month and threshold; the worker's notifier sends it): amounts and a link, nothing of a reader.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.ai.calendar import day_start, days_left_in_month, local_day, month_start
from fbi.ai.providers.base import LlmUsage
from fbi.ai.usage import HARD_FACTOR, Budget, Purpose, UsageLedger, state_of
from fbi.core.env import environment
from fbi.notify.service import WEB_BASE, Draft

BUDGET_VAR: Final = "FBI_AI_USER_MONTHLY_BUDGET_USD"
PURPOSE: Final = "user_narrative"
ALERT_THRESHOLDS: Final = (50, 70, 85, 95, 100)

SPENT_SQL: Final = """
SELECT COALESCE(sum(cost_usd), 0) FROM ai.user_usage WHERE at >= %(since)s AND at < %(until)s
"""
"""The readers' spend between two moments - ``ai.user_usage`` only (Intelligence's is ``fbi.ai.usage.SPENT_SQL``)."""


def _money(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def monthly_budget(env: Mapping[str, str] | None = None) -> Decimal:
    """The readers' monthly cap from the environment: 0 unless the owner wrote a positive amount."""
    raw = (env if env is not None else environment()).get(BUDGET_VAR) or ""
    try:
        value = Decimal(raw.strip() or "0")
    except InvalidOperation:
        return Decimal(0)
    return value if value.is_finite() and value > 0 else Decimal(0)


def spent(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> Decimal:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"since": since, "until": until})
        row = cur.fetchone()
    return Decimal(row[0]) if row and row[0] is not None else Decimal(0)


def user_budget(conn: psycopg.Connection[Any], *, at: datetime, monthly: Decimal) -> Budget:
    """Where the readers' budget stands at ``at``: the same ``Budget`` Intelligence's is read as, from ``ai.user_usage``."""
    day = local_day(at)
    start = day_start(day)
    before = spent(conn, day_start(month_start(day)), start)
    today = spent(conn, start, at + timedelta(seconds=1))
    remaining_before = max(Decimal(0), monthly - before)
    days_left = days_left_in_month(day)
    daily = _money(remaining_before / days_left)
    cap = _money(min(remaining_before, daily * HARD_FACTOR))
    state = state_of(spent_today=today, daily=daily, cap=cap, spent_month=before + today, monthly=monthly)
    return Budget(state, today, before + today, daily, monthly, cap, daily, 1.0, days_left, Decimal(0), day)


class UserUsageLedger(UsageLedger):
    """The readers' calls go to ``ai.user_usage`` - through its own connection, committed at once, like Intelligence's: a run
    that fails later cannot hide what a call cost. ``fbi.ai.usage.call_json`` is used unchanged with this ledger."""

    def record(self, *, at: datetime, purpose: Purpose, tier: str, provider: str, model: str,
               usage: LlmUsage | None, cost: Decimal, status: str, prompt_version: str | None = None,
               fixture_id: int | None = None, latency_ms: int | None = None, error: str | None = None,
               input_hash: str | None = None, request_id: str | None = None) -> int:
        del purpose  # Intelligence's list of purposes; every call of this ledger is the readers' narrative
        u = usage or LlmUsage()
        with self._connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "INSERT INTO ai.user_usage (at, purpose, tier, provider, model, prompt_version, fixture_id, input_tokens, "
                "output_tokens, cached_tokens, cost_usd, latency_ms, status, error, input_hash, request_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (at, PURPOSE, tier, provider, model, prompt_version, fixture_id, u.input_tokens, u.output_tokens,
                 u.cached_tokens, cost, latency_ms, status, None if error is None else error[:300], input_hash,
                 request_id))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])


def _usd(x: Decimal) -> str:
    return f"US$ {_money(x):.2f}".replace(".", ",")


def alert_drafts(b: Budget) -> list[Draft]:
    """The owner's notices the month's spend has earned: one per threshold crossed, keyed by month and threshold."""
    if b.monthly <= 0 or b.day is None:
        return []
    month = month_start(b.day).isoformat()[:7]
    out: list[Draft] = []
    for t in ALERT_THRESHOLDS:
        if b.spent_month * 100 < b.monthly * t:
            continue
        stop = ("La narrativa se detuvo: los lectores ven la lectura estructurada hasta el mes que viene o hasta que subas "
                "el tope." if t >= 100 else
                "Al llegar al 100 % la narrativa se detiene sola y los lectores ven la lectura estructurada.")
        out.append(Draft(
            "ai_user_budget", f"ai_user_budget:{month}:{t}",
            f"IA de lectores: {t} % del presupuesto de {month}",
            f"Gastado {_usd(b.spent_month)} de {_usd(b.monthly)} este mes, aparte del presupuesto de Intelligence. {stop} "
            f"Consola: {WEB_BASE}/admin/ai",
            {"month": month, "threshold": t, "spent_usd": str(_money(b.spent_month)),
             "budget_usd": str(_money(b.monthly))}))
    return out


def draft_alerts(conn: psycopg.Connection[Any], *, at: datetime, monthly: Decimal) -> list[int]:
    """Draft the notices of the thresholds the month crossed that were not drafted yet. Returns the new thresholds."""
    new: list[int] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        for d in alert_drafts(user_budget(conn, at=at, monthly=monthly)):
            cur.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
                        (d.kind, d.dedup_key, d.title, d.body, json.dumps(d.payload)))
            if cur.fetchone() is not None:
                new.append(int(d.payload["threshold"]))
    return new


def overview(conn: psycopg.Connection[Any], *, at: datetime, monthly: Decimal | None = None) -> dict[str, Any]:
    """The readers' budget as the Admin Console shows it, beside Intelligence's: the cap, the spend, the state."""
    cap = monthly_budget() if monthly is None else monthly
    b = user_budget(conn, at=at, monthly=cap)
    return {"state": b.state, "monthly_budget_usd": str(_money(b.monthly)), "spent_month_usd": str(_money(b.spent_month)),
            "spent_today_usd": str(_money(b.spent_today)), "daily_budget_usd": str(b.daily), "daily_cap_usd": str(b.cap),
            "remaining_month_usd": str(_money(b.remaining_month)), "days_left": b.days_left,
            "day": None if b.day is None else b.day.isoformat()}
