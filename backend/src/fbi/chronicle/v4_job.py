"""The single chronicle's job (IA-103 / IA-104, plan pieces AD-F01 and AD-F02), IN SHADOW: plan, write, verify, keep. Born OFF.

SWITCH ``FBI_CHRONICLE_V4``: ``off`` (default, and any other word) - nothing is read, nothing is called, nothing is spent; ``shadow`` - every
30 minutes (``FBI_CHRONICLE_V4_MINUTES``) the worker takes the matches PrediGol Intelligence has analysed that kick off within a day (or kicked
off less than two hours ago), makes each one's content plan (``content-plan-v1``) and, when the plan has something to tell, asks the small model
(tier ``bulk``) for the chronicle (``chronicle-v4``) and keeps what the verifier lets stand (``chronicle-verify-v1``) in ``ai.chronicles``. No
reader sees it: ``FBI_MATCH_INTELLIGENCE`` is off and C-01's second delivery is another piece. ``user-narrative-v3`` goes on as it is.

WHAT IS WRITTEN: ``ai.chronicles`` only (append-only) - a plan without anything to tell is kept as an abstention (``SIN_PLAN``, ``SIN_DATOS``)
once per plan, so every analysed match has its versioned plan; a call's row is the ledger's (``ai.usage``, prompt ``chronicle-v4``); a batch
item is the queue's (``ai.batch_items``). Nothing of PrediGol Intelligence: no packet, no state, no decision, no pick, no probability.

MONEY. US$ 1 a day at most (the owner's decision for the chronicle in shadow; ``DAY_CAP_USD``; ``FBI_CHRONICLE_V4_DAY_USD`` may only LOWER it):
what the ledger spent today (Bogotá) under ``chronicle-v4`` plus what open batch items of it reserve, plus the estimate of the next call, must
fit. Then Intelligence's own budget still decides every call (``call_json``, ``BatchQueue``). The capability's month is ``chronicle_v4`` of
``fbi.ai.capability_budget`` (US$ 14, production envelope): it warns at 80 % and, since IA-137 (AD-K05), the job stops asking at 95 % of it,
the next call counted (``piece_allows``; a month that cannot be read stops it too: ``piece_month_cap``).

ROUTE. The Message Batches API (half the price) while the ``batch`` gate covers the bulk model; real time otherwise. The system block is marked
for the prompt cache either way. One attempt per input (the same plan and claims are never paid twice: ``already_answered``; a batch item still
open is ``in_flight``), at most three a match a day, at most ``MAX_PER_RUN`` a run.

The answer of a batch is taken by the worker's poll (``ai_batch_poll``) and handed to ``settle`` (purpose ``match_brief``: the chronicle is the
brief's successor, and no other task of that purpose goes to a batch), which verifies it against the very plan it was written from (kept in
the item) and keeps the row.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai import capability_budget, gates
from fbi.ai.batch import BatchQueue, Resolved, Task, estimate_cost, register
from fbi.ai.calendar import day_start, local_day, month_start
from fbi.ai.config import AiSettings, Tier
from fbi.ai.providers.base import CUT_PREFIX, JsonRequest, LlmProvider
from fbi.ai.usage import CallOutcome, UsageLedger, call_json, with_effort
from fbi.chronicle import inputs, repetition, verify
from fbi.chronicle import plan as cp
from fbi.chronicle.writer import PROMPT_VERSION, VERSION, WriterInput, Written, read, request, write

log = structlog.get_logger(__name__)

JOB: Final = "chronicle_v4"
SWITCH: Final = "FBI_CHRONICLE_V4"
MINUTES_SWITCH: Final = "FBI_CHRONICLE_V4_MINUTES"
DAY_SWITCH: Final = "FBI_CHRONICLE_V4_DAY_USD"
CAPABILITY: Final = "chronicle_v4"
"""Its key in ``fbi.ai.capability_budget``: the month's cap the job stops at 95 % of (IA-137)."""
EVERY_MINUTES: Final = 30
DAY_CAP_USD: Final = Decimal("1.00")
"""The owner's decision: the chronicle in shadow spends at most one dollar a day."""
TIER: Final[Tier] = "bulk"
PURPOSE: Final = "match_brief"
AHEAD: Final = timedelta(hours=26)
AFTER_KICKOFF: Final = timedelta(hours=2)
MAX_PER_RUN: Final = 10
MAX_PER_DAY: Final = 3
CANDIDATES: Final = 120
TYPICAL_OUTPUT: Final = 4500
"""Tokens a chronicle is expected to write, thinking included (its reservation in a batch, and the estimate of a call): measured 26 Nov 2026,
~2,000 thinking + ~1,500 visible for the answers that fitted, and more for the ones that did not."""
ANSWERED: Final = ("ok", "partial", "rejected", "invalid_output")
CUT_MARK: Final = CUT_PREFIX.strip().rstrip(":")

