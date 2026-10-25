"""The cost panel of the Plan Maestro IA (sections 26, 28 and 29): the THREE envelopes and what the optimisations of Phase 0 saved.

Claude of the production workspace, Claude of the LAB workspace and Exa are never one number: each is shown against its own envelope
(US$185 / 15-55-15 / 35), with the joint ceiling Claude may not pass (US$190) and the reserve production keeps. Next to them, what the
prompt cache and the Message Batches saved this month, how many briefs and reviews were reused instead of paid again, what the batches
still open have reserved, and what each switch is doing and why (``fbi.ai.gates.describe``).

THE SAVINGS ARE MEASURED, NOT ASSUMED. Each group of the ledger (a Bogotá day, a model, real time or Batch) is priced twice with the same
verified table the ledger used: as it was billed (``ai.usage.cost_usd``) and as if every input token had been fresh. The difference
is the cache's saving - it may be NEGATIVE while a cache write is not read yet, and then it says so. The Batch's saving is what the same
fresh calls would have cost in real time less what they cost at half price. The two add up (no call is counted twice).

Reading only: nothing here writes, and no key is read."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai import budget_v3, gates
from fbi.ai.batch import open_counts
from fbi.ai.calendar import day_start, days_left_in_month, local_day, month_start
from fbi.ai.config import AiSettings
from fbi.ai.pricing import BATCH_FACTOR, price_of, token_cost
from fbi.ai.usage import _money, reserved_by_day
from fbi.ai.usage import budget as budget_of

SERIES_DAYS = 14

# ``cache_write_tokens`` is everything written to the cache; ``cache_write_1h_tokens`` is the part written for one hour. The rest is 5 minutes.
TOKENS_SQL = """
SELECT (at AT TIME ZONE 'America/Bogota')::date AS day, provider, model, (batch_id IS NOT NULL) AS batch,
       count(*) AS calls, COALESCE(sum(input_tokens), 0) AS input_tokens, COALESCE(sum(output_tokens), 0) AS output_tokens,
       COALESCE(sum(cached_tokens), 0) AS cached_tokens,
       COALESCE(sum(cache_write_tokens), 0) - COALESCE(sum(cache_write_1h_tokens), 0) AS write_5m,
       COALESCE(sum(cache_write_1h_tokens), 0) AS write_1h, COALESCE(sum(cost_usd), 0) AS cost
  FROM ai.usage_scoped WHERE scope <> 'exa' AND (input_tokens > 0 OR output_tokens > 0) AND at >= %(since)s AND at < %(until)s
 GROUP BY 1, 2, 3, 4
"""

REUSE_SQL = """
SELECT COALESCE(sum((counts->>'briefs_llm')::numeric), 0) AS briefs_paid,
       COALESCE(sum((counts->>'briefs_reused')::numeric), 0) AS briefs_reused,
       COALESCE(sum((counts->>'briefs_reused_material')::numeric), 0) AS briefs_reused_material,
       COALESCE(sum((counts->>'llm_reused')::numeric), 0) AS reviews_reused,
       COALESCE(sum((counts->>'reviews_batched')::numeric), 0) AS reviews_batched
  FROM ai.cycles WHERE started_at >= %(since)s AND started_at < %(until)s
"""

EXA_SQL = """
SELECT count(*) AS searches FROM ai.usage_scoped WHERE scope = 'exa' AND status = 'ok' AND at >= %(since)s AND at < %(until)s
"""

BATCHES_SQL = """
SELECT count(*) FILTER (WHERE status IN ('submitting', 'in_progress', 'canceling')) AS open,
       count(*) FILTER (WHERE status = 'ended') AS ended,
       count(*) FILTER (WHERE status IN ('failed', 'abandoned')) AS lost,
       COALESCE(sum(n_items) FILTER (WHERE status = 'ended'), 0) AS items_ended
  FROM ai.batches WHERE kind = 'production' AND created_at >= %(since)s AND created_at < %(until)s
"""


@dataclass(frozen=True, slots=True)
class Group:
    """One line of the ledger's token sums: a Bogotá day, a model, answered in real time or in a batch."""

    day: date
    provider: str
    model: str
    batch: bool
    calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    write_5m: int
    write_1h: int
    cost: Decimal


