"""Asking the bank again (IA-047): the plan, the run, the handler of the answers, the collection and the bank's tables.

    plan     what a run would ask - every admitted run of the selection, ``REPEATS`` times - and what it would cost:
             the expected cost (the stored run's own tokens at the Batch's half price, no cache credit), a prudent one
             (its output half again, at most the request's ``max_tokens``), the worst case (every answer writes its
             ``max_tokens``) and what the queue reserves. No write, no call.
    run      the plan sent as ONE batch of the LAB, all or nothing, and only when (a) the owner confirms it
             (``confirmed_by_owner``), (b) the protocol of ``INT-C02`` is registered (``fbi.research.protocol``),
             (c) the LAB has a key, an envelope and, for each stored run, the very model it ran with, (d) the prudent
             cost fits the run's cap (``max_usd``, never above ``HARD_MAX_USD``) and (e) the worst case fits in what
             the LAB has left after keeping the shadow's own days (``headroom``), so that a replay can never be the
             reason the shadow stops for money (``budget_stop``, the excluded days of Gate B). Asking again the same
             selection finds what is already sent: nothing is paid twice.
    settle   the handler ``fbi.ai.lab.settle_lab`` calls for an answer of the bank (``context.lab = 'replay'``):
             the RAW answer is kept in its item, as the shadow's are; nothing is validated in the worker's poll.
    collect  the answers read the way the shadow reads them (the agent's own ``read`` against the rebuilt slice or
             view) into ``ai.replay_results`` (append-only, one row per stored run, variant and repetition).
    report   ``fbi.ai.replay.measure`` per scope, appended to ``ai.replay_assessments`` when it says something new.

Every request is PINNED (``JsonRequest.pinned``): the switches of production are applied once, when the plan is made,
exactly as the queue applies them to the shadow's, and nothing changes it afterwards. A request names no match
(``fixture_id`` is None) and no agent (``Task.agent``): the LAB's spend is not any match's or any agent's cost.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final, cast

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai import budget_v3, lab, router
from fbi.ai.agents import council, match, player, stats
from fbi.ai.batch import BatchClient, BatchQueue, Resolved, Task, estimate_cost
from fbi.ai.calendar import days_left_in_month, local_day
from fbi.ai.config import AiSettings, Tier
from fbi.ai.orchestrator import verdict_string
from fbi.ai.pricing import token_cost
from fbi.ai.providers.base import JsonRequest
from fbi.ai.replay import PROTOCOL_KEY, REPEATS, SAME, VERSION, bank, measure
from fbi.ai.usage import UsageLedger, with_effort, with_switches

HARD_MAX_USD: Final = Decimal("15.00")
"""No run of the bank may plan to spend more than this, whatever the caller asks (the plan's «tope por ejecución»)."""
DEFAULT_MAX_USD: Final = Decimal("5.00")
DEFAULT_LIMIT_PER_SCOPE: Final = 200
OUTPUT_MARGIN: Final = Decimal("1.5")
"""The prudent cost: each answer writes half again as much as the stored one did (never more than ``max_tokens``)."""
HEADROOM_FACTOR: Final = Decimal(2)
"""What a run leaves to the shadow: twice its typical LAB day (``budget_v3.LabDay.typical_day``) for every day left in
the month, before the worst case of the run is counted."""
MIN_TYPICAL_DAY: Final = Decimal("0.50")
"""A typical day is never taken as less than this (a month with no shadow yet still keeps room for it)."""
OPEN: Final = ("submitting", "submitted")
ANSWERED: Final = ("succeeded", "late", "invalid")
FAILED: Final = ("errored", "canceled", "expired")


def _h(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def ask_hash(variant: str, idem_key: str, repetition: int) -> str:
    """The ``input_hash`` of one ask of the bank: the variant, the stored run's own key and the repetition - so the same
    ask is one item of the queue whichever run sends it, and it is paid once."""
    return _h(VERSION, variant, idem_key, repetition)


def tier_of(model: str) -> Tier:
    """The tier whose LAB model answers a stored run (``router.TIER_OF_LEVEL`` of the model's level)."""
    return cast(Tier, router.TIER_OF_LEVEL[router.LEVEL_OF_MODEL[model]])


def _money(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.0001")))


# -- what an ask costs -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Cost:
    expected: Decimal = Decimal(0)
    prudent: Decimal = Decimal(0)
    worst: Decimal = Decimal(0)
    queue: Decimal = Decimal(0)

    def __add__(self, other: Cost) -> Cost:
        return Cost(self.expected + other.expected, self.prudent + other.prudent, self.worst + other.worst, self.queue + other.queue)

    def as_json(self) -> dict[str, str]:
        return {"expected_usd": _money(self.expected), "prudent_usd": _money(self.prudent), "worst_usd": _money(self.worst),
                "queue_reservation_usd": _money(self.queue)}


def cost_of(run: bank.StoredRun, request: JsonRequest, *, at: datetime) -> Cost:
    """What one ask of a stored run costs in the Batch: its input is the stored call's own (the same request, byte for
    byte), its output the stored one's, half again, or the most the request allows."""
    model = str(run.model)
    tokens_in = int(run.input_tokens or 0)
    tokens_out = int(run.output_tokens or 0)
    prudent_out = min(request.max_tokens, int((Decimal(tokens_out) * OUTPUT_MARGIN).to_integral_value(rounding=ROUND_CEILING)))

    def price(out: int) -> Decimal:
        return token_cost("anthropic", model, input_tokens=tokens_in, output_tokens=out, batch=True, at=at)

    return Cost(price(tokens_out), price(max(prudent_out, tokens_out)), price(max(request.max_tokens, tokens_out)),
                estimate_cost(model, request, typical_output=typical_output(run, request), at=at))


def typical_output(run: bank.StoredRun, request: JsonRequest) -> int:
    """The tokens the queue reserves for an ask's answer: the stored run's own output (at least one, at most
    ``max_tokens``)."""
    return max(1, min(int(run.output_tokens or request.max_tokens // 2), request.max_tokens))


# -- the plan ----------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PlannedAsk:
    item: bank.Item
    repetition: int
    tier: Tier
    request: JsonRequest
    """The request as it is sent: the agent's own, with the tier's effort and the switches in force, pinned."""
    cost: Cost


@dataclass(frozen=True, slots=True)
class Plan:
    run_key: str
    variant: str
    at: datetime
    selection: tuple[bank.Item, ...]
    asks: tuple[PlannedAsk, ...]
    cost: Cost
    cap: Decimal
    room: budget_v3.LabDay | None
    headroom: Decimal
    blockers: tuple[str, ...]
    selected_by: dict[str, Any] = field(default_factory=dict)

    @property
    def sendable(self) -> bool:
        return not self.blockers and bool(self.asks)

    def as_json(self) -> dict[str, Any]:
        scopes: dict[str, dict[str, Any]] = {}
        for a in self.asks:
            row = scopes.setdefault(a.item.scope, {"items": set(), "asks": 0, "cost": Cost()})
            row["items"].add(a.item.run.id)
            row["asks"] += 1
            row["cost"] = row["cost"] + a.cost
        return {
            "run": self.run_key, "variant": self.variant, "bank": VERSION, "repeats": REPEATS, "items": len(self.selection),
            "asks": len(self.asks), "by_scope": {s: {"items": len(v["items"]), "asks": v["asks"], **v["cost"].as_json()}
                                                 for s, v in sorted(scopes.items())},
            "cost": self.cost.as_json(), "cap_usd": _money(self.cap), "hard_cap_usd": _money(HARD_MAX_USD),
            "lab": None if self.room is None else self.room.as_json(), "headroom_for_the_shadow_usd": _money(self.headroom),
            "lab_left_after_worst_case_usd": None if self.room is None else _money(self.room.remaining - self.cost.worst),
            "selection": self.selected_by, "blockers": list(self.blockers)}


def headroom_of(room: budget_v3.LabDay, *, at: datetime) -> Decimal:
    """What a run leaves the shadow (``HEADROOM_FACTOR`` typical days for each day left in the month)."""
    typical = max(room.typical_day, MIN_TYPICAL_DAY)
    return (HEADROOM_FACTOR * typical * days_left_in_month(local_day(at))).quantize(Decimal("0.01"))


def sent_request(conn: psycopg.Connection[Any], settings: AiSettings, item: bank.Item, tier: Tier) -> JsonRequest:
    """The request the queue would send for the stored run today: the agent's own, the tier's effort and the switches in
    force for the model (``usage.with_switches``, as for the shadow's own tasks), then pinned."""
    model = str(item.run.model)
    request = with_switches(conn, settings, with_effort(item.ask.request, tier), model)
    return replace(request, pinned=True)


def plan(conn: psycopg.Connection[Any], settings: AiSettings, built: bank.Build, *, at: datetime, variant: str = SAME,
         scopes: Sequence[str] | None = None, limit_per_scope: int | None = DEFAULT_LIMIT_PER_SCOPE, seed: str = VERSION,
         max_usd: Decimal = DEFAULT_MAX_USD) -> Plan:
    """What a run of ``variant`` over the admitted runs of ``built`` would ask and cost, and every reason it may not be
    sent now. Reads, never writes."""
    if variant != SAME:
        raise ValueError(f"the bank knows the variant {SAME!r} only (a variant of INT-C03/C05 brings its own builder)")
    selection = bank.select(built.items, scopes=scopes, limit_per_scope=limit_per_scope, seed=seed)
    blockers: list[str] = []
    if max_usd <= 0 or max_usd > HARD_MAX_USD:
        blockers.append(f"the cap of a run is more than 0 and at most {_money(HARD_MAX_USD)} USD (asked {max_usd})")
    tiers = sorted({tier_of(str(i.run.model)) for i in selection})
    blockers += lab.blockers(settings, tiers)
    wrong: dict[str, int] = defaultdict(int)
    asks: list[PlannedAsk] = []
    total = Cost()
    for item in selection:
        tier = tier_of(str(item.run.model))
        configured = settings.tier(tier, lab=True)
        if configured is None or configured.model != item.run.model:
            wrong[f"{tier}:{item.run.model}"] += 1
            continue
        request = sent_request(conn, settings, item, tier)
        one = cost_of(item.run, request, at=at)
        for k in range(1, REPEATS + 1):
            asks.append(PlannedAsk(item, k, tier, request, one))
            total = total + one
    blockers += [f"the LAB's {k.split(':')[0]} tier does not answer with {k.split(':')[1]} ({n} stored run(s)): never asked on another model"
                 for k, n in sorted(wrong.items())]
    room = budget_v3.lab_day(conn, at=at, settings=settings)
    headroom = headroom_of(room, at=at)
    if not room.can_spend:
        blockers.append(f"the LAB may not spend today ({room.reason})")
    if total.prudent > max_usd:
        blockers.append(f"the prudent cost {_money(total.prudent)} USD is over the cap of the run ({_money(max_usd)} USD): "
                        "narrow the selection (--scope, --limit-per-scope)")
    if room.remaining - total.worst < headroom:
        blockers.append(f"the worst case {_money(total.worst)} USD would leave the LAB {_money(room.remaining - total.worst)} USD, "
                        f"less than the {_money(headroom)} USD kept for the shadow's days to the end of the month")
    if not asks:
        blockers.append("nothing to ask: no admitted run in the selection")
    run_key = f"{VERSION}:{variant}:{bank.digest(selection)[:16]}"
    selected_by = {"scopes": None if scopes is None else list(scopes), "limit_per_scope": limit_per_scope, "seed": seed,
                   "since": None if built.since is None else built.since.isoformat(),
                   "until": None if built.until is None else built.until.isoformat(), "digest": bank.digest(selection)}
    return Plan(run_key, variant, at, tuple(selection), tuple(asks), total, max_usd, room, headroom, tuple(blockers), selected_by)


# -- the bank's tables -----------------------------------------------------------------------------------------------------

BANK_SQL: Final = """
INSERT INTO ai.replay_bank_items (bank_version, source_run_id, created_at, scope, admitted, reason, fixture_id, pass_kind, known_at,
    run_started_at, agent, agent_version, prompt_version, schema_version, task_kind, model, effort, idem_key, package_hash, input_hash,
    request_hash, packet_id, package_version, candidates, stored_status, stored_units, stored_confidence, stored_cost_usd,
    stored_in_batch, stored_input_tokens, stored_output_tokens)
VALUES (%(bank)s, %(run)s, %(at)s, %(scope)s, %(admitted)s, %(reason)s, %(fixture)s, %(pass)s, %(known)s, %(started)s, %(agent)s,
    %(agent_version)s, %(prompt)s, %(schema)s, %(task)s, %(model)s, %(effort)s, %(idem)s, %(package)s, %(input)s, %(request)s,
    %(packet)s, %(package_version)s, %(candidates)s, %(status)s, %(units)s, %(confidence)s, %(cost)s, %(batch)s, %(tokens_in)s,
    %(tokens_out)s)
ON CONFLICT (bank_version, source_run_id) DO NOTHING
"""
BANK_IDS_SQL: Final = "SELECT source_run_id, id FROM ai.replay_bank_items WHERE bank_version = %(bank)s AND source_run_id = ANY(%(runs)s)"
RUN_SQL: Final = """
INSERT INTO ai.replay_runs (run_key, bank_version, variant, protocol, protocol_fingerprint, created_at, items, asks, repeats,
    estimate_usd, worst_usd, cap_usd, lab_remaining_usd, confirmed_by_owner, selection)
VALUES (%(key)s, %(bank)s, %(variant)s, %(protocol)s, %(fingerprint)s, %(at)s, %(items)s, %(asks)s, %(repeats)s, %(estimate)s,
    %(worst)s, %(cap)s, %(remaining)s, true, %(selection)s)
ON CONFLICT (run_key) DO NOTHING
RETURNING id
"""
ITEMS_SQL: Final = """
SELECT i.id, i.status, i.error, i.model, i.context, i.usage_id, u.cost_usd
  FROM ai.batch_items i LEFT JOIN ai.usage u ON u.id = i.usage_id
 WHERE i.purpose = 'other' AND i.prompt_version = %(version)s AND i.status <> 'abandoned' AND i.context ->> 'variant' = %(variant)s
 ORDER BY i.id
"""
RESULT_SQL: Final = """
INSERT INTO ai.replay_results (bank_item_id, variant, repetition, batch_item_id, usage_id, model, collected_at, status, output,
    verdict, units, problems, cost_usd)
VALUES (%(item)s, %(variant)s, %(repetition)s, %(batch_item)s, %(usage)s, %(model)s, %(at)s, %(status)s, %(output)s, %(verdict)s,
    %(units)s, %(problems)s, %(cost)s)
ON CONFLICT (bank_item_id, variant, repetition) DO NOTHING
"""
RESULTS_SQL: Final = """
SELECT b.source_run_id, r.repetition, r.status, r.units, r.output, r.cost_usd
  FROM ai.replay_results r JOIN ai.replay_bank_items b ON b.id = r.bank_item_id
 WHERE b.bank_version = %(bank)s AND r.variant = %(variant)s
 ORDER BY b.source_run_id, r.repetition
"""
STORED_SQL: Final = """
SELECT source_run_id, scope, fixture_id, stored_status, stored_units, stored_confidence FROM ai.replay_bank_items
 WHERE bank_version = %(bank)s AND admitted AND source_run_id = ANY(%(runs)s)
"""
NEWEST_ASSESSMENT_SQL: Final = """
SELECT evidence_hash FROM ai.replay_assessments WHERE bank_version = %(bank)s AND variant = %(variant)s AND scope = %(scope)s
   AND protocol = %(protocol)s ORDER BY at DESC, id DESC LIMIT 1
"""
ASSESSMENT_SQL: Final = """
INSERT INTO ai.replay_assessments (at, bank_version, variant, scope, protocol, protocol_fingerprint, method, verdict, evidence,
    evidence_hash)
VALUES (%(at)s, %(bank)s, %(variant)s, %(scope)s, %(protocol)s, %(fingerprint)s, %(method)s, %(verdict)s, %(evidence)s, %(hash)s)
RETURNING id
"""


def _bank_row(run: bank.StoredRun, *, scope: str, at: datetime, item: bank.Item | None, reason: str | None) -> dict[str, Any]:
    ask = None if item is None else item.ask
    return {"bank": VERSION, "run": run.id, "at": at, "scope": scope, "admitted": item is not None, "reason": reason, "fixture": run.fixture_id,
            "pass": run.pass_kind, "known": run.known_at, "started": run.started_at, "agent": run.agent, "agent_version": run.agent_version,
            "prompt": run.prompt_version, "schema": run.schema_version, "task": run.task_kind, "model": run.model, "effort": run.effort,
            "idem": run.idem_key, "package": run.package_hash, "input": None if ask is None else ask.identity.input_hash,
            "request": None if ask is None else ask.request_hash, "packet": run.packet_id, "package_version": run.package_version,
            "candidates": list(run.candidates), "status": run.status, "units": Jsonb({} if item is None else item.units),
            "confidence": Jsonb({} if item is None else item.confidence), "cost": run.cost, "batch": run.in_batch,
            "tokens_in": run.input_tokens, "tokens_out": run.output_tokens}


def write_bank(conn: psycopg.Connection[Any], built: bank.Build, *, at: datetime) -> dict[int, int]:
    """Append every run ``built`` read - admitted or excluded with its code - to ``ai.replay_bank_items`` (a run already
    there stays as it was: the table is append-only). Returns the bank's id of each run. The caller commits."""
    with conn.cursor(row_factory=tuple_row) as cur:
        for i in built.items:
            cur.execute(BANK_SQL, _bank_row(i.run, scope=i.scope, at=at, item=i, reason=None))
        for e in built.excluded:
            cur.execute(BANK_SQL, _bank_row(e.run, scope=e.scope, at=at, item=None, reason=e.reason[:120]))
        runs = [i.run.id for i in built.items] + [e.run.id for e in built.excluded]
        cur.execute(BANK_IDS_SQL, {"bank": VERSION, "runs": runs})
        return {int(r): int(i) for r, i in cur.fetchall()}


# -- the run -----------------------------------------------------------------------------------------------------------------

def task_of(a: PlannedAsk, *, run_key: str, variant: str) -> Task:
    """One ask as a task of the LAB's queue: purpose ``other`` and the bank's own prompt version, no match, no agent."""
    run = a.item.run
    return Task(purpose="other", tier=a.tier, request=a.request, prompt_version=VERSION,
                input_hash=ask_hash(variant, run.idem_key, a.repetition), fixture_id=None, deadline_at=None,
                context={"lab": "replay", "bank": VERSION, "variant": variant, "run": run_key, "item": run.id, "idem": run.idem_key,
                         "repetition": a.repetition, "scope": a.item.scope},
                lab=True, agent=None, typical_output=typical_output(run, a.request))


def submit(conn: psycopg.Connection[Any], settings: AiSettings, built: bank.Build, p: Plan, *, confirmed_by_owner: bool,
           ledger: UsageLedger | None = None, client: BatchClient | None = None,
           transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Send the plan as ONE batch of the LAB, all or nothing. Without the owner's confirmation it is the plan itself and
    nothing is written; without the protocol, or with any blocker of the plan, nothing is written either. The bank's rows
    are written (and committed) first; then every ask is recorded in the queue - and if the queue refuses one, nothing
    is sent - then the run's row, and the batch is sent (the queue commits as it sends)."""
    out = p.as_json()
    if not confirmed_by_owner:
        return out | {"submitted": 0, "dry_run": True,
                      "note": "a run spends only with --confirm-owner (and with the protocol registered)"}
    from fbi.research import (
        protocol,  # the plan's registered protocols: a run with spend needs its own
    )

    try:
        stamp = protocol.stamp(PROTOCOL_KEY)
    except LookupError as exc:
        return out | {"submitted": 0, "blockers": [*p.blockers, str(exc)]}
    if p.blockers:
        return out | {"submitted": 0}
    write_bank(conn, built, at=p.at)
    conn.commit()
    queue = BatchQueue(conn, settings, at=p.at, ledger=ledger, client=client, transport=transport)
    admissions = [queue.add(task_of(a, run_key=p.run_key, variant=p.variant)) for a in p.asks]
    if any(not adm.pending for adm in admissions):
        conn.rollback()
        return out | {"submitted": 0, "refused": dict(queue.refused),
                      "blockers": ["the queue refused part of the run (see refused): nothing was sent"]}
    states: dict[str, int] = defaultdict(int)
    for adm in admissions:
        states[adm.status] += 1
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(RUN_SQL, {"key": p.run_key, "bank": VERSION, "variant": p.variant, "protocol": stamp["version"],
                              "fingerprint": stamp["fingerprint"], "at": p.at, "items": len(p.selection), "asks": len(p.asks),
                              "repeats": REPEATS, "estimate": p.cost.prudent, "worst": p.cost.worst, "cap": p.cap,
                              "remaining": Decimal(0) if p.room is None else p.room.remaining,
                              "selection": Jsonb(p.selected_by)})
    report = queue.flush()
    return out | {"submitted": report.sent, "states": dict(states), "failed": report.failed, "error": report.error,
                  "protocol": stamp}


# -- the answers -------------------------------------------------------------------------------------------------------------

def settle(r: Resolved) -> dict[str, Any]:
    """What ``fbi.ai.lab.settle_lab`` keeps of an answer of the bank (``context.result``): the RAW answer, as the shadow's
    tasks of the Batch keep theirs. Nothing is validated in the poll: the collection reads it against the rebuilt slice
    or view, as the shadow's next stage does. Idempotent: the same answer overwrites itself."""
    base: dict[str, Any] = {"replay": 1, "usage_id": r.usage_id, "cost": str(r.cost), "late": r.late, "model": str(r.item["model"])}
    if r.result is None:
        return base | {"ok": False, "error": "invalid_output" if r.error is None else r.error.code}
    return base | {"ok": True, "data": dict(r.result.data), "stop_reason": r.result.extra.get("stop_reason")}


@dataclass(frozen=True, slots=True)
class Reading:
    status: str
    """``ok``, ``abstain`` (a Council that abstained on every candidate) or ``invalid``."""
    output: dict[str, Any] | None
    verdict: str | None
    units: dict[str, str]
    problems: tuple[str, ...] = ()


def read_answer(item: bank.Item, data: object) -> Reading:
    """An answer of a replay read EXACTLY as the shadow reads it: the agent's own ``read`` against the slice (or the
    Council's view) and the names of the pass, derived again. Never raises."""
    ask, inputs = item.ask, item.inputs
    if ask.agent == council.AGENT:
        assert ask.view is not None
        got = council.read(data, view=ask.view, naming=inputs.naming)
        if got.status == "ok" and got.council is not None:
            verdicts = [v.verdict for v in got.council.verdicts]
            output = got.council.model_dump(mode="json")
            status = "abstain" if verdicts and all(v == "ABSTAIN" for v in verdicts) else "ok"
            return Reading(status, output, verdict_string(verdicts) or None, bank.units_of(ask.agent, ask.task_kind, output))
        return Reading("invalid", None, None, {}, tuple(got.problems))
    if ask.agent == player.AGENT:
        position = player.read(data, slice_=inputs.slices["player"], naming=inputs.naming)
        out = position.assessment
        if position.ok and out is not None:
            output = out.model_dump(mode="json")
            return Reading("ok", output, verdict_string(c.stance for c in out.candidates) or None,
                           bank.units_of(ask.agent, ask.task_kind, output))
        return Reading("invalid", None, None, {}, tuple(position.problems))
    if ask.agent == stats.AGENT:
        reading = stats.read(data, slice_=inputs.slices["stats"], naming=inputs.naming)
    else:
        mode = cast(Any, ask.mode)
        reading = match.read(data, mode=mode, slice_=inputs.slices["match"], naming=inputs.naming if mode == "EVALUATION" else None)
    assessment = reading.assessment
    if reading.ok and assessment is not None:
        output = assessment.model_dump(mode="json")
        return Reading("ok", output, verdict_string(c.stance for c in assessment.candidates) or None,
                       bank.units_of(ask.agent, ask.task_kind, output))
    return Reading("invalid", None, None, {}, tuple(reading.problems))


@dataclass(frozen=True, slots=True)
class Held:
    """What the queue holds of the asks of a variant: the newest item of each (stored run, repetition)."""

    newest: dict[tuple[int, int], dict[str, Any]]

    def state(self, key: tuple[int, int]) -> str:
        row = self.newest.get(key)
        return "missing" if row is None else str(row["status"])

    @property
    def open(self) -> list[tuple[int, int]]:
        return [k for k, r in self.newest.items() if r["status"] in OPEN]


def held_items(conn: psycopg.Connection[Any], *, variant: str) -> Held:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ITEMS_SQL, {"version": VERSION, "variant": variant})
        rows = [dict(r) for r in cur.fetchall()]
    newest: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        ctx = row["context"] or {}
        try:
            key = (int(ctx["item"]), int(ctx["repetition"]))
        except (KeyError, TypeError, ValueError):
            continue
        newest[key] = row
    return Held(newest)


COLLECTED_SQL: Final = """
SELECT b.source_run_id, r.repetition FROM ai.replay_results r JOIN ai.replay_bank_items b ON b.id = r.bank_item_id
 WHERE b.bank_version = %(bank)s AND r.variant = %(variant)s
"""


def collect(conn: psycopg.Connection[Any], *, variant: str = SAME, at: datetime) -> dict[str, Any]:
    """Read every answer of the variant that came back and is not in ``ai.replay_results`` yet, and append it there. It
    does not poll the provider: the worker's ``ai_batch_poll`` takes the results every five minutes. The caller commits."""
    held = held_items(conn, variant=variant)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(COLLECTED_SQL, {"bank": VERSION, "variant": variant})
        done = {(int(r), int(k)) for r, k in cur.fetchall()}
    answered = {k: r for k, r in held.newest.items() if r["status"] in ANSWERED and k not in done}
    if not answered:
        return {"answered": 0, "written": 0, "open": len(held.open), "already": len(done)}
    runs = sorted({k[0] for k in answered})
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(BANK_IDS_SQL, {"bank": VERSION, "runs": runs})
        ids = {int(r): int(i) for r, i in cur.fetchall()}
    stored = bank.read_runs_by_id(conn, runs)
    rebuilt = bank.build(conn, runs=stored, changed_at=None)
    items = {i.run.id: i for i in rebuilt.items}
    written = 0
    unreadable: dict[str, str] = {}
    for e in rebuilt.excluded:
        unreadable[str(e.run.id)] = e.reason
    with conn.cursor(row_factory=tuple_row) as cur:
        for (run_id, repetition), row in sorted(answered.items()):
            item, bank_id = items.get(run_id), ids.get(run_id)
            if bank_id is None or item is None:
                # Its input cannot be derived again now (a deploy changed the agent in force, say): the answer is left in its item,
                # uncollected and said, never written as a replay that did not stand - the table is append-only.
                unreadable.setdefault(str(run_id), "stored_run_missing" if item is None else "bank_item_missing")
                continue
            result = (row["context"] or {}).get("result") or {}
            if row["status"] == "invalid" or result.get("ok") is not True:
                got = Reading("invalid", None, None, {}, (str(result.get("error") or row["error"] or "invalid_output")[:64],))
            else:
                got = read_answer(item, result.get("data"))
            cur.execute(RESULT_SQL, {"item": bank_id, "variant": variant, "repetition": repetition, "batch_item": int(row["id"]),
                                     "usage": row["usage_id"], "model": row["model"], "at": at, "status": got.status,
                                     "output": None if got.output is None else Jsonb(got.output), "verdict": got.verdict,
                                     "units": Jsonb(got.units), "problems": [p[:120] for p in got.problems[:12]],
                                     "cost": Decimal(row["cost_usd"] or 0)})
            written += max(cur.rowcount, 0)
    return {"answered": len(answered), "written": written, "open": len(held.open), "already": len(done),
            "not_rebuilt": dict(sorted(unreadable.items()))}


# -- the report ----------------------------------------------------------------------------------------------------------------

Confidence = dict[str, tuple[str | None, str | None, str | None]]
"""The Council's confidence of the three readings of each unit (``<item>:<candidate>``)."""


@dataclass(slots=True)
class _Scope:
    units: list[measure.Unit] = field(default_factory=list)
    stored: int = 0
    stored_invalid: int = 0
    replays: int = 0
    replays_invalid: int = 0
    open: int = 0
    confidence: Confidence = field(default_factory=dict)

    def answers(self) -> measure.Answers:
        return measure.Answers(self.stored, self.stored_invalid, self.replays, self.replays_invalid, self.open)


def scope_units(rows: Sequence[Mapping[str, Any]], stored: Mapping[int, Mapping[str, Any]], held: Held) -> dict[str, _Scope]:
    """Per scope: the units of every stored run that was asked, how its asks came back and (the Council) the confidence of
    its three readings. A repetition that has not come back is a missing reading; one still open is counted as open."""
    results: dict[int, dict[int, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        results[int(row["source_run_id"])][int(row["repetition"])] = row
    out: dict[str, _Scope] = defaultdict(_Scope)
    for run_id in sorted({k[0] for k in held.newest} | set(results)):
        s = stored.get(run_id)
        if s is None:
            continue
        scope = out[str(s["scope"])]
        scope.stored += 1
        scope.stored_invalid += int(s["stored_status"] == "invalid")
        words: list[dict[str, str] | None] = []
        conf: list[dict[str, str]] = []
        for k in range(1, REPEATS + 1):
            got = results.get(run_id, {}).get(k)
            if held.state((run_id, k)) in OPEN:
                scope.open += 1
            stood = got is not None and got["status"] != "invalid"
            if got is not None:
                scope.replays += 1
                scope.replays_invalid += int(not stood)
            words.append(dict(got["units"] or {}) if got is not None and stood else None)
            conf.append(bank.confidence_of(council.AGENT, got["output"]) if got is not None and stood else {})
        stored_words = dict(s["stored_units"] or {}) if s["stored_status"] != "invalid" else None
        scope.units += measure.units_of(run_id, int(s["fixture_id"]), stored_words, words[0], words[1])
        stored_conf = dict(s["stored_confidence"] or {})
        for key in sorted(stored_conf):
            scope.confidence[f"{run_id}:{key}"] = (stored_conf.get(key), conf[0].get(key), conf[1].get(key))
    return dict(out)


def report(conn: psycopg.Connection[Any], *, at: datetime, variant: str = SAME, record: bool = True) -> dict[str, Any]:
    """The verdict of every scope that was asked. With ``record`` it first collects what came back
    (``ai.replay_results``) and then, with the protocol registered, appends each verdict of a scope with nothing on its way
    to ``ai.replay_assessments`` when its evidence is not the newest row's; without it, it writes nothing and judges what
    was already collected. The caller commits."""
    collected = collect(conn, variant=variant, at=at) if record else {"skipped": "--no-record: nothing collected"}
    held = held_items(conn, variant=variant)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RESULTS_SQL, {"bank": VERSION, "variant": variant})
        rows = [dict(r) for r in cur.fetchall()]
        runs = sorted({k[0] for k in held.newest} | {int(r["source_run_id"]) for r in rows})
        cur.execute(STORED_SQL, {"bank": VERSION, "runs": runs})
        stored = {int(r["source_run_id"]): dict(r) for r in cur.fetchall()}
    if not held.newest and not rows:
        return {"state": "nothing_submitted", "variant": variant, "collected": collected}
    from fbi.research import protocol

    try:
        stamp: dict[str, Any] | None = protocol.stamp(PROTOCOL_KEY)
    except LookupError:
        stamp = None
    out: dict[str, Any] = {"variant": variant, "bank": VERSION, "collected": collected, "protocol": stamp, "scopes": {},
                           "cost_usd": _money(sum((Decimal(r["cost_usd"] or 0) for r in rows), Decimal(0)))}
    for name, scope in sorted(scope_units(rows, stored, held).items()):
        answers = scope.answers()
        verdict = measure.assess(scope.units, answers, confidence=scope.confidence or None)
        entry: dict[str, Any] = dict(verdict)
        if record and stamp is not None and not answers.open:
            evidence = {"bank": VERSION, "variant": variant, "scope": name, "assessment": verdict,
                        "letters": measure.letters(scope.units), "protocol": stamp}
            entry["assessment_id"] = record_assessment(conn, at=at, variant=variant, scope=name, stamp=stamp,
                                                       verdict=str(verdict["verdict"]), evidence=evidence)
        out["scopes"][name] = entry
    out["state"] = "waiting" if held.open else "ended"
    out["comparable"] = sorted(s for s, e in out["scopes"].items() if e["verdict"] == measure.PASS)
    return out


def record_assessment(conn: psycopg.Connection[Any], *, at: datetime, variant: str, scope: str, stamp: Mapping[str, Any], verdict: str,
                      evidence: Mapping[str, Any]) -> int | None:
    """Append the verdict of a scope unless the newest row of the same scope says exactly this. Returns its id, or None."""
    digest = measure.evidence_hash(evidence)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NEWEST_ASSESSMENT_SQL, {"bank": VERSION, "variant": variant, "scope": scope, "protocol": stamp["version"]})
        newest = cur.fetchone()
        if newest is not None and newest[0] == digest:
            return None
        cur.execute(ASSESSMENT_SQL, {"at": at, "bank": VERSION, "variant": variant, "scope": scope, "protocol": stamp["version"],
                                     "fingerprint": stamp["fingerprint"], "method": measure.METHOD, "verdict": verdict,
                                     "evidence": Jsonb(dict(evidence)), "hash": digest})
        row = cur.fetchone()
    return None if row is None else int(row[0])


def window(at: datetime, *, days: int) -> tuple[datetime, datetime]:
    """The runs a build reads by default: the ``days`` complete Bogotá days before today (fixed for the whole day, so
    the same plan the whole day)."""
    from fbi.ai.calendar import day_start

    today = local_day(at)
    return day_start(today - timedelta(days=days)), day_start(today)


__all__ = ["DEFAULT_LIMIT_PER_SCOPE", "DEFAULT_MAX_USD", "HARD_MAX_USD", "HEADROOM_FACTOR", "Cost", "Plan", "PlannedAsk", "Reading",
           "ask_hash", "collect", "cost_of", "plan", "read_answer", "report", "settle", "submit", "task_of", "tier_of", "window",
           "write_bank"]