Mode = Literal["off", "shadow"]


def mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = (os.environ if env is None else env).get(SWITCH, "")
    return "shadow" if raw.strip().lower() == "shadow" else "off"


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    raw = (os.environ if env is None else env).get(MINUTES_SWITCH, "")
    try:
        return max(10, int(raw))
    except ValueError:
        return EVERY_MINUTES


def day_cap(env: Mapping[str, str] | None = None) -> Decimal:
    """The day's cap: US$ 1, or less when the environment says less (never more)."""
    raw = (os.environ if env is None else env).get(DAY_SWITCH, "")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return DAY_CAP_USD
    return max(Decimal(0), min(DAY_CAP_USD, value))


# ── the table ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

INSERT_SQL: Final = """
INSERT INTO ai.chronicles (fixture_id, created_at, plan_at, version, plan_version, classes_version, verify_version, figure_version,
    packet_id, plan_hash, input_hash, plan, status, abstention, content, dropped, metrics, route, provider, model, usage_id, custom_id,
    cost_usd, error, code_version)
VALUES (%(fixture)s, %(at)s, %(plan_at)s, %(version)s, %(plan_version)s, %(classes_version)s, %(verify_version)s, %(figure_version)s,
    %(packet)s, %(plan_hash)s, %(input_hash)s, %(plan)s, %(status)s, %(abstention)s, %(content)s, %(dropped)s, %(metrics)s, %(route)s,
    %(provider)s, %(model)s, %(usage_id)s, %(custom_id)s, %(cost)s, %(error)s, %(code)s)
ON CONFLICT (custom_id) WHERE custom_id IS NOT NULL DO NOTHING
RETURNING id
"""

NEWEST_SQL: Final = "SELECT plan_hash, input_hash, status FROM ai.chronicles WHERE fixture_id = %(f)s ORDER BY id DESC LIMIT 1"
ANSWERED_SQL: Final = """
SELECT 1 FROM ai.chronicles WHERE fixture_id = %(f)s AND input_hash = %(input)s AND status IN ('ok', 'partial', 'rejected', 'invalid_output')
 LIMIT 1
"""
TRIED_TODAY_SQL: Final = """
SELECT count(*) FROM ai.chronicles WHERE fixture_id = %(f)s AND created_at >= %(since)s AND route <> 'none'
"""
OPEN_ITEMS_SQL: Final = """
SELECT count(*) FROM ai.batch_items WHERE fixture_id = %(f)s AND prompt_version = %(v)s AND status IN ('submitting', 'submitted')
"""
SPENT_SQL: Final = """
SELECT (SELECT coalesce(sum(cost_usd), 0) FROM ai.usage WHERE prompt_version = %(v)s AND at >= %(since)s AND at <= %(at)s)
     + (SELECT coalesce(sum(est_cost_usd), 0) FROM ai.batch_items WHERE prompt_version = %(v)s AND status IN ('submitting', 'submitted'))
"""
"""What the chronicle spent today and what its open batch items reserve (``ai_usage_at``; the open items are few)."""


