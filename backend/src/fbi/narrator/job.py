"""The Narrator's job (``narrator-v1``): the switch, the budget, the call and the report. Born OFF.

SWITCH. ``FBI_NARRATOR``: ``shadow`` - the job builds the facts, calls the model, checks every sentence and REPORTS what it wrote
(the log and the returned report); ``on`` (or 1, true, yes) - the same: there is no storage for a pick's narrative yet, so ``on``
behaves as ``shadow`` and a reader sees nothing; anything else, the line absent included - off: nothing is read, nothing is
called, nothing is spent.

STORAGE: NONE (no migration). The readers' table the chronicle's readers table (UX-025) is the chronicle's, one row per MATCH: the chronicle's job
counts every row of a fixture for its two-hour wait and its three tries a day, whatever the version, so a pick's narrative written
there would hold the chronicle back. Its schema does not fit, and a table of its own is a migration - a later step, with the owner's
OK. Until then the narrative lives in the report (``RunReport.as_json``) and in the log line ``narrator.pick``.

MONEY. The readers' own budget, the one the chronicle uses (``FBI_AI_USER_MONTHLY_BUDGET_USD``, ``fbi.ai.user_budget``, 0 by
default: nothing is spent): asked first, then ``fbi.ai.usage.call_json`` asks Intelligence's. Each call is recorded by the readers'
ledger with the prompt version ``pick-why-v1`` and the hash of the facts.

MODEL. The tier of ``FBI_NARRATOR_TIER`` (default ``analysis``: Sonnet 5.5 in production, ``deploy/vps/app.env.example``) - the
architecture's model for a published pick. ``bulk`` (Haiku) and ``final`` are the other words; any other word is ``analysis``.

ONE CALL A PICK, no retry: a sentence the facts do not support is dropped (``fbi.narrator.verify``); when no «why» sentence stands
the pick has no narrative (``rejected``). The same facts twice in a run are paid once; facts that change (another decision) are
another input (``PickFacts.hash``): the narrative is written again.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row
from pydantic import ValidationError

from fbi.ai import user_budget
from fbi.ai.config import TIERS, AiSettings, Tier
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.usage import CallOutcome, UsageLedger, call_json
from fbi.core.env import environment
from fbi.narrator import VERSION
from fbi.narrator.facts import Identity, PickFacts, from_trace
from fbi.narrator.prompt import PROMPT_VERSION, request
from fbi.narrator.verify import Dropped, NarratorOut, verify
from fbi.observability import trace

log = structlog.get_logger(__name__)

SWITCH: Final = "FBI_NARRATOR"
TIER_SWITCH: Final = "FBI_NARRATOR_TIER"
DEFAULT_TIER: Final[Tier] = "analysis"
ON: Final = frozenset({"on", "1", "true", "yes"})
MAX_PER_RUN: Final = 20
"""Picks narrated in one run at most (a day has a handful of published picks)."""

Mode = Literal["off", "shadow", "on"]
Caller = Callable[[JsonRequest, PickFacts], CallOutcome]
"""One call of the model for one pick's facts: ``call_json`` in production, a fake in the tests."""


def narrator_mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = ((env if env is not None else environment()).get(SWITCH) or "").strip().lower()
    if raw == "shadow":
        return "shadow"
    return "on" if raw in ON else "off"


def narrator_tier(env: Mapping[str, str] | None = None) -> Tier:
    raw = ((env if env is not None else environment()).get(TIER_SWITCH) or "").strip().lower()
    return next((t for t in TIERS if t == raw), DEFAULT_TIER)


# ── the facts of a pick ───────────────────────────────────────────────────────────────────────────────────────────────

IDENTITY_SQL: Final = """
SELECT th.name AS home, ta.name AS away, c.name AS competition
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(fixture)s
"""
"""The names of the match the trace names (its teams and its competition): names a sentence may state, never a reason."""


def identity_of(conn: psycopg.Connection[Any], fixture_id: int | None) -> Identity | None:
    if fixture_id is None:
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(IDENTITY_SQL, {"fixture": fixture_id})
        row = cur.fetchone()
    return None if row is None else Identity(row["home"], row["away"], row["competition"])


def build(conn: psycopg.Connection[Any], pick_id: int) -> PickFacts | str:
    """The facts of a pick from its trace (read-only: SELECTs on the caller's connection), or why there are none."""
    t = trace.trace_of(conn, pick_id=pick_id)
    return from_trace(t.as_json(), pick_id=pick_id, identity=identity_of(conn, t.fixture_id))


