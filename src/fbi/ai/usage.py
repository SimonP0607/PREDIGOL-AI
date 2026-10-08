"""Every model and search call priced, recorded and capped - and what the layer does as the money runs out.

The ledger (``ai.usage``) is written through its own connection, committed at once: a review that
fails later, or a transaction that rolls back, cannot hide what a call cost. Spend counts the whole AI
layer - these rows and the earlier ``analytics.ai_runs`` (the admin questions and the daily report) -
against ONE daily and ONE monthly cap.

Degradation, never breakage (the ratio is the larger of the day's and the month's spend over its cap):

    NORMAL      < 70 %   every tier
    REDUCED     >= 70 %  no final (strong) tier and no images: the best opportunities get the analysis tier
    CHEAP_ONLY  >= 90 %  the bulk (cheapest) tier only, no web search
    EXHAUSTED   >= 100 % no call at all: the deterministic reviewer alone, every model review ABSTAINs

The quantitative pipeline does not depend on any of this.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
import psycopg
from psycopg.rows import tuple_row

from fbi.ai.config import AiSettings, Tier
from fbi.ai.pricing import token_cost
from fbi.ai.providers import provider_for
from fbi.ai.providers.base import JsonRequest, LlmProvider, LlmResult, LlmUsage, ProviderError

BudgetState = Literal["NORMAL", "REDUCED", "CHEAP_ONLY", "EXHAUSTED"]
Purpose = Literal["evidence_extraction", "pick_review", "match_analysis", "postmortem", "pattern_review",
                  "web_search", "daily_report", "ask", "other"]
Connect = Callable[[], AbstractContextManager[psycopg.Connection[Any]]]
ALLOWED: dict[BudgetState, frozenset[str]] = {
    "NORMAL": frozenset({"bulk", "analysis", "final", "search"}),
    "REDUCED": frozenset({"bulk", "analysis", "search"}),
    "CHEAP_ONLY": frozenset({"bulk"}),
    "EXHAUSTED": frozenset(),
}
DOWNGRADE: dict[str, tuple[Tier, ...]] = {"final": ("final", "analysis", "bulk"), "analysis": ("analysis", "bulk"),
                                          "bulk": ("bulk",)}


@contextmanager
def ledger_connection() -> Iterator[psycopg.Connection[Any]]:
    from fbi.core.config import settings

    conn = psycopg.connect(settings.database.psycopg_url, autocommit=True, connect_timeout=3,
                           options="-c statement_timeout=10000 -c TimeZone=UTC")
    try:
        yield conn
    finally:
        conn.close()


def shared(conn: psycopg.Connection[Any]) -> Connect:
    """A connector handing out one existing connection (tests, a caller's own transaction)."""

    @contextmanager
    def _cm() -> Iterator[psycopg.Connection[Any]]:
        yield conn

    return _cm


@dataclass(frozen=True, slots=True)
class Budget:
    state: BudgetState
    spent_today: Decimal
    spent_month: Decimal
    daily: Decimal
    monthly: Decimal

    @property
    def ratio(self) -> float:
        parts = [float(self.spent_today / self.daily) if self.daily > 0 else 1.0,
                 float(self.spent_month / self.monthly) if self.monthly > 0 else 1.0]
        return max(parts)

    def allows(self, tier: str) -> bool:
        return tier in ALLOWED[self.state]

    def as_json(self) -> dict[str, Any]:
        return {"state": self.state, "spent_today_usd": str(self.spent_today), "spent_month_usd": str(self.spent_month),
                "daily_budget_usd": str(self.daily), "monthly_budget_usd": str(self.monthly),
                "ratio": round(self.ratio, 4)}


SPENT_SQL = """
SELECT COALESCE((SELECT sum(cost_usd) FROM ai.usage WHERE at >= %(since)s AND at < %(until)s), 0)
     + COALESCE((SELECT sum(cost_usd) FROM analytics.ai_runs WHERE started_at >= %(since)s AND started_at < %(until)s), 0)
"""


def spent(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> Decimal:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"since": since, "until": until})
        row = cur.fetchone()
    return Decimal(row[0]) if row and row[0] is not None else Decimal(0)


def state_for(ratio: float) -> BudgetState:
    if ratio >= 1.0:
        return "EXHAUSTED"
    if ratio >= 0.9:
        return "CHEAP_ONLY"
    if ratio >= 0.7:
        return "REDUCED"
    return "NORMAL"