def store(conn: psycopg.Connection[Any], plan: cp.ContentPlan, *, at: datetime, status: str, route: str,
          input_hash: str | None = None, verdict: verify.Verdict | None = None, provider: str | None = None, model: str | None = None,
          usage_id: int | None = None, custom_id: str | None = None, cost: Decimal = Decimal(0), error: str | None = None,
          code_version: str | None = None, verify_version: str | None = None) -> int | None:
    """One row. ``status`` ok / partial carry the content; rejected carries ``VERIFICACION_VACIA``; abstained, the plan's code.
    ``verify_version``: the verifier's version when it is not v1 (``chronicle-verify-v2`` while the rule of repetitions drops, IA-117)."""
    content = verdict.content if verdict is not None and status in ("ok", "partial") else None
    abstention = plan.abstention if status == "abstained" else cp.EMPTY_VERIFICATION if status == "rejected" else None
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(INSERT_SQL, {
            "fixture": plan.fixture_id, "at": at, "plan_at": plan.at, "version": VERSION, "plan_version": plan.version,
            "classes_version": plan.classes_version, "verify_version": verify_version or verify.VERSION, "figure_version": plan.figure_version,
            "packet": plan.packet_id, "plan_hash": plan.hash, "input_hash": input_hash, "plan": Jsonb(plan.as_json()), "status": status,
            "abstention": abstention, "content": None if content is None else Jsonb(content),
            "dropped": Jsonb([d.as_json() for d in (verdict.dropped if verdict is not None else [])][:60]),
            "metrics": Jsonb(verdict.metrics if verdict is not None else
                             {"version": verify.VERSION} | ({"cut": True} if was_cut(error) else {})), "route": route,
            "provider": provider, "model": model, "usage_id": usage_id, "custom_id": custom_id, "cost": cost,
            "error": None if error is None else error[:300], "code": code_version})
        row = cur.fetchone()
    return None if row is None else int(row[0])


def was_cut(error: str | None) -> bool:
    """The answer was stopped at the cap of output tokens (RP-1.3): ``fbi.ai.providers.base.CUT_PREFIX`` is in its error. Kept as ``cut`` in
    the row's metrics so the cut ones are counted apart from the answers that were really invalid."""
    return error is not None and CUT_MARK in error


def spent_today(conn: psycopg.Connection[Any], at: datetime) -> Decimal:
    return _spent_since(conn, day_start(local_day(at)), at)


def spent_this_month(conn: psycopg.Connection[Any], at: datetime) -> Decimal:
    """What the chronicle spent this Bogotá month and what its open batch items reserve (IA-137: its piece's cut at 95 %)."""
    return _spent_since(conn, day_start(month_start(local_day(at))), at)


def _spent_since(conn: psycopg.Connection[Any], since: datetime, at: datetime) -> Decimal:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"v": PROMPT_VERSION, "since": since, "at": at})
        row = cur.fetchone()
    return Decimal(str(row[0])) if row is not None and row[0] is not None else Decimal(0)


