"""What the AI layer costs, and the monthly cap it cannot exceed.

Every call's tokens are recorded (``analytics.ai_runs``) and priced from the provider's list
prices (``docs/research/AI_PROVIDER_SELECTION_2026.md``, verified 4 Oct 2026). A model not in
the table is priced at the most expensive known rate, so an unknown model can only make the
cap bite earlier, never later. Before every call the month's spend is read; at or over the cap
(``FBI_ANALYST_MONTHLY_BUDGET_USD``, default 20) the call is not made and the run ends
``over_budget``.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

PRICES: dict[str, tuple[Decimal, Decimal]] = {
    # model id prefix -> (USD per 1M input tokens, per 1M output tokens)
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
}
UNKNOWN_PRICE = (Decimal("15.00"), Decimal("75.00"))
DEFAULT_BUDGET = Decimal("20")


class OverBudgetError(RuntimeError):
    """The month's spend has reached the cap: no call is made."""


def price_of(model: str | None) -> tuple[Decimal, Decimal]:
    for prefix, price in PRICES.items():
        if model and model.startswith(prefix):
            return price
    return UNKNOWN_PRICE


def cost(model: str | None, input_tokens: int, output_tokens: int) -> Decimal:
    pin, pout = price_of(model)
    return ((pin * input_tokens + pout * output_tokens) / Decimal(1_000_000)).quantize(Decimal("0.00001"))


def monthly_budget() -> Decimal:
    raw = os.environ.get("FBI_ANALYST_MONTHLY_BUDGET_USD")
    try:
        return Decimal(raw) if raw else DEFAULT_BUDGET
    except ArithmeticError:
        return DEFAULT_BUDGET


def spent_this_month(conn: psycopg.Connection[Any], *, at: datetime) -> Decimal:
    start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(sum(cost_usd), 0) FROM analytics.ai_runs WHERE started_at >= %s", (start,))
        row = cur.fetchone()
    return Decimal(row[0]) if row else Decimal(0)


def check_budget(conn: psycopg.Connection[Any], *, at: datetime) -> Decimal:
    """The remaining budget; raises OverBudgetError when nothing is left."""
    left = monthly_budget() - spent_this_month(conn, at=at)
    if left <= 0:
        raise OverBudgetError(f"the AI budget of USD {monthly_budget()} for this month is spent")
    return left
