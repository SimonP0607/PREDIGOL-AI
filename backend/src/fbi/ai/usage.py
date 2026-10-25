"""Every model and search call priced, recorded and capped - and what the layer does as the money runs out.

The ledger (``ai.usage``) is written through its own connection, committed at once: a review that
fails later, or a transaction that rolls back, cannot hide what a call cost. Spend counts the whole AI
layer - these rows and the earlier ``analytics.ai_runs`` (the admin questions and the daily report) -
against ONE monthly budget, its hard cap (``FBI_AI_MONTHLY_BUDGET_USD``: US$180 on the server since 13 Oct 2026).

The day and the month are Bogotá's (``fbi.ai.calendar``). The day's budget ADAPTS (V2, 8 Oct 2026):

    pace    = what is left of the month before today / the days left (today included)
    load    = today's matches with a market / a typical day's (median of the last 14 opened days),
              between 0.5 and FBI_AI_DAILY_MAX_FACTOR (2): a light day spends less, an important one more
    budget  = pace x load, at most the soft target x the max factor, never more than what is left
    ceiling = 1.5 x the day's budget, never more than what is left: the month is never exceeded

Degradation, never breakage (by today's spend against today's budget; the month's cap stops everything):

    NORMAL      below the day's budget          every tier
    REDUCED     past 100 % of it                no final (strong) tier and no images
    CHEAP_ONLY  past 125 % of it                the bulk (cheapest) tier only, no web search
    EXHAUSTED   at the day's ceiling, or the    no call at all: the deterministic reviewer alone, every
                month's budget spent            model review ABSTAINs

Inside the day the passes share it (``PASS_SHARE``): the first pass may take 55 %, the second up to 75 %, the
last one the rest - the line-ups are never left without money. The month's spend crossing 50, 70, 85, 95 and 100 %
is recorded once each (``ai.budget_alerts``) and sent through the notifier.

PRIORITY (PrediGol Intelligence, 13 Oct 2026): depth on MARGINAL matches - a match of the day without any candidate -
stops first: no model brief and no web for them once today's spend reaches 80 % of today's budget, the day is no longer
NORMAL, or the month has spent 85 % (``Budget.marginal_allowed``). The candidates' analysis keeps every tier the state
allows, up to the day's ceiling: near the budget the layer reads fewer marginal matches, never less of the critical
ones.

The quantitative pipeline does not depend on any of this.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

import httpx
import psycopg
from psycopg.rows import tuple_row

from fbi.ai import gates
from fbi.ai.calendar import day_start, days_left_in_month, local_day, month_start
from fbi.ai.config import AiSettings, Tier
from fbi.ai.pricing import token_cost
from fbi.ai.providers import provider_for
from fbi.ai.providers.base import JsonRequest, LlmProvider, LlmResult, LlmUsage, ProviderError

BudgetState = Literal["NORMAL", "AJUSTE", "REDUCED", "CHEAP_ONLY", "EXHAUSTED"]
Purpose = Literal["evidence_extraction", "pick_review", "match_analysis", "match_brief", "postmortem",
                  "pattern_review", "learning", "web_search", "daily_report", "ask", "other"]
Connect = Callable[[], AbstractContextManager[psycopg.Connection[Any]]]
ALLOWED: dict[BudgetState, frozenset[str]] = {
    "NORMAL": frozenset({"bulk", "analysis", "final", "search"}),
    "AJUSTE": frozenset({"bulk", "analysis", "final", "search"}),  # budget v3: the main path's quality does not change
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


REDUCED_AT = Decimal("1.00")
CHEAP_AT = Decimal("1.25")
HARD_FACTOR = Decimal("1.5")
LOAD_MIN = 0.5
TYPICAL_DAYS = 14
MIN_TYPICAL = 3
ALERT_THRESHOLDS = (50, 70, 85, 95, 100)
MARGINAL_SHARE = Decimal("0.80")
MARGINAL_MONTH = 0.85
PASS_SHARE: dict[str, Decimal] = {"first": Decimal("0.55"), "pre": Decimal("0.75"), "final": Decimal("1.00"),
                                  "request": Decimal("1.00")}
"""How much of the day's budget may be spent by the end of each pass on the intermediate and strong models and the
web (the economical L1 brief only stops with the day's state)."""


def _money(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Budget:
    state: BudgetState
    spent_today: Decimal
    spent_month: Decimal
    daily: Decimal
    """Today's adaptive budget."""
    monthly: Decimal
    cap: Decimal = Decimal(0)
    """Today's ceiling (EXHAUSTED there)."""
    pace: Decimal = Decimal(0)
    load: float = 1.0
    days_left: int = 1
    target: Decimal = Decimal(0)
    """The owner's soft daily target (``FBI_AI_DAILY_TARGET_USD``)."""
    day: date | None = None
    version: str = "v2"
    """``v2``: the day's arithmetic of this module. ``v3``: the adaptive budget of ``fbi.ai.budget_v3`` (section 26 of the plan)."""
    projected: Decimal | None = None
    """v3: the month's PROJECTED spend of production, against ``monthly`` (its envelope)."""
    reserve_locked: Decimal = Decimal(0)
    """v3: the part of what is left that is kept for production's emergencies (released in the last five days)."""
    limit_until: datetime | None = None
    """v3: the provider said a spend limit is spent; no call is made until then, and then one tries again."""
    reasons: tuple[str, ...] = ()
    """v3: why the state is not NORMAL (``projection``, ``day_allocation``, ``day_cap``, ``month_spent``, ``api_limit``...)."""

    @property
    def ratio(self) -> float:
        """How far the day's budget and the month's are spent - the larger of the two."""
        parts = [float(self.spent_today / self.daily) if self.daily > 0 else 1.0,
                 float(self.spent_month / self.monthly) if self.monthly > 0 else 1.0]
        return max(parts)

    @property
    def month_ratio(self) -> float:
        return float(self.spent_month / self.monthly) if self.monthly > 0 else 1.0

    @property
    def remaining_month(self) -> Decimal:
        return max(Decimal(0), self.monthly - self.spent_month)

    def allows(self, tier: str) -> bool:
        return tier in ALLOWED[self.state]

    @property
    def projection_ratio(self) -> float | None:
        """v3: the projected month against the envelope (None in v2)."""
        if self.projected is None:
            return None
        return float(self.projected / self.monthly) if self.monthly > 0 else None

    @property
    def adjusting(self) -> bool:
        """v3: the budget asks for savings that leave the main path's quality alone (AJUSTE) or for more (REDUCED and below):
        dedupe, reuse, cache, Batch what can wait, drop redundant calls, postpone secondary experiments, shrink the LAB."""
        return self.state != "NORMAL"

    def marginal_allowed(self) -> bool:
        """Whether a match WITHOUT a candidate may still get the paid depth (model brief, web): only while the day is
        NORMAL (or, in v3, in AJUSTE: it changes nothing of the main path), below 80 % of its budget, and the month below
        85 % of its own."""
        return (self.state in ("NORMAL", "AJUSTE") and self.spent_today < self.daily * MARGINAL_SHARE
                and self.month_ratio < MARGINAL_MONTH)

    def pass_allows(self, pass_kind: str) -> bool:
        """Whether a paid step beyond the L1 brief (intermediate or strong model, web search) still fits the share
        of today's budget this pass may reach."""
        share = PASS_SHARE.get(pass_kind, Decimal(1))
        return self.state != "EXHAUSTED" and self.spent_today < self.daily * share

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "state": self.state, "spent_today_usd": str(_money(self.spent_today)),
            "spent_month_usd": str(_money(self.spent_month)), "daily_budget_usd": str(self.daily),
            "daily_cap_usd": str(self.cap), "daily_target_usd": str(self.target),
            "monthly_budget_usd": str(self.monthly), "remaining_month_usd": str(_money(self.remaining_month)),
            "pace_usd": str(_money(self.pace)), "load": round(self.load, 3), "days_left": self.days_left,
            "ratio": round(self.ratio, 4), "month_ratio": round(self.month_ratio, 4),
            "day": None if self.day is None else self.day.isoformat()}
        if self.version != "v2":
            ratio = self.projection_ratio
            out.update({"version": self.version,
                        "projected_month_usd": None if self.projected is None else str(_money(self.projected)),
                        "projection_ratio": None if ratio is None else round(ratio, 4),
                        "reserve_locked_usd": str(_money(self.reserve_locked)),
                        "limit_until": None if self.limit_until is None else self.limit_until.isoformat(),
                        "reasons": list(self.reasons)})
        return out


SPENT_SQL = """
SELECT COALESCE((SELECT sum(cost_usd) FROM ai.usage WHERE at >= %(since)s AND at < %(until)s), 0)
     + COALESCE((SELECT sum(cost_usd) FROM analytics.ai_runs WHERE started_at >= %(since)s AND started_at < %(until)s), 0)
"""

LOAD_SQL = """
SELECT day, fixtures_with_market FROM ai.day_plans
 WHERE stage = 'opened' AND day >= %(since)s AND day <= %(day)s
"""


def spent(conn: psycopg.Connection[Any], since: datetime, until: datetime) -> Decimal:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"since": since, "until": until})
        row = cur.fetchone()
    return Decimal(row[0]) if row and row[0] is not None else Decimal(0)