def budget(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> Budget:
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    end = at + timedelta(seconds=1)
    today, this_month = spent(conn, day, end), spent(conn, month, end)
    b = Budget("NORMAL", today, this_month, settings.daily_budget, settings.monthly_budget)
    return Budget(state_for(b.ratio), today, this_month, settings.daily_budget, settings.monthly_budget)


def effective_tier(b: Budget, wanted: Tier, settings: AiSettings) -> Tier | None:
    """The tier actually used: the wanted one, or the next cheaper one the budget allows and the
    owner configured; None when no model may be called."""
    for tier in DOWNGRADE[wanted]:
        if b.allows(tier) and settings.tier(tier) is not None:
            return tier
    return None


class UsageLedger:
    def __init__(self, connect: Connect = ledger_connection) -> None:
        self._connect = connect

    def record(self, *, at: datetime, purpose: Purpose, tier: str, provider: str, model: str,
               usage: LlmUsage | None, cost: Decimal, status: str, prompt_version: str | None = None,
               fixture_id: int | None = None, latency_ms: int | None = None, error: str | None = None,
               input_hash: str | None = None, request_id: str | None = None) -> int:
        u = usage or LlmUsage()
        with self._connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "INSERT INTO ai.usage (at, purpose, tier, provider, model, prompt_version, fixture_id, input_tokens, "
                "output_tokens, cached_tokens, searches, vision_items, cost_usd, latency_ms, status, error, input_hash, "
                "request_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (at, purpose, tier, provider, model, prompt_version, fixture_id, u.input_tokens, u.output_tokens,
                 u.cached_tokens, u.searches, u.vision_items, cost, latency_ms, status,
                 None if error is None else error[:300], input_hash, request_id))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])


@dataclass
class CallOutcome:
    result: LlmResult | None
    usage_id: int | None
    tier: Tier | None
    provider: str | None
    model: str | None
    cost: Decimal
    error: str | None = None
    """A stable code: not_configured, over_budget, timeout, unavailable, rate_limited, refused, invalid_output."""


TIER_EFFORT: dict[str, str] = {"bulk": "low", "analysis": "medium", "final": "medium"}
"""Thinking spent per tier. Claude 5.5 thinks before it answers (adaptive thinking, billed as output): at the API's
default a review's 1,200 tokens went to thinking and the answer was cut (8 Oct 2026). Extraction needs little;
reviews a balanced amount - to be raised only when the shadow evaluation shows that more thinking pays."""


def with_effort(request: JsonRequest, tier: Tier | None) -> JsonRequest:
    """The request with the effort of the tier that will answer it (the budget may have lowered the tier)."""
    if request.effort is not None or tier is None:
        return request
    return replace(request, effort=TIER_EFFORT[tier])


def call_json(conn: psycopg.Connection[Any], settings: AiSettings, *, tier: Tier, purpose: Purpose,
              request: JsonRequest, at: datetime, prompt_version: str, input_hash: str,
              fixture_id: int | None = None, ledger: UsageLedger | None = None,
              transport: httpx.BaseTransport | None = None,
              provider: tuple[LlmProvider, str] | None = None) -> CallOutcome:
    """One JSON call at the best tier the budget and the configuration allow - recorded, priced,
    never raising for a provider's failure (the outcome says what happened)."""
    ledger = ledger or UsageLedger()
    b = budget(conn, at=at, settings=settings)
    if provider is not None:
        used: Tier | None = tier if b.allows(tier) else None
        chosen = provider if used is not None else None
    else:
        used = effective_tier(b, tier, settings)
        chosen = provider_for(settings, used, transport=transport) if used is not None else None
    if chosen is None:
        code = "over_budget" if b.state == "EXHAUSTED" or (settings.llm_configured and used is None) \
            else "not_configured"
        return CallOutcome(None, None, None, None, None, Decimal(0), code)
    impl, model = chosen
    request = with_effort(request, used)
    try:
        result = impl.complete_json(model, request)
    except ProviderError as exc:
        status = "timeout" if exc.code == "timeout" else "invalid_output" if exc.code == "invalid_output" \
            else "refused" if exc.code == "refused" else "failed"
        uid = ledger.record(at=at, purpose=purpose, tier=used or tier, provider=impl.name, model=model, usage=None,
                            cost=Decimal(0), status=status, prompt_version=prompt_version, fixture_id=fixture_id,
                            error=f"{exc.code}: {exc}", input_hash=input_hash)
        return CallOutcome(None, uid, used, impl.name, model, Decimal(0), exc.code)
    cost = token_cost(result.provider, model, input_tokens=result.usage.input_tokens,
                      output_tokens=result.usage.output_tokens, cached_tokens=result.usage.cached_tokens, at=at)
    uid = ledger.record(at=at, purpose=purpose, tier=used or tier, provider=result.provider, model=model,
                        usage=result.usage, cost=cost, status="ok", prompt_version=prompt_version,
                        fixture_id=fixture_id, latency_ms=result.latency_ms, input_hash=input_hash,
                        request_id=result.request_id)
    return CallOutcome(result, uid, used, result.provider, model, cost)