@dataclass(frozen=True, slots=True)
class Savings:
    cache_usd: Decimal
    """Fresh-input price as billed (Batch halved when it was a batch) less what the cache made it. Negative while writes are unread."""
    batch_usd: Decimal
    """The same fresh calls in real time less at half price: only for the groups answered by a batch."""
    calls: int
    batch_calls: int
    input_tokens: int
    cached_tokens: int
    write_tokens: int

    @property
    def total_usd(self) -> Decimal:
        return self.cache_usd + self.batch_usd

    @property
    def read_share(self) -> float | None:
        """Of the input tokens, the share the provider served from its cache."""
        return round(self.cached_tokens / self.input_tokens, 4) if self.input_tokens else None

    @property
    def batch_share(self) -> float | None:
        return round(self.batch_calls / self.calls, 4) if self.calls else None


def savings(groups: Iterable[Group]) -> Savings:
    """What the cache and the Batch saved over these groups. Unknown models are left out: their price is a guess."""
    cache = batch = Decimal(0)
    calls = batch_calls = tokens_in = cached = writes = 0
    for g in groups:
        if not price_of(g.provider, g.model)[1]:
            continue
        calls += g.calls
        batch_calls += g.calls if g.batch else 0
        tokens_in += g.input_tokens
        cached += g.cached_tokens
        writes += g.write_5m + g.write_1h
        fresh_as_billed = token_cost(g.provider, g.model, input_tokens=g.input_tokens, output_tokens=g.output_tokens,
                                     batch=g.batch, at=g.day)
        cache += fresh_as_billed - g.cost
        if g.batch:
            fresh_real_time = token_cost(g.provider, g.model, input_tokens=g.input_tokens, output_tokens=g.output_tokens,
                                         at=g.day)
            batch += fresh_real_time - fresh_as_billed
    return Savings(_money(cache), _money(batch), calls, batch_calls, tokens_in, cached, writes)


def share(spent: Decimal, envelope: Decimal) -> float | None:
    return round(float(spent / envelope), 4) if envelope > 0 else None


def groups_of(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> list[Group]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TOKENS_SQL, {"since": since, "until": until})
        return [Group(r["day"], r["provider"], r["model"], bool(r["batch"]), int(r["calls"]), int(r["input_tokens"]),
                      int(r["output_tokens"]), int(r["cached_tokens"]), int(r["write_5m"]), int(r["write_1h"]),
                      Decimal(r["cost"])) for r in cur.fetchall()]


def savings_json(s: Savings) -> dict[str, Any]:
    return {"cache_usd": str(s.cache_usd), "batch_usd": str(s.batch_usd), "total_usd": str(_money(s.total_usd)),
            "calls": s.calls, "batch_calls": s.batch_calls, "batch_share": s.batch_share, "input_tokens": s.input_tokens,
            "cached_tokens": s.cached_tokens, "write_tokens": s.write_tokens, "read_share": s.read_share}