SCOPE_SPENT_SQL = """
SELECT COALESCE(sum(cost_usd), 0) FROM ai.usage_scoped WHERE scope = %(scope)s AND at >= %(since)s AND at < %(until)s
"""


def scope_spent(conn: psycopg.Connection[Any], scope: str, since: datetime, until: datetime) -> Decimal:
    """What one envelope spent in a period: ``production`` (Claude of the production workspace), ``lab`` (Claude of the LAB
    workspace) or ``exa`` (every search). The scope is derived by ``ai.scope_of`` from the tier and the workspace."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SCOPE_SPENT_SQL, {"scope": scope, "since": since, "until": until})
        row = cur.fetchone()
    return Decimal(row[0]) if row and row[0] is not None else Decimal(0)


RESERVED_SQL = """
SELECT (i.created_at AT TIME ZONE 'America/Bogota')::date, COALESCE(sum(i.est_cost_usd), 0)
  FROM ai.batch_items i JOIN ai.batches b ON b.id = i.batch_id
 WHERE i.status IN ('submitting', 'submitted') AND b.kind = ANY(%(kinds)s) GROUP BY 1
"""
RESERVED_KINDS: dict[str, list[str]] = {"production": ["production"], "lab": ["lab", "probe"]}


def reserved_by_day(conn: psycopg.Connection[Any], scope: str) -> dict[date, Decimal]:
    """What the Message Batches still open have RESERVED, per Bogotá day of their creation: the estimated cost of every item sent and
    not yet answered (``fbi.ai.batch``). The budget counts it as spent until the result arrives and the ledger holds the real cost, so
    a day's batches cannot go over it. Exa has none."""
    kinds = RESERVED_KINDS.get(scope)
    if not kinds:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(RESERVED_SQL, {"kinds": kinds})
        return {r[0]: Decimal(r[1]) for r in cur.fetchall()}