def _one_value(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> Any:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return None if row is None else row[0]


# ── one match ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

Caller = Callable[[JsonRequest, WriterInput], CallOutcome]


def caller(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, ledger: UsageLedger | None = None,
           transport: httpx.BaseTransport | None = None, provider: tuple[LlmProvider, str] | None = None) -> Caller:
    """``call_json`` for the chronicle: the small tier, its prompt version, the hash of its input, the match."""
    def call(req: JsonRequest, inp: WriterInput) -> CallOutcome:
        return call_json(conn, settings, tier=TIER, purpose=PURPOSE, request=req, at=at, prompt_version=PROMPT_VERSION,
                         input_hash=inp.hash, fixture_id=inp.plan.fixture_id, ledger=ledger, transport=transport, provider=provider)
    return call


def task_of(inp: WriterInput, *, deadline: datetime | None) -> Task:
    """The batch task of one chronicle: its plan travels in the item, so its answer is verified against that very plan."""
    return Task(purpose=PURPOSE, tier=TIER, request=request(inp), prompt_version=PROMPT_VERSION, input_hash=inp.hash,
                fixture_id=inp.plan.fixture_id, deadline_at=deadline, context={"chronicle": VERSION, "plan": inp.plan.as_json()},
                typical_output=TYPICAL_OUTPUT)


@dataclass
class RunReport:
    mode: str
    status: str
    counts: Counter[str] = field(default_factory=Counter)
    cost_usd: Decimal = Decimal(0)
    queued_usd: Decimal = Decimal(0)
    written: list[int] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "mode": self.mode, "status": self.status, "counts": dict(sorted(self.counts.items())),
                "cost_usd": str(self.cost_usd), "queued_usd": str(self.queued_usd), "written": len(self.written)}


DUE_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at
  FROM core.fixtures f
 WHERE f.kickoff_at > %(kicked)s AND f.kickoff_at <= %(until)s
   AND EXISTS (SELECT 1 FROM ai.fixture_passes fp
                WHERE fp.fixture_id = f.id AND fp.status IN ('ok', 'partial') AND fp.packet_id IS NOT NULL AND fp.finished_at <= %(at)s)
 ORDER BY f.kickoff_at, f.id
 LIMIT %(limit)s