def envelopes(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> dict[str, Any]:
    """The panel: the envelopes, the joint ceiling, the savings, what is reserved for the open batches, the switches."""
    day = local_day(at)
    month_first = month_start(day)
    month_from, until = day_start(month_first), at + timedelta(seconds=1)
    series_from = min(month_from, day_start(day - timedelta(days=SERIES_DAYS - 1)))

    costs = {scope: budget_v3.costs_by_day(conn, scope, series_from, until) for scope in ("production", "lab", "exa")}

    def spent(scope: str) -> Decimal:
        return sum((c for d, c in costs[scope].items() if d >= month_first), Decimal(0))

    prod_spent, lab_spent, exa_spent = spent("production"), spent("lab"), spent("exa")
    forecast = budget_v3.forecast(conn, at=at)
    lab = budget_v3.lab_day(conn, at=at, settings=settings)
    exa = budget_v3.exa_budget(conn, at=at, settings=settings)
    budget = budget_of(conn, at=at, settings=settings)
    claude = prod_spent + lab_spent
    ceiling = settings.joint_ceiling
    held_prod = sum(reserved_by_day(conn, "production").values(), Decimal(0))
    held_lab = sum(reserved_by_day(conn, "lab").values(), Decimal(0))
    month_groups = groups_of(conn, month_from, until)
    limit_prod = budget_v3.limit_state(conn, at=at, workspace=settings.workspace)
    limit_lab = budget_v3.limit_state(conn, at=at, workspace=settings.workspace_lab)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REUSE_SQL, {"since": month_from, "until": until})
        reuse = dict(cur.fetchone() or {})
        cur.execute(BATCHES_SQL, {"since": month_from, "until": until})
        batches = dict(cur.fetchone() or {})
        cur.execute(EXA_SQL, {"since": month_from, "until": until})
        searches = int((cur.fetchone() or {}).get("searches") or 0)

    open_items = open_counts(conn, "pick_review")
    recent = [day - timedelta(days=n) for n in range(SERIES_DAYS - 1, -1, -1)]
    return {
        "month": month_first.isoformat(), "days_left": days_left_in_month(day), "budget_version": budget.version,
        "production": {
            "spent_usd": str(_money(prod_spent)), "budget_usd": str(settings.monthly_budget),
            "spent_today_usd": str(_money(costs["production"].get(day, Decimal(0)))),
            "share": share(prod_spent, settings.monthly_budget), "projected_usd": str(_money(forecast.projected)),
            "projection_share": share(forecast.projected, settings.monthly_budget), "state": budget.state,
            "reserved_for_batches_usd": str(_money(held_prod)), "reserve_usd": str(settings.reserve),
            "reserve_locked_usd": str(_money(budget.reserve_locked)),
            "run_rate_usd": str(_money(forecast.run_rate)), "unit_cost_usd": None if forecast.unit_cost is None else str(forecast.unit_cost),
            "limit": {"active": limit_prod.active, "until": None if limit_prod.until is None else limit_prod.until.isoformat(),
                      "hits": limit_prod.hits},
            "workspace": settings.workspace},
        "lab": {
            "spent_usd": str(_money(lab_spent)), "budget_usd": str(settings.lab_monthly_budget),
            "spent_today_usd": str(_money(costs["lab"].get(day, Decimal(0)))),
            "allocation_usd": str(_money(lab.allocation)), "share": share(lab_spent, settings.lab_monthly_budget),
            "allowed": lab.allowed, "reason": lab.reason, "reserved_for_batches_usd": str(_money(held_lab)),
            "limit": {"active": limit_lab.active, "until": None if limit_lab.until is None else limit_lab.until.isoformat(),
                      "hits": limit_lab.hits},
            "workspace": settings.workspace_lab},
        "exa": {
            "spent_usd": str(_money(exa_spent)), "budget_usd": str(settings.exa_monthly_budget),
            "spent_today_usd": str(_money(costs["exa"].get(day, Decimal(0)))),
            "share": share(exa_spent, settings.exa_monthly_budget), "allowed": exa.allowed, "reason": exa.reason,
            "searches": searches},
        "claude": {"spent_usd": str(_money(claude)), "ceiling_usd": str(ceiling), "share": share(claude, ceiling),
                   "projected_usd": str(_money(forecast.projected + lab_spent)),
                   "projection_share": share(forecast.projected + lab_spent, ceiling)},
        "savings": {"month": savings_json(savings(month_groups))},
        "reuse": {"briefs_paid": int(reuse.get("briefs_paid") or 0), "briefs_reused": int(reuse.get("briefs_reused") or 0),
                  "briefs_reused_material": int(reuse.get("briefs_reused_material") or 0),
                  "reviews_reused": int(reuse.get("reviews_reused") or 0),
                  "reviews_batched": int(reuse.get("reviews_batched") or 0)},
        "batch": {"open_items": sum(open_items.values()), "open_batches": int(batches.get("open") or 0),
                  "ended_batches": int(batches.get("ended") or 0), "lost_batches": int(batches.get("lost") or 0),
                  "items_ended": int(batches.get("items_ended") or 0)},
        "switches": gates.describe(conn, settings),
        "days": [{"day": d.isoformat(), "production_usd": str(_money(costs["production"].get(d, Decimal(0)))),
                  "lab_usd": str(_money(costs["lab"].get(d, Decimal(0)))), "exa_usd": str(_money(costs["exa"].get(d, Decimal(0))))}
                 for d in recent],
        "factors": {"batch": str(BATCH_FACTOR)},
    }


__all__ = ["Group", "Savings", "envelopes", "groups_of", "savings", "savings_json", "share"]