def lab_spent_month(conn: psycopg.Connection[Any], at: datetime) -> Decimal:
    """The LAB workspace's spend this month (Bogotá's), up to ``at``."""
    return scope_spent(conn, "lab", day_start(month_start(local_day(at))), at + timedelta(seconds=1))


def lab_may_spend(conn: psycopg.Connection[Any], settings: AiSettings, at: datetime) -> bool:
    """Whether an experiment of the LAB workspace may spend now. Budget v3: the LAB runs a day whole or not at all and yields to
    production first (``fbi.ai.budget_v3.lab_day``); rolled back, it is the LAB's envelope alone."""
    if gates.enabled(conn, settings, "budget_v3"):
        from fbi.ai import budget_v3

        return budget_v3.lab_day(conn, at=at, settings=settings).can_spend
    return settings.lab_monthly_budget > 0 and lab_spent_month(conn, at) < settings.lab_monthly_budget


def state_of(*, spent_today: Decimal, daily: Decimal, cap: Decimal, spent_month: Decimal,
             monthly: Decimal) -> BudgetState:
    if monthly <= 0 or spent_month >= monthly or daily <= 0 or spent_today >= cap:
        return "EXHAUSTED"
    r = spent_today / daily
    if r >= CHEAP_AT:
        return "CHEAP_ONLY"
    if r >= REDUCED_AT:
        return "REDUCED"
    return "NORMAL"