"""
"""The matches PrediGol Intelligence has analysed (any pass), kicking off within a day or less than two hours ago: «analyse once, read many»."""

Builder = Callable[[psycopg.Connection[Any], int, datetime], cp.PlanInput | str]


def _build(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> cp.PlanInput | str:
    return inputs.plan_input(conn, fixture_id, at=at)


def _batch_on(conn: psycopg.Connection[Any], settings: AiSettings) -> bool:
    tm = settings.tier(TIER)
    return tm is not None and tm.provider == "anthropic" and gates.enabled(conn, settings, "batch", model=tm.model)


def run(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, mode_word: Mode | None = None, cap: Decimal | None = None,
        ledger: UsageLedger | None = None, transport: httpx.BaseTransport | None = None,
        provider: tuple[LlmProvider, str] | None = None, builder: Builder = _build, batch: bool | None = None,
        queue: BatchQueue | None = None, code_version: str | None = None) -> RunReport:
    """One pass. Off: returns before reading anything. Each match in a savepoint of its own: one that fails is counted, never the end."""
    word = mode_word or mode()
    if word == "off":
        return RunReport("off", "off")
    limit = day_cap() if cap is None else cap
    report = RunReport(word, "ok")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DUE_SQL, {"kicked": at - AFTER_KICKOFF, "until": at + AHEAD, "at": at, "limit": CANDIDATES})
        due = [(int(r["fixture_id"]), r["kickoff_at"]) for r in cur.fetchall()]
    report.counts["due"] = len(due)
    use_batch = _batch_on(conn, settings) if batch is None else batch
    q = queue if queue is not None else (BatchQueue(conn, settings, at=at, ledger=ledger, transport=transport) if use_batch else None)
    since = day_start(local_day(at))
    asked = 0
    stop: str | None = None
    for fixture_id, kickoff in due:
        if stop is not None:
            report.counts["left_for_next_run"] += 1
            continue
        try:
            with conn.transaction():
                outcome = _one(conn, settings, fixture_id, kickoff, at=at, since=since, cap=limit, report=report, builder=builder,
                               queue=q, ledger=ledger, transport=transport, provider=provider, code_version=code_version,
                               room=asked < MAX_PER_RUN)
        except Exception as exc:  # one match never stops the others
            report.counts["errors"] += 1
            log.error("chronicle_v4.match_failed", fixture_id=fixture_id, error=f"{type(exc).__name__}: {exc}"[:300])
            continue
        report.counts[outcome] += 1
        if outcome in ("ok", "partial", "rejected", "invalid_output", "failed", "queued"):
            asked += 1
        if outcome in ("piece_day_cap", "piece_month_cap", "over_budget", "not_configured"):
            stop = outcome
    if q is not None:
        flushed = q.flush()
        report.counts["batch_sent"] += flushed.sent
        if flushed.error:
            report.counts["batch_failed"] += flushed.failed
    if report.counts["errors"]:
        report.status = "partial"
    return report


def _one(conn: psycopg.Connection[Any], settings: AiSettings, fixture_id: int, kickoff: datetime | None, *, at: datetime, since: datetime,
         cap: Decimal, report: RunReport, builder: Builder, queue: BatchQueue | None, ledger: UsageLedger | None,
         transport: httpx.BaseTransport | None, provider: tuple[LlmProvider, str] | None, code_version: str | None,
         room: bool) -> str:
    built = builder(conn, fixture_id, at)
    if isinstance(built, str):
        return built
    plan = cp.build(built)
    newest = _newest(conn, fixture_id)
    if plan.abstention is not None:
        if newest is not None and newest[0] == plan.hash:
            return "same_plan"
        rid = store(conn, plan, at=at, status="abstained", route="none", code_version=code_version)
        if rid is not None:
            report.written.append(rid)
        return f"abstained_{plan.abstention}"
    inp = WriterInput(plan, inputs.claims_for(conn, plan))
    if _one_value(conn, ANSWERED_SQL, {"f": fixture_id, "input": inp.hash}) is not None:
        return "already_answered"
    if int(_one_value(conn, OPEN_ITEMS_SQL, {"f": fixture_id, "v": PROMPT_VERSION}) or 0) > 0:
        return "in_flight"
    if int(_one_value(conn, TRIED_TODAY_SQL, {"f": fixture_id, "since": since}) or 0) >= MAX_PER_DAY:
        return "day_cap"
    if not room:
        return "left_for_next_run"
    tm = settings.tier(TIER)
    if tm is None:
        return "not_configured"
    req = request(inp)
    guess = estimate_cost(tm.model, with_effort(req, TIER), typical_output=TYPICAL_OUTPUT, at=at) * (1 if queue is not None else 2)
    if spent_today(conn, at) + guess > cap:
        return "piece_day_cap"
    if not capability_budget.piece_allows(CAPABILITY, spent_this_month(conn, at), guess).allowed:
        return "piece_month_cap"
    if queue is not None:
        admitted = queue.add(task_of(inp, deadline=kickoff))
        if admitted.status == "queued":
            report.queued_usd += admitted.est_cost
            return "queued"
        if admitted.pending:
            return "in_flight"
        # refused by the queue (a budget, two failures): real time, under the same cap
    written = write(inp, call=caller(conn, settings, at=at, ledger=ledger, transport=transport, provider=provider))
    report.cost_usd += written.cost
    if written.status in ("over_budget", "not_configured") and written.usage_id is None:
        return written.status
    rid = _keep(conn, plan, written, at=at, route="realtime", code_version=code_version)
    if rid is not None:
        report.written.append(rid)
    log.info("chronicle_v4.match", fixture_id=fixture_id, status=written.status, kept=0 if written.verdict is None else
             written.verdict.metrics.get("kept"), dropped=len(written.dropped), cost_usd=str(written.cost))
    return written.status if written.status in ANSWERED else "failed"


def _newest(conn: psycopg.Connection[Any], fixture_id: int) -> tuple[str, str | None, str] | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NEWEST_SQL, {"f": fixture_id})
        row = cur.fetchone()
    return None if row is None else (str(row[0]), row[1], str(row[2]))


def _keep(conn: psycopg.Connection[Any], plan: cp.ContentPlan, written: Written, *, at: datetime, route: str,
          custom_id: str | None = None, code_version: str | None = None) -> int | None:
    """The answer kept, after the rule of stock phrases and repetitions (IA-117, ``FBI_CHRONICLE_REPEAT``: ``shadow`` by default measures
    and drops nothing; ``on`` drops; ``off`` skips it)."""
    status = written.status if written.status in ANSWERED else "failed"
    verdict, verify_version = written.verdict, None
    word = repetition.mode()
    if verdict is not None and verdict.content is not None and word != "off":
        verdict, verify_version = repetition.apply(verdict, plan, inputs.repetition_corpus(conn, plan, at=at), mode_word=word)
        if status in ("ok", "partial"):
            status = verdict.status
    return store(conn, plan, at=at, status=status, route=route, input_hash=written.input_hash, verdict=verdict,
                 provider=written.provider, model=written.model, usage_id=written.usage_id, custom_id=custom_id, cost=written.cost,
                 error=written.error, code_version=code_version, verify_version=verify_version)


# ── the answer of a batch ───────────────────────────────────────────────────────────────────────────────────────────────────

def settle(conn: psycopg.Connection[Any], r: Resolved) -> None:
    """The answer of a chronicle's batch item: verified against the plan the item carries, kept once (``custom_id``)."""
    ctx = r.item.get("context") or {}
    if ctx.get("chronicle") != VERSION or not isinstance(ctx.get("plan"), Mapping):
        raise ValueError("an item of purpose 'match_brief' that is not a chronicle-v4")
    plan = cp.from_json(ctx["plan"])
    inp = WriterInput(plan, inputs.claims_for(conn, plan))
    input_hash = str(r.item.get("input_hash") or inp.hash)
    if r.result is None:
        code = "invalid_output" if r.error is not None and r.error.code == "invalid_output" else "failed"
        written = Written(code, input_hash, None, r.cost, "anthropic", str(r.item.get("model") or ""), r.usage_id,
                          None if r.error is None else f"{r.error.code}: {r.error}"[:300])
    else:
        verdict, error = read(r.result.data, inp)
        written = Written("invalid_output" if verdict is None else verdict.status, input_hash, verdict, r.cost, "anthropic",
                          str(r.item.get("model") or ""), r.usage_id, error)
    _keep(conn, plan, written, at=r.at, route="batch", custom_id=str(r.item["custom_id"]))
    log.info("chronicle_v4.batch_answer", fixture_id=plan.fixture_id, status=written.status, late=r.late, cost_usd=str(r.cost))