# ── one pick ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    pick_id: int
    status: str
    """ok | partial | rejected | invalid_output | a provider's code (failed, timeout, over_budget, not_configured...)."""
    input_hash: str
    content: dict[str, Any] | None = None
    dropped: list[Dropped] = field(default_factory=list)
    cost: Decimal = Decimal(0)
    provider: str | None = None
    model: str | None = None
    error: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"pick_id": self.pick_id, "status": self.status, "version": VERSION, "prompt_version": PROMPT_VERSION,
                "input_hash": self.input_hash, "content": self.content, "dropped": [d.as_json() for d in self.dropped],
                "cost_usd": str(self.cost), "provider": self.provider, "model": self.model, "error": self.error}


def narrate(pf: PickFacts, *, call: Caller) -> Outcome:
    """One call for one pick's facts, then the verifier: what stands and what was dropped."""
    outcome = call(request(pf), pf)
    if outcome.result is None:
        return Outcome(pf.pick_id, outcome.error or "failed", pf.hash, cost=outcome.cost, provider=outcome.provider,
                       model=outcome.model, error=outcome.error)
    try:
        parsed = NarratorOut.model_validate(outcome.result.data)
    except ValidationError as exc:
        error = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:4])
        return Outcome(pf.pick_id, "invalid_output", pf.hash, cost=outcome.cost, provider=outcome.provider,
                       model=outcome.model, error=error[:300])
    verdict = verify(parsed, pf)
    return Outcome(pf.pick_id, verdict.status, pf.hash, verdict.content, verdict.dropped, outcome.cost, outcome.provider,
                   outcome.model)


def caller(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, tier: Tier,
           ledger: UsageLedger | None = None, transport: httpx.BaseTransport | None = None,
           provider: tuple[LlmProvider, str] | None = None, lab: bool = False) -> Caller:
    """``call_json`` for the Narrator: its tier, its prompt version, the hash of the facts, the pick's fixture."""
    def call(req: JsonRequest, pf: PickFacts) -> CallOutcome:
        return call_json(conn, settings, tier=tier, purpose="other", request=req, at=at, prompt_version=PROMPT_VERSION,
                         input_hash=pf.hash, fixture_id=pf.fixture_id, ledger=ledger, transport=transport, provider=provider,
                         lab=lab)
    return call


# ── the job ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class RunReport:
    mode: str
    status: str
    counts: Counter[str] = field(default_factory=Counter)
    cost_usd: Decimal = Decimal(0)
    outcomes: list[Outcome] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "mode": self.mode, "status": self.status, "counts": dict(sorted(self.counts.items())),
                "cost_usd": str(self.cost_usd), "outcomes": [o.as_json() for o in self.outcomes]}


Builder = Callable[[psycopg.Connection[Any], int], PickFacts | str]


def run(conn: psycopg.Connection[Any], settings: AiSettings, *, pick_ids: Sequence[int], at: datetime,
        mode: Mode | None = None, monthly: Decimal | None = None, tier: Tier | None = None,
        ledger: UsageLedger | None = None, transport: httpx.BaseTransport | None = None,
        provider: tuple[LlmProvider, str] | None = None, builder: Builder = build) -> RunReport:
    """The narrative of each pick asked for, while the switch and both budgets allow it. Off: returns at once, before reading
    anything. Writes nothing but the ledger's row of each call."""
    mode = mode or narrator_mode()
    if mode == "off":
        return RunReport("off", "off")
    cap = user_budget.monthly_budget() if monthly is None else monthly
    if cap <= 0:
        return RunReport(mode, "no_budget")
    report = RunReport(mode, "ok")
    call = caller(conn, settings, at=at, tier=tier or narrator_tier(), ledger=ledger or user_budget.UserUsageLedger(),
                  transport=transport, provider=provider)
    seen: set[str] = set()
    for i, pick_id in enumerate(dict.fromkeys(int(p) for p in pick_ids)):
        if i >= MAX_PER_RUN:
            report.counts["left_for_next_run"] += 1
            continue
        pf = builder(conn, pick_id)
        if isinstance(pf, str):
            report.counts[pf] += 1
            continue
        if pf.hash in seen:
            report.counts["same_input"] += 1
            continue
        seen.add(pf.hash)
        if user_budget.user_budget(conn, at=at, monthly=cap).state == "EXHAUSTED":
            report.counts["user_over_budget"] += 1
            break
        outcome = narrate(pf, call=call)
        report.outcomes.append(outcome)
        report.counts[outcome.status] += 1
        report.cost_usd += outcome.cost
        log.info("narrator.pick", pick_id=pick_id, mode=mode, status=outcome.status, input_hash=outcome.input_hash,
                 kept=0 if outcome.content is None else sum(len(v) for v in outcome.content["es"].values()),
                 dropped=len(outcome.dropped), cost_usd=str(outcome.cost))
        if outcome.status in ("over_budget", "not_configured"):
            break  # Intelligence's budget or no key: nothing more can be called
    return report