def load_factor(conn: psycopg.Connection[Any], day: date, settings: AiSettings) -> float:
    """Today's matches with a market against a typical day's (the median of the last two weeks' opened days); 1 when
    today is not opened yet or there are fewer than three days to compare with."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LOAD_SQL, {"since": day - timedelta(days=TYPICAL_DAYS), "day": day})
        rows = [(r[0], int(r[1])) for r in cur.fetchall()]
    today = next((n for d, n in rows if d == day), None)
    history = [n for d, n in rows if d < day and n > 0]
    if today is None or len(history) < MIN_TYPICAL:
        return 1.0
    typical = statistics.median(history)
    return max(LOAD_MIN, min(float(settings.daily_max_factor), today / typical))


def budget(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> Budget:
    """Today's budget of production: v3 (``fbi.ai.budget_v3``) unless the owner rolled it back (``FBI_AI_BUDGET_V3=0``)."""
    if gates.enabled(conn, settings, "budget_v3"):
        from fbi.ai import budget_v3  # here, not above: budget_v3 builds on this module

        return budget_v3.budget(conn, at=at, settings=settings)
    return budget_v2(conn, at=at, settings=settings)


def budget_v2(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> Budget:
    """The day's arithmetic of V2 (8 Oct 2026), one total for the whole layer: kept whole for the rollback."""
    day = local_day(at)
    start = day_start(day)
    end = at + timedelta(seconds=1)
    held = reserved_by_day(conn, "production")
    before = spent(conn, day_start(month_start(day)), start) + sum(
        (v for d, v in held.items() if month_start(day) <= d < day), Decimal(0))
    today = spent(conn, start, end) + held.get(day, Decimal(0))
    monthly = settings.monthly_budget
    remaining_before = max(Decimal(0), monthly - before)
    days_left = days_left_in_month(day)
    pace = remaining_before / days_left
    load = load_factor(conn, day, settings)
    ceiling = settings.daily_budget * settings.daily_max_factor
    daily = _money(min(pace * Decimal(str(round(load, 4))), ceiling, remaining_before))
    cap = _money(min(remaining_before, daily * HARD_FACTOR))
    state = state_of(spent_today=today, daily=daily, cap=cap, spent_month=before + today, monthly=monthly)
    return Budget(state, today, before + today, daily, monthly, cap, pace, load, days_left, settings.daily_budget, day)


def check_alerts(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> list[int]:
    """Record the month's thresholds crossed (50 / 70 / 85 / 95 / 100 %), each once a month. Returns the new ones. With the
    budget v3 each envelope (production, LAB, Exa) alerts on its own and production's PROJECTION alerts at 95 and 100 %."""
    if gates.enabled(conn, settings, "budget_v3"):
        from fbi.ai import budget_v3

        return budget_v3.check_alerts(conn, at=at, settings=settings)
    b = budget_v2(conn, at=at, settings=settings)
    if b.monthly <= 0:
        return []
    crossed = [t for t in ALERT_THRESHOLDS if b.spent_month * 100 >= b.monthly * t]
    new: list[int] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        for t in crossed:
            cur.execute("INSERT INTO ai.budget_alerts (month, scope, kind, threshold, created_at, spent_usd, budget_usd) "
                        "VALUES (%s, 'production', 'month', %s, %s, %s, %s) "
                        "ON CONFLICT (month, scope, kind, threshold) DO NOTHING RETURNING threshold",
                        (month_start(local_day(at)), t, at, _money(b.spent_month), b.monthly))
            if cur.fetchone() is not None:
                new.append(t)
    return new


def effective_tier(b: Budget, wanted: Tier, settings: AiSettings, *, lab: bool = False) -> Tier | None:
    """The tier actually used: the wanted one, or the next cheaper one the budget allows and the
    owner configured; None when no model may be called."""
    for tier in DOWNGRADE[wanted]:
        if b.allows(tier) and settings.tier(tier, lab=lab) is not None:
            return tier
    return None


class UsageLedger:
    def __init__(self, connect: Connect = ledger_connection) -> None:
        self._connect = connect

    def record(self, *, at: datetime, purpose: Purpose, tier: str, provider: str, model: str,
               usage: LlmUsage | None, cost: Decimal, status: str, prompt_version: str | None = None,
               fixture_id: int | None = None, latency_ms: int | None = None, error: str | None = None,
               input_hash: str | None = None, request_id: str | None = None, workspace: str | None = None,
               key_label: str | None = None, batch_id: int | None = None, custom_id: str | None = None,
               run_id: int | None = None, agent: str | None = None) -> int:
        """One call, priced. ``workspace`` and ``key_label`` are NAMES (never a key): they say whose money it was - the
        LAB's or production's - and a search has none (it is Exa's). A result of a Batch carries its ``batch_id`` and
        ``custom_id``: the database refuses to record the same result twice."""
        u = usage or LlmUsage()
        with self._connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "INSERT INTO ai.usage (at, purpose, tier, provider, model, prompt_version, fixture_id, input_tokens, "
                "output_tokens, cached_tokens, searches, vision_items, cost_usd, latency_ms, status, error, input_hash, "
                "request_id, cache_write_tokens, cache_write_1h_tokens, cache_ttl, thinking_tokens, batch_id, custom_id, "
                "workspace, key_label, run_id, agent) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (at, purpose, tier, provider, model, prompt_version, fixture_id, u.input_tokens, u.output_tokens,
                 u.cached_tokens, u.searches, u.vision_items, cost, latency_ms, status,
                 None if error is None else error[:300], input_hash, request_id, u.cache_write_tokens,
                 u.cache_write_1h_tokens, u.cache_ttl, u.thinking_tokens, batch_id, custom_id, workspace, key_label,
                 run_id, agent))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def record_limit_hit(self, *, at: datetime, provider: str, workspace: str, key_label: str | None, kind: str,
                         http_status: int, request_id: str | None = None, purpose: str | None = None) -> None:
        """The provider said a spend limit is spent (``ai.limit_hits``, append-only): the budget treats the workspace as
        exhausted for a while and asks again later, once - never in a loop."""
        kind = kind if kind in ("workspace_limit", "tier_cap") else "workspace_limit"
        with self._connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("INSERT INTO ai.limit_hits (at, provider, workspace, key_label, kind, http_status, request_id, "
                        "purpose) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (at, provider, workspace, key_label, kind, http_status, request_id, purpose))


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


def with_switches(conn: psycopg.Connection[Any], settings: AiSettings, request: JsonRequest,
                  model: str) -> JsonRequest:
    """The request with the optimisations of Phase 0 that are in force for this model (``fbi.ai.gates``): the prompt cache
    (it only marks blocks - the same tokens are read) and structured outputs. What a caller already asked for stays."""
    cache = request.cache or gates.enabled(conn, settings, "cache", model=model)
    native = request.native_schema or gates.enabled(conn, settings, "native_schema", model=model)
    if cache == request.cache and native == request.native_schema:
        return request
    return replace(request, cache=cache, native_schema=native)


def call_json(conn: psycopg.Connection[Any], settings: AiSettings, *, tier: Tier, purpose: Purpose,
              request: JsonRequest, at: datetime, prompt_version: str, input_hash: str,
              fixture_id: int | None = None, ledger: UsageLedger | None = None,
              transport: httpx.BaseTransport | None = None,
              provider: tuple[LlmProvider, str] | None = None, lab: bool = False, agent: str | None = None,
              run_id: int | None = None) -> CallOutcome:
    """One JSON call at the best tier the budget and the configuration allow - recorded, priced,
    never raising for a provider's failure (the outcome says what happened).

    ``lab``: the call is an experiment of the LAB workspace - its own key, its own name in the ledger, its own envelope.
    A provider that says a spend limit is spent is recorded (``ai.limit_hits``) and the outcome is ``over_budget``: the
    layer's rules decide, and nothing is asked again in a loop."""
    ledger = ledger or UsageLedger()
    workspace, key_label = settings.labelled(lab=lab)
    b = budget(conn, at=at, settings=settings)
    if lab and not lab_may_spend(conn, settings, at):
        return CallOutcome(None, None, None, None, None, Decimal(0), "over_budget")
    if provider is not None:
        used: Tier | None = tier if b.allows(tier) else None
        chosen = provider if used is not None else None
    else:
        used = effective_tier(b, tier, settings, lab=lab)
        chosen = provider_for(settings, used, transport=transport, lab=lab) if used is not None else None
    if chosen is None:
        code = "over_budget" if b.state == "EXHAUSTED" or (settings.llm_configured and used is None) \
            else "not_configured"
        return CallOutcome(None, None, None, None, None, Decimal(0), code)
    impl, model = chosen
    request = with_switches(conn, settings, with_effort(request, used), model)
    try:
        result = impl.complete_json(model, request)
    except ProviderError as exc:
        # An answer that came back but did not validate was billed: its tokens are counted (13 Oct 2026; before, an
        # invalid output was recorded at US$0). A cache write and a read are priced as they are billed.
        billed = exc.usage
        lost = Decimal(0) if billed is None else token_cost(
            impl.name, model, input_tokens=billed.input_tokens, output_tokens=billed.output_tokens,
            cached_tokens=billed.cached_tokens, cache_write_5m_tokens=billed.cache_write_5m_tokens,
            cache_write_1h_tokens=billed.cache_write_1h_tokens, at=at)
        if exc.code == "limit_reached":
            uid = ledger.record(at=at, purpose=purpose, tier=used or tier, provider=impl.name, model=model, usage=billed,
                                cost=lost, status="over_budget", prompt_version=prompt_version, fixture_id=fixture_id,
                                error=f"limit_reached: {exc.limit_kind or 'workspace_limit'} (HTTP {exc.status})",
                                input_hash=input_hash, request_id=exc.request_id, workspace=workspace,
                                key_label=key_label, run_id=run_id, agent=agent)
            ledger.record_limit_hit(at=at, provider=impl.name, workspace=workspace, key_label=key_label,
                                    kind=exc.limit_kind or "workspace_limit", http_status=exc.status or 0,
                                    request_id=exc.request_id, purpose=purpose)
            return CallOutcome(None, uid, used, impl.name, model, lost, "over_budget")
        status = "timeout" if exc.code == "timeout" else "invalid_output" if exc.code == "invalid_output" \
            else "refused" if exc.code == "refused" else "failed"
        uid = ledger.record(at=at, purpose=purpose, tier=used or tier, provider=impl.name, model=model, usage=billed,
                            cost=lost, status=status, prompt_version=prompt_version, fixture_id=fixture_id,
                            error=f"{exc.code}: {exc}", input_hash=input_hash, request_id=exc.request_id,
                            workspace=workspace, key_label=key_label, run_id=run_id, agent=agent)
        return CallOutcome(None, uid, used, impl.name, model, lost, exc.code)
    u = result.usage
    cost = token_cost(result.provider, model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                      cached_tokens=u.cached_tokens, cache_write_5m_tokens=u.cache_write_5m_tokens,
                      cache_write_1h_tokens=u.cache_write_1h_tokens, at=at)
    uid = ledger.record(at=at, purpose=purpose, tier=used or tier, provider=result.provider, model=model,
                        usage=u, cost=cost, status="ok", prompt_version=prompt_version,
                        fixture_id=fixture_id, latency_ms=result.latency_ms, input_hash=input_hash,
                        request_id=result.request_id, workspace=workspace, key_label=key_label, run_id=run_id,
                        agent=agent)
    return CallOutcome(result, uid, used, result.provider, model, cost)