register(PURPOSE, settle)


# ── the worker's job ────────────────────────────────────────────────────────────────────────────────────────────────────────

def run_job(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None, code_version: str | None = None
            ) -> RunReport:
    """One pass with its row in the job ledger (``raw.ingestion_runs``, job ``chronicle_v4``). Off: no row, nothing read."""
    if mode() == "off":
        return RunReport("off", "off")
    from fbi.ingestion.ledger import RunCounters, RunLedger

    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": VERSION, "plan": cp.VERSION})
    conn.commit()
    counters = RunCounters()
    report = RunReport("shadow", "failed")
    try:
        report = run(conn, settings or AiSettings.from_env(), at=at, code_version=code_version)
        conn.commit()
        counters.rows_inserted = len(report.written)
        counters.errors.extend(["a match raised (see chronicle_v4.match_failed)"] * report.counts["errors"])
    finally:
        notes = ", ".join(f"{k} {v}" for k, v in sorted(report.counts.items()))
        ledger.close(run_id, counters, notes=f"{report.status}; {notes}; US$ {report.cost_usd}; reservado US$ {report.queued_usd}"[:1000])
        conn.commit()
    return report


__all__ = ["CAPABILITY", "DAY_CAP_USD", "JOB", "PURPOSE", "SWITCH", "TIER", "RunReport", "caller", "day_cap", "every_minutes", "mode", "run", "run_job",
           "settle", "spent_this_month", "spent_today", "store", "task_of", "was_cut"]
