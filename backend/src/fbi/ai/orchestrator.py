"""The Orchestrator of phase 3 (Plan Maestro IA, sections 17, 18, 22-24 and 34; architecture, sections 8, 12, 13, 16 and 17): it runs the Match Agent, the
contradiction detector and the Council in SHADOW over a sample of the matches, in the LAB workspace, and writes rows nobody reads for a decision.

    ``run(conn, settings, *, at, limit=20, max_seconds=240.0, provider=None, transport=None, ledger=None, slots=None, circuit=None) -> Report``

The job of the worker calls it with its own connection (autocommit off) and commits and closes the cycle itself. ``run`` NEVER raises: whatever goes
wrong with one match is rolled back, counted in ``failed_open`` and the loop goes on; the quantitative pipeline never notices (fail open).

What a run does, in this order:

1. WORK. The passes of the AI layer that stored a packet before the kick-off and finished ``ok`` or ``partial``, whose kick-off is still ahead, that
   production reviewed with at least one selection and that have no shadow yet (``orchestrator_store.pending``). ``arms.assign`` puts every match in
   its arms ONCE (and the run COMMITS before it spends anything: the assignment is the experiment's memory); only the sampled matches run, and only
   the engines ``arms.runnable`` says.
2. CANDIDATES. Exactly the selections production reviewed in that pass (the ``rules`` reviews of that packet), named ``c1``.. by
   ``agents.common.name_candidates``; the ones left out are said and never reviewed. The three scores and the fair and minimum odds are the rules
   reviewer's: no model writes a number.
3. CALLS, in this order, each through ``usage.call_json(..., lab=True)``: the Match Agent in CONTEXT (Haiku, low) and in EVALUATION (Haiku, medium) once
   for the match; ``contra.detect`` over the whole package; the Council of each arm (``ma-v1`` Sonnet and ``ma-v1-h`` Haiku read the same view with the
   assessments, ``cs-v1`` reads a view with none); and Opus, only for the candidates a rule E1-E7 of ``router-v1`` fires on, at most 3 calls a Bogotá day
   shared by the two arms of the multi-agent, replacing the first-round verdicts of the candidates it was asked about and nothing else. A model never asks
   for Opus (``cd-v1`` has no field for it); the research a model asks for is IGNORED in the shadow (recorded as ``research_ask_ignored``): the shadow
   agents never search, never call MCP and never write ``ai.evidence`` or ``ai.fixture_passes``.
4. GUARDS. ``runtime.Slots`` (one per process), ``runtime.Circuit`` (one per process, never changing the model or the request), ``run_with_retries``
   for transport failures only, the deadline of T-15 (``runtime.verdict`` before the pass, ``time_left`` bounding each call's timeout), the budget of the
   LAB (``budget_v3.lab_day``: the estimate of a match must fit in what is left of the day, else the run STOPS and writes nothing for that match) and
   ``runtime.arm_pause`` (an arm whose model's circuit is open, or whose day is over 3 % invalid, does not run for the pass).
5. WRITES, one transaction per match: the tasks and runs (``ai.agent_tasks``, ``ai.agent_runs``), ONE shadow row of ``ai.match_runs`` and ONE
   ``ai.pick_reviews`` row (``mode = 'shadow'``) per candidate and engine. The calls themselves are in ``ai.usage`` already, written by ``call_json``
   on its own connection: they survive a rollback of the match's rows.

THE REPORT. ``Report.to_json()`` has counts and codes only.

    skipped             ``"off"`` when ``settings.orchestrate`` is false (nothing else was read); otherwise None
    considered          the passes selected (before the assignment)
    sampled             of those, the passes of matches the assignment put in the sample
    ran                 the passes whose shadow was written after the arms were asked (an arm may have been paused, skipped or failed: its rows say so)
    not_run             the passes written as NOT RUN because no model could be asked at all (a blocked package, no candidate to name, a slice over its cap,
                        every arm paused)
    failed_open         the passes that raised: rolled back, nothing written for them, and not tried again by this process
    calls               the calls made to the provider (a retry is a call), the ones that failed included
    cost_usd            what those calls cost, as ``call_json`` priced them (Decimal)
    invalid             answers that did not validate (the contract refused them, a reference did not exist, or the provider said so)
    budget_stop         why the run stopped for money, or None: ``no_envelope``, ``api_limit``, ``yields_to_production``, ``allocation_spent``,
                        ``insufficient`` (the estimate does not fit in what is left of the day) or ``exhausted`` (a call came back ``over_budget``)
    circuit_open        the models whose circuit refused a call or paused an arm in this run
    paused              ``<engine>:<reason>`` of every arm that did not run for a pass (reasons of ``runtime.PAUSE_REASONS``)
    too_late            the passes skipped because they could not end before T-15
    escalated           the candidates sent to Opus in a call that was made
    escalation_skipped  the candidates a rule fired on whose Opus call was not made (the daily cap, the money): the first-round verdict stands
    reused              the tasks whose answer was already stored for the same idempotency key (nothing was paid again)
    queued              the tasks sent to the Message Batches API in this run (the Batch calendar)
    waiting             the passes of the Batch calendar that wait for an item still open at the end of this run
    settled             the tasks of the Batch calendar whose answer was read when their pass was written
    abandoned           of those, the tasks given up for time (``batch_too_late``)

Idempotent: the second run over the same passes finds a shadow row for each and selects nothing.

THE BATCH CALENDAR (plan, sections 16-18). Every model call goes through ``_Runner.ask``, the one place where a task becomes a call - or an item of the
Message Batches API. A pass whose ``first`` or ``pre`` kick-off is far enough (``BatchQueue.routes``: pass, lead time, the ``batch`` gate of the models)
is decided ONCE to travel in the LAB's Batch, at half the price, and then it never asks in real time: its tasks are stored ``queued`` (``route.mode =
'batch'``), the pass is a state machine over several runs of the job, and the job's next runs pick it up again (``orchestrator_store.pending``) as
soon as no item of it is open:

    stage 1   the Match Agent's context and evaluation (Haiku) and the Council that reads no assessment (``cs-v1``), queued together after ONE
              check of the whole pass at half price against the LAB's day (nothing is queued if it does not fit);
    stage 2   the Council of each arm that reads the assessments (``ma-v1``, ``ma-v1-h``), built from the stored answers of stage 1;
    stage 3   Opus, only for the candidates a rule E1-E7 fires on (the hours to the kick-off are frozen in the first Opus task, so that a later run
              asks the same question).

The poll keeps the RAW answer of each item (``lab.settle_lab``, ``context.lab = 'shadow'``); the stage that reads it validates it against the view it
rebuilds from the stored package (the same ``match.read`` and ``council.read`` as the real-time path), and the pass is WRITTEN when its last stage is
settled, by the same writer: the tasks end ``queued > running > done`` with their runs, one shadow row of ``ai.match_runs`` and the reviews, the same
rows as a pass asked in real time. A batch item that errors, is cancelled, expires or is abandoned leaves its arm ``fallback`` with the code
(``batch_errored``...), unpaid, never retried; a stage that cannot be queued (``STAGE_MIN_LEAD``) or an item still open at ``ABANDON_BEFORE`` (100
minutes) of the kick-off ends the pass ``batch_too_late`` (recorded, ``final.too_late``), and a pass never goes back to real time once it is a
pass of the Batch.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast

import psycopg

from fbi.ai import arms, contra, gates, router, runtime, stats_factors, usage
from fbi.ai import package as mcp_package
from fbi.ai import prompts as prompt_labels
from fbi.ai.agents import council, match, stats
from fbi.ai.agents.common import Assessed, Contradiction, Naming, name_candidates, name_with_counts
from fbi.ai.agents.registry import REGISTRY
from fbi.ai.batch import BatchClient, BatchQueue, Task, estimate_cost
from fbi.ai.config import AiSettings, Tier
from fbi.ai.contracts.base import GOALS_RESULT, parse_ref
from fbi.ai.contracts.mcp import SLICE_NAMES
from fbi.ai.idempotency import TaskIdentity
from fbi.ai.orchestrator_store import (
    ABANDON_BEFORE,
    STATE_VERSION,
    Existing,
    Reviewed,
    ReviewRow,
    Scores,
    StateRecord,
    StoredTask,
    TaskRecord,
    Tokens,
    Work,
    batch_task,
    batch_tasks,
    close_tasks,
    distinct,
    end_task,
    existing,
    lapse,
    link_batch,
    open_batch_of,
    opus_today,
    pending,
    queue_task,
    reviewed,
    spent_today,
    tokens_of,
    write_review,
    write_state,
    write_task,
)
from fbi.ai.orchestrator_store import (
    arm_today as store_arm_today,
)
from fbi.ai.packet import Packet, content_hash, load_packet
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.review import fair_and_minimum
from fbi.core.version import model_code_version

log = logging.getLogger("fbi.ai.orchestrator")

VERSION: Final = "orch-v1"
"""The orchestrator's own name in the rows it writes (``output.version``). A change to how a verdict is stored is a new one, never an edit."""

CONFIDENCE: Final[dict[str, Decimal]] = {
    "LOW": Decimal("0.35"),
    "MEDIUM": Decimal("0.60"),
    "HIGH": Decimal("0.85"),
}
"""``cd-v1`` speaks of how sure the Council is in three words and ``ai.pick_reviews.confidence`` is a number from 0 to 1: the fixed mapping. A review
that was not answered (abstained, not run, invalid) has 0."""
ENGINE_LEVEL: Final[dict[str, str]] = {
    arms.MULTIAGENT: "complex",
    arms.MULTIAGENT_HAIKU: "simple",
    arms.COUNCIL_SOLO: "complex",
}
"""The level of the router that judges for each engine: Sonnet, Haiku (the challenger arm: same prompt, schema and effort) and Sonnet."""
WITH_MATCH: Final = frozenset({arms.MULTIAGENT, arms.MULTIAGENT_HAIKU})
"""The engines that read the Match Agent's assessments."""
ENGINE_VERSION: Final[dict[str, str]] = {
    arms.MULTIAGENT: f"{arms.MULTIAGENT}+{match.VERSION}+{council.VERSION}+{contra.VERSION}+{router.VERSION}",
    arms.MULTIAGENT_HAIKU: f"{arms.MULTIAGENT_HAIKU}+{match.VERSION}+{council.VERSION}+{contra.VERSION}+{router.VERSION}",
    arms.COUNCIL_SOLO: f"{arms.COUNCIL_SOLO}+{council.VERSION}+{router.VERSION}",
}
"""``ai.pick_reviews.engine_version`` of each engine: the versions of what it is made of."""
STATS_PART: Final = f"+{stats.VERSION}"
"""What the engines that read the assessments add to their ``engine_version`` when the Statistics Agent is on (phase 4): a shadow row says whether the
Council read the assessments of the Statistics Agent or not. With ``stats`` off the versions are exactly those above."""


def engine_version(engine: str, *, with_stats: bool) -> str:
    """``ENGINE_VERSION`` of an engine, with the Statistics Agent's version after the Match Agent's when the engine reads its assessments."""
    base = ENGINE_VERSION[engine]
    if with_stats and engine in WITH_MATCH:
        return base.replace(f"+{match.VERSION}", f"+{match.VERSION}{STATS_PART}", 1)
    return base


EXPECTED: Final = timedelta(minutes=3)
"""How long a shadow pass is expected to take, for ``runtime.verdict``: it must END strictly before T-15."""
MIN_CALL_S: Final = 10.0
"""A call is not made with less than this left before T-15 (its timeout is bounded by the time left, minus five seconds)."""
SLOT_WAIT_S: Final = 20.0
"""How long a call waits for a slot of its level before the task is skipped (``no_slot``)."""
SYNC_FACTOR: Final = Decimal(2)
"""``batch.estimate_cost`` prices a request at the Batch's half price; this phase asks in real time, at the full price."""
ESTIMATE_MARGIN: Final = Decimal("1.10")
"""The estimate of a match is made with the Council's view WITHOUT the assessments (they do not exist yet): a tenth more covers them."""
PRIORITY: Final[dict[str, int]] = {"final": 100, "pre": 200, "first": 300, "request": 400}
"""``ai.agent_tasks.priority``: the final pass before the pre before the first; the task kind adds its own offset (``TASK_OFFSET``)."""
TASK_OFFSET: Final[dict[str, int]] = {"context": 0, "evaluation": 1, "council": 2, "escalation": 3}
BATCH_DEADLINE: Final = timedelta(minutes=60)
"""``ai.agent_tasks.deadline_at`` and ``batch.Task.deadline_at`` of a task of the Batch calendar: kick-off minus this (``batch.DEADLINE_MARGIN``)."""
STAGE_MIN_LEAD: Final = ABANDON_BEFORE + BATCH_DEADLINE
"""A stage of the Batch calendar is queued only while the match is at least this far (the ``final`` pass starts at ``ABANDON_BEFORE``, and the batch
needs the hour its deadline leaves). A later stage that cannot be queued ends the pass ``batch_too_late``."""
BATCH_CODES: Final[dict[str, tuple[str, str]]] = {
    "errored": ("skipped", "failed"),
    "canceled": ("skipped", "skipped"),
    "expired": ("expired", "expired"),
    "abandoned": ("skipped", "failed"),
    "missing": ("skipped", "failed"),
    "too_late": ("expired", "expired"),
}
"""(status of the run, state of the task) of a batch item that gave no answer, by how it ended; the code of the arm is ``batch_<key>``. Nothing was
paid, and nothing is asked again in real time."""
FAILED_MEMORY: Final = 2000
"""A pass that raised is not tried again by this process; the memory is cut when it gets this big."""
BUDGET_STOPS: Final = (
    "no_envelope",
    "api_limit",
    "yields_to_production",
    "allocation_spent",
    "insufficient",
    "exhausted",
)

# what a pass leaves behind per engine
STATUS_OK: Final = "ok"
STATUS_FALLBACK: Final = "fallback"
STATUS_INVALID: Final = "invalid_output"
STATUS_FAILED: Final = "failed"
STATUS_OVER_BUDGET: Final = "over_budget"

_failed: set[tuple[int, str, int]] = set()
_slots: runtime.Slots | None = None
_circuit: runtime.Circuit | None = None
_guard = threading.Lock()


def process_slots() -> runtime.Slots:
    """THE slots of this process (one per level): created on first use. A run takes them as a parameter only in tests."""
    global _slots
    with _guard:
        if _slots is None:
            _slots = runtime.Slots()
        return _slots


def process_circuit() -> runtime.Circuit:
    """THE circuit of this process: one per 15-minute tick would forget that a model was down."""
    global _circuit
    with _guard:
        if _circuit is None:
            _circuit = runtime.Circuit()
        return _circuit


# -- the report ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """What one run did, in counts and codes (see the module's docstring for the exact meaning of each field)."""

    skipped: str | None = None
    considered: int = 0
    sampled: int = 0
    ran: int = 0
    not_run: int = 0
    failed_open: int = 0
    calls: int = 0
    cost_usd: Decimal = Decimal(0)
    invalid: int = 0
    budget_stop: str | None = None
    circuit_open: list[str] = field(default_factory=list)
    paused: list[str] = field(default_factory=list)
    too_late: int = 0
    escalated: int = 0
    escalation_skipped: int = 0
    reused: int = 0
    queued: int = 0
    waiting: int = 0
    settled: int = 0
    abandoned: int = 0

    def to_json(self) -> dict[str, Any]:
        """Counts and codes only: no prompt, no evidence text, no key, no address."""
        return {
            "skipped": self.skipped,
            "considered": self.considered,
            "sampled": self.sampled,
            "ran": self.ran,
            "not_run": self.not_run,
            "failed_open": self.failed_open,
            "calls": self.calls,
            "cost_usd": str(self.cost_usd),
            "invalid": self.invalid,
            "budget_stop": self.budget_stop,
            "circuit_open": list(self.circuit_open),
            "paused": list(self.paused),
            "too_late": self.too_late,
            "escalated": self.escalated,
            "escalation_skipped": self.escalation_skipped,
            "reused": self.reused,
            "queued": self.queued,
            "waiting": self.waiting,
            "settled": self.settled,
            "abandoned": self.abandoned,
        }


@dataclass(slots=True)
class _Tally:
    considered: int = 0
    sampled: int = 0
    ran: int = 0
    not_run: int = 0
    failed_open: int = 0
    calls: int = 0
    cost: Decimal = Decimal(0)
    invalid: int = 0
    budget_stop: str | None = None
    circuit_open: set[str] = field(default_factory=set)
    paused: list[str] = field(default_factory=list)
    too_late: int = 0
    escalated: int = 0
    escalation_skipped: int = 0
    reused: int = 0
    queued: int = 0
    waiting: int = 0
    settled: int = 0
    abandoned: int = 0

    def report(self) -> Report:
        return Report(
            considered=self.considered,
            sampled=self.sampled,
            ran=self.ran,
            not_run=self.not_run,
            failed_open=self.failed_open,
            calls=self.calls,
            cost_usd=self.cost,
            invalid=self.invalid,
            budget_stop=self.budget_stop,
            circuit_open=sorted(self.circuit_open),
            paused=list(self.paused),
            too_late=self.too_late,
            escalated=self.escalated,
            escalation_skipped=self.escalation_skipped,
            reused=self.reused,
            queued=self.queued,
            waiting=self.waiting,
            settled=self.settled,
            abandoned=self.abandoned,
        )


# -- pure helpers --------------------------------------------------------------------------------------------------------------------


def confidence_value(level: str | None) -> Decimal:
    """The number a level of confidence is stored as (``CONFIDENCE``); anything else - no verdict, an unknown word - is 0."""
    return CONFIDENCE.get(level or "", Decimal(0))


def outcome_status(error: str | None) -> tuple[str, str]:
    """(status of the run, state of the task) of a call that did NOT produce a usable answer, by the code ``call_json`` gave. A call that was never
    made, or never served, is unpaid; one the provider answered with something that cannot be read is paid and ``invalid``."""
    if error == "timeout":
        return "timeout", "failed"
    if error == "invalid_output":
        return "invalid", "done"
    if error == "over_budget":
        return "budget_skip", "skipped"
    if error == "not_configured":
        return "skipped", "skipped"
    return "skipped", "failed"


VERDICT_ORDER: Final = ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN", "SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL")
"""The words of the Council's verdicts and of the Match Agent's stances, in the order a summary lists them."""


def verdict_string(verdicts: Iterable[str]) -> str:
    """``APPROVE:2,REJECT:1``: the verdicts (or stances) of an answer by count, in the order of the contracts, at most 64 characters. An answer
    with none is the empty string."""
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    order = [*VERDICT_ORDER, *sorted(k for k in counts if k not in VERDICT_ORDER)]
    return ",".join(f"{k}:{counts[k]}" for k in order if k in counts)[:64]


def split_cost(total: Decimal, parts: int) -> list[Decimal]:
    """``total`` in ``parts`` equal amounts of six decimals that add up to it exactly (the remainder goes to the first)."""
    if parts <= 0:
        return []
    each = (total / parts).quantize(Decimal("0.000001"), rounding="ROUND_DOWN")
    out = [each] * parts
    out[0] += total.quantize(Decimal("0.000001")) - each * parts
    return out


def settle_costs(exact: Sequence[Decimal]) -> list[Decimal]:
    """Round the engines' exact costs to six decimals so that they add up to the rounded whole, never a millionth off.

    Rounding each engine on its own can lose or invent a millionth (three shares of 0.0000005 round to 0 each, yet their sum to 0.000002).
    Rounding the running total and giving each engine the step between two running totals cannot.
    """
    out: list[Decimal] = []
    running, paid = Decimal(0), Decimal(0)
    for cost in exact:
        running += cost
        settled = running.quantize(Decimal("0.000001"))
        out.append(settled - paid)
        paid = settled
    return out


def budget_stop_reason(
    can_spend: bool, remaining: Decimal, reason: str, estimate: Decimal
) -> str | None:
    """Why the run must stop for money before a match, or None. The LAB runs a day whole or not at all (``budget_v3.lab_day``): when it may not
    spend, its own reason (``no_envelope``, ``api_limit``, ``yields_to_production``, ``allocation_spent``); when it may but the estimate of the match
    does not fit in what is left, ``insufficient``."""
    if not can_spend:
        return reason if reason in BUDGET_STOPS and reason != "insufficient" else "insufficient"
    if estimate > remaining:
        return "insufficient"
    return None


def hours_to(kickoff: datetime, now: datetime) -> Decimal:
    """The hours from ``now`` to the kick-off, two decimals (negative once it has started)."""
    return (Decimal((kickoff - now).total_seconds()) / Decimal(3600)).quantize(Decimal("0.01"))


def priority_of(pass_kind: str, task_kind: str) -> int:
    return PRIORITY.get(pass_kind, 500) + TASK_OFFSET.get(task_kind, 9)


def refs_in(node: Any) -> tuple[list[int], list[str]]:
    """The evidence ids (``E:<id>``) and the paths (``P:<path>``) a stored output cites, once each, in order. Only the lists named ``refs`` count."""
    evidence: list[int] = []
    paths: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key == "refs" and isinstance(inner, list):
                    for text in inner:
                        parsed = parse_ref(text) if isinstance(text, str) else None
                        if parsed is not None and parsed.kind == "E":
                            evidence.append(int(parsed.value))
                        elif parsed is not None and parsed.kind == "P":
                            paths.append(f"P:{parsed.value}")
                else:
                    walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(node)
    return list(dict.fromkeys(evidence)), list(dict.fromkeys(paths))


def review_hash(*parts: Any) -> str:
    """The ``input_hash`` of a shadow review: what the verdict stands on (the engine, the view or package, the model, the escalation)."""
    return content_hash([VERSION, *parts])


# -- the room the LAB has --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Room:
    """What the LAB may spend (``budget_v3.lab_day``, which already nets the open Batch reservations of the day)."""

    can_spend: bool
    remaining: Decimal
    allocation: Decimal
    reason: str


def room_of(conn: psycopg.Connection[Any], settings: AiSettings, at: datetime) -> Room:
    """The LAB's room now: budget v3's ``lab_day`` or, with the rollback switched on, the LAB's monthly envelope alone."""
    if gates.enabled(conn, settings, "budget_v3"):
        from fbi.ai import (
            budget_v3,  # here, not above: budget_v3 builds on usage, which this module also uses
        )

        day = budget_v3.lab_day(conn, at=at, settings=settings)
        return Room(day.can_spend, day.remaining, day.allocation, day.reason)
    budget = settings.lab_monthly_budget
    left = max(Decimal(0), budget - usage.lab_spent_month(conn, at))
    reason = "no_envelope" if budget <= 0 else "allocation_spent" if left <= 0 else "ok"
    return Room(budget > 0 and left > 0, left, budget, reason)


# -- what a call leaves ----------------------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Asked:
    """One task of a pass: what was asked, what came of it, and what is to be stored. Built by ``_Runner._ask``; the reader of the answer
    completes it (``status``, ``output``...)."""

    identity: TaskIdentity
    task_kind: str
    est: Decimal
    decision: router.Decision
    started: datetime
    finished: datetime
    parent_key: str | None = None
    state: str = "skipped"
    status: str = "skipped"
    error: str | None = None
    skip: str | None = None
    """Why no call was made (a code), or None."""
    reused: bool = False
    shared: bool = False
    data: dict[str, Any] | None = None
    model: str | None = None
    """The model that answered."""
    calls: int = 0
    stopped_by: str | None = None
    cost: Decimal = Decimal(0)
    usage_ids: list[int] = field(default_factory=list)
    provider: str | None = None
    output: dict[str, Any] | None = None
    verdict: str | None = None
    evidence_ids: tuple[int, ...] = ()
    data_refs: tuple[str, ...] = ()
    pending: bool = False
    """The task waits in the Message Batches API: there is no answer to read yet (the pass waits)."""
    batch_task: int | None = None
    """``ai.agent_tasks.id`` of the task when it travels in the Batch (it is stored ``queued``: ``end_task`` closes it)."""
    batch_custom: str | None = None
    batch_id: int | None = None
    queued_here: bool = False
    """The task was queued by THIS run (not found stored)."""

    @property
    def key(self) -> str:
        return self.identity.key

    @property
    def answered(self) -> bool:
        """A model's answer is here to be read."""
        return self.data is not None and self.error is None


@dataclass(slots=True)
class Verdict:
    """The verdict that stands for a candidate in an engine, and where it came from."""

    verdict: str
    confidence: str
    drivers: list[str]
    risks: list[str]
    refs: list[str]
    model: str
    escalation: str | None = None
    replaced: bool = False
    changed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Arm:
    """One engine of a pass: its Council, what it read, and what stands."""

    engine: str
    level: str
    view: council.CouncilView | None = None
    asked: Asked | None = None
    reading: council.Reading | None = None
    status: str = STATUS_FALLBACK
    reason: str | None = None
    finals: dict[str, Verdict] = field(default_factory=dict)
    escalated: dict[str, str] = field(default_factory=dict)
    skipped_escalation: dict[str, str] = field(default_factory=dict)
    opus: Asked | None = None
    opus_reading: council.Reading | None = None
    """What Opus answered for the candidates it was asked about, read against the arm's view."""
    users: list[Asked] = field(default_factory=list)
    """Every task this engine stands on (shared ones included), for the cost."""


@dataclass(slots=True)
class BatchRun:
    """What a run knows of a pass of the Batch calendar: the queue that takes its new tasks, the tasks already stored (by idempotency key), what the
    first run decided (``active`` and ``paused`` arms, the frozen hours to the kick-off) and what this run queued."""

    queue: BatchQueue
    stored: dict[str, StoredTask] = field(default_factory=dict)
    active: tuple[str, ...] = ()
    paused: dict[str, list[str]] = field(default_factory=dict)
    hours: Decimal | None = None
    queued_now: int = 0


@dataclass(slots=True)
class _Pass:
    """The state of one pass while it is being shadowed."""

    work: Work
    engines: tuple[str, ...]
    package: mcp_package.Package
    slice_: mcp_package.Slice
    candidates: Reviewed
    naming: Naming
    packet: Packet
    started: datetime
    asked: dict[str, Asked] = field(default_factory=dict)
    assessed: list[Assessed] = field(default_factory=list)
    stances: dict[str, dict[str, str]] = field(default_factory=dict)
    ignored_asks: list[str] = field(default_factory=list)
    arms: list[Arm] = field(default_factory=list)
    match_users: list[Asked] = field(default_factory=list)
    tiers_ok: dict[str, bool] = field(default_factory=dict)
    batch: BatchRun | None = None
    too_late: bool = False
    slices: dict[str, mcp_package.Slice] = field(default_factory=dict)
    """Every slice of the package, by name: ``ai.match_runs.slices`` keeps the measures of all of them, as the audit ``slice_known`` expects."""
    stats_on: bool = False
    """The Statistics Agent is on for this pass (phase 4): the candidates are named with the counts, and the arms that read assessments are given its own."""
    stats_slice: mcp_package.Slice | None = None
    """The ``stats`` slice of the package, when ``stats_on``."""
    stats_note: str | None = None
    """Why the Statistics Agent was not asked (a code), when it was on and nothing was asked of it."""

    @property
    def at(self) -> datetime:
        """The moment of the PASS (the package's): what every request says the time is, so that the same pass asks the same question."""
        return self.slice_.known_at


# -- the run ---------------------------------------------------------------------------------------------------------------------------


class _Runner:
    """One run of the orchestrator. Not reusable."""

    def __init__(
        self,
        conn: psycopg.Connection[Any],
        settings: AiSettings,
        *,
        at: datetime,
        limit: int,
        max_seconds: float,
        provider: LlmProvider | None,
        transport: Any,
        ledger: usage.UsageLedger | None,
        slots: runtime.Slots | None,
        circuit: runtime.Circuit | None,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
        batch_client: BatchClient | None = None,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.at = at
        self.limit = limit
        self.max_seconds = max_seconds
        self.provider = provider
        self.transport = transport
        self.ledger = ledger
        self.slots = slots or process_slots()
        self.circuit = circuit or process_circuit()
        self.monotonic = monotonic
        self.sleep = sleep
        self.t0 = monotonic()
        self.tally = _Tally()
        self.stopped = False
        self.exhausted = False
        self.opus_base: tuple[int, Decimal] | None = None
        self.opus_made = 0
        self.opus_cost = Decimal(0)
        self.batch_client = batch_client
        self._queue: BatchQueue | None = None

    # -- time and money --------------------------------------------------------------------------------------------------------------

    def clock(self) -> datetime:
        """The moment now: the cycle's, plus the time the run has really taken (so that a deterministic clock moves a deterministic amount)."""
        return self.at + timedelta(seconds=self.monotonic() - self.t0)

    def room(self) -> Room:
        return room_of(self.conn, self.settings, self.clock())

    def estimate(self, model: str, request: JsonRequest, *, batch: bool = False) -> Decimal:
        """What a request will cost in real time: ``batch.estimate_cost`` (half price, the typical output being half of ``max_tokens``) doubled; in
        the Batch, at half price as it is."""
        cost = estimate_cost(model, request, typical_output=None, at=self.clock())
        return cost if batch else cost * SYNC_FACTOR

    def queue(self) -> BatchQueue:
        """THE queue of the run: its moment is the run's (``add`` and ``flush`` of the same batch must agree on it), it holds what ``add`` recorded
        until ``flush`` sends it, and the pass that added flushes in the same run (a batch left ``submitting`` is what ``abandon_unsent`` eats)."""
        if self._queue is None:
            self._queue = BatchQueue(
                self.conn,
                self.settings,
                at=self.at,
                ledger=self.ledger,
                client=self.batch_client,
                transport=self.transport,
            )
        return self._queue

    def day(self, room: Room) -> router.Day:
        """The day as the router reads it, for the shadow's caps: what the shadow spent today (from its own runs) and the Opus calls made."""
        if self.opus_base is None:
            self.opus_base = opus_today(self.conn, self.clock())
        by_model = spent_today(self.conn, self.clock())
        simple = sum(
            (c for m, c in by_model.items() if router.LEVEL_OF_MODEL.get(m) == "simple"), Decimal(0)
        )
        council_spent = sum(
            (c for m, c in by_model.items() if router.LEVEL_OF_MODEL.get(m) == "complex"),
            Decimal(0),
        )
        return router.Day(
            allocation_usd=room.allocation,
            scope="shadow",
            spent_simple_usd=simple,
            spent_council_usd=council_spent,
            spent_opus_usd=self.opus_base[1] + self.opus_cost,
            opus_calls=self.opus_base[0] + self.opus_made,
        )

    # -- the loop --------------------------------------------------------------------------------------------------------------------

    def close_lapsed(self) -> None:
        """The queued tasks of a match that has started end (``kickoff_passed``): nothing stays queued for ever."""
        if lapse(self.conn, at=self.at):
            self.conn.commit()

    def register_relations(self) -> None:
        """Phase 4: the relations the Statistics Agent is told nobody has tested are recorded in ``intel.context_factors`` as DESCRIPTIVE (idempotent: the
        registry is append-only and a relation already decided is left alone). Fail open: a registry that cannot be written costs the shadow nothing."""
        try:
            stats_factors.register_relations(self.conn, at=self.at)
            self.conn.commit()
        except Exception as exc:  # the registry is a record of what is NOT a reason: not having it written changes no answer, so it never stops a pass
            log.warning("orchestrator.relations_failed", extra={"code": type(exc).__name__})
            try:
                if not self.conn.closed:
                    self.conn.rollback()
            except Exception:  # a connection that cannot roll back is no connection to go on with: the next step of the run finds it out
                pass

    def go(self) -> None:
        if stats.AGENT in self.settings.agents:
            self.register_relations()
        works = pending(self.conn, at=self.at, limit=self.limit)
        self.tally.considered = len(works)
        if not works:
            return
        ids = list(dict.fromkeys(w.fixture_id for w in works))
        assigned = arms.assign(self.conn, ids, at=self.at, share=self.settings.shadow_sample)
        self.conn.commit()  # the assignment is the experiment's memory: it survives whatever happens to the passes
        self.tally.sampled = sum(
            1 for w in works if assigned.get(w.fixture_id, arms.OUTSIDE).sampled
        )
        for w in works:
            if self.stopped:
                break
            if self.monotonic() - self.t0 >= self.max_seconds:
                log.info("orchestrator.time_up", extra={"code": "max_seconds"})
                break
            assignment = assigned.get(w.fixture_id, arms.OUTSIDE)
            if not assignment.sampled:
                continue
            engines = arms.runnable(assignment, self.settings.shadow_engines)
            memo = (w.fixture_id, w.pass_kind, w.packet_id)
            if not engines or memo in _failed:
                continue
            self.item(w, engines, memo)

    def item(self, w: Work, engines: tuple[str, ...], memo: tuple[int, str, int]) -> None:
        try:
            self.shadow(w, engines)
        except Exception as exc:  # whatever went wrong with one match is rolled back and counted: the loop goes on and the pipeline never notices
            self.tally.failed_open += 1
            if len(_failed) >= FAILED_MEMORY:
                _failed.clear()
            _failed.add(memo)
            log.warning(
                "orchestrator.failed_open",
                extra={"fixture": w.fixture_id, "pass": w.pass_kind, "code": type(exc).__name__},
            )
            try:
                if self.conn.closed:
                    self.stopped = True
                    return
                self.conn.rollback()
            except Exception:  # a connection that cannot even roll back is no connection to go on with: the run ends, the job's cycle goes on
                self.stopped = True

    # -- one pass --------------------------------------------------------------------------------------------------------------------

    def shadow(self, w: Work, engines: tuple[str, ...]) -> None:
        now = self.clock()
        stored = batch_tasks(self.conn, w)  # a pass is decided ONCE: tasks in the Batch mean it is a pass of the Batch calendar for good
        if stored:
            engines = self.stored_engines(stored, engines)
        elif runtime.verdict(w.pass_kind, w.kickoff_at, now, EXPECTED) == "too_late":
            self.tally.too_late += 1
            log.info("orchestrator.too_late", extra={"fixture": w.fixture_id, "pass": w.pass_kind})
            return
        package = mcp_package.derive(
            self.conn, w.packet_id, pass_kind=w.pass_kind, model_code=model_code_version()
        )
        if package is None or package.fixture_id != w.fixture_id:
            raise LookupError(f"the packet {w.packet_id} is not the match's")
        slices = mcp_package.slices_of(package)
        slice_ = slices["match"]
        packet = load_packet(self.conn, w.packet_id)
        if packet is None:
            raise LookupError(f"the packet {w.packet_id} is not there")
        rev = reviewed(self.conn, w)
        stats_on = self.stats_wanted(stored)
        naming = name_with_counts(rev.candidates) if stats_on else name_candidates(rev.candidates)
        p = _Pass(
            work=w,
            engines=engines,
            package=package,
            slice_=slice_,
            candidates=rev,
            naming=naming,
            packet=packet,
            started=now,
            slices=dict(slices),
            stats_on=stats_on,
            stats_slice=slices.get("stats") if stats_on else None,
        )

        reason: str | None = None
        if package.blocking:
            reason = "blocked:" + ",".join(sorted(package.blocking))
        elif not naming.named:
            reason = "no_candidate_to_name"
        elif not slice_.fits:
            reason = "slice_over_its_cap"
        if reason is not None:
            if stored:  # cannot happen to a pass that was queued; if it does, what waits is closed, not left to the end of the match
                close_tasks(self.conn, [t.task_id for t in stored if t.open], at=now, error=reason[:300])
            self.not_run(p, reason)
            return

        contra0 = contra.detect(package.document, naming=naming, assessments=(), at=p.at)
        if stored:
            self.resume(p, stored, contra0)
            return
        in_batch = self.batch_eligible(p)
        plan = self.plan(p, contra0, batch=in_batch)
        room = self.room()
        stop = budget_stop_reason(room.can_spend, room.remaining, room.reason, plan.estimate)
        if stop is not None:
            self.tally.budget_stop = stop
            self.stopped = True
            self.conn.rollback()
            log.info("orchestrator.budget_stop", extra={"code": stop})
            return
        paused = self.pausing(p, room)
        active = [e for e in engines if e not in paused]
        if not active:
            self.not_run(p, "every_arm_paused", paused=paused)
            return

        if in_batch:
            p.batch = BatchRun(queue=self.queue(), active=tuple(active), paused=dict(paused))
            self.batch_stages(p, contra0, room)
            return
        prod = usage.budget(self.conn, at=now, settings=self.settings)
        p.tiers_ok = {t: prod.allows(t) for t in ("bulk", "analysis", "final")}
        contra1 = tuple(contra0)
        if any(e in WITH_MATCH for e in active):
            contra1 = self.match_round(p, contra0)
        self.councils(p, active, contra0, contra1, room)
        self.escalate(p, contra1, room)
        self.store(p, contra1, paused)
        self.tally.ran += 1
        log.info(
            "orchestrator.pass",
            extra={"fixture": w.fixture_id, "pass": w.pass_kind, "engines": list(active)},
        )

    def stats_wanted(self, stored: Sequence[StoredTask]) -> bool:
        """Whether the Statistics Agent is on for this pass (phase 4). A pass that is new follows ``FBI_AI_AGENTS``; a pass of the Batch calendar keeps
        what its first run decided (``route.stats``: the names of the candidates, and so every key of its tasks, depend on it) whatever the switch says
        now. A pass stored before this phase has no such word and is a pass without the agent."""
        if stored:
            return stored[0].route.get("stats") is True
        return stats.AGENT in self.settings.agents

    # -- the Batch calendar ------------------------------------------------------------------------------------------------------------

    @staticmethod
    def stored_engines(stored: Sequence[StoredTask], engines: tuple[str, ...]) -> tuple[str, ...]:
        """The engines a pass of the Batch calendar started with (the first run's decision is the experiment's memory), as far as they can still run."""
        first = stored[0].route.get("engines")
        if isinstance(first, list):
            return tuple(e for e in (str(x) for x in first) if e in ENGINE_LEVEL)
        return engines

    def batch_eligible(self, p: _Pass) -> bool:
        """Whether this pass travels in the Batch: the queue's own rule (``BatchQueue.routes``: the pass is ``first`` or ``pre``, the match is far
        enough, the ``batch`` gate covers the model) for the tier of EVERY engine and of the Match Agent. One tier that cannot make the whole pass
        synchronous: a pass is either one or the other, never both. Decided once - the tasks it stores are the memory."""
        queue = self.queue()
        tiers = {router.TIER_OF_LEVEL[ENGINE_LEVEL[e]] for e in p.engines}
        if any(e in WITH_MATCH for e in p.engines):
            tiers.add(router.TIER_OF_LEVEL["simple"])
        return bool(tiers) and all(
            queue.routes(
                tier=cast(Tier, t),
                pass_kind=p.work.pass_kind,
                kickoff_at=p.work.kickoff_at,
                role="candidate",
                lab=True,
            )
            for t in sorted(tiers)
        )

    def resume(self, p: _Pass, stored: Sequence[StoredTask], contra0: Sequence[Contradiction]) -> None:
        """Pick a pass of the Batch calendar up where the last run left it. The code that built its package must be the one that stored its tasks
        (else the questions would not be the same ones, and they would be paid twice): a pass whose package changed under it is ended, not redone."""
        first = stored[0]
        run = BatchRun(queue=self.queue(), stored={t.key: t for t in stored})
        run.active = tuple(str(e) for e in first.route.get("active") or () if str(e) in p.engines)
        raw = first.route.get("paused")
        run.paused = {
            str(k): [str(x) for x in v] for k, v in (raw.items() if isinstance(raw, dict) else ()) if str(k) in p.engines
        }
        frozen = next((t.route.get("hours_to_kickoff") for t in stored if t.route.get("hours_to_kickoff") is not None), None)
        run.hours = None if frozen is None else Decimal(str(frozen))
        p.batch = run
        if any(t.package_hash is not None and t.package_hash != p.package.hash for t in stored):
            closed = close_tasks(self.conn, [t.task_id for t in stored if t.open], at=self.clock(), error="package_changed")
            self.tally.abandoned += closed
            self.not_run(p, "package_changed")
            return
        self.batch_stages(p, contra0, self.room())

    def batch_stages(self, p: _Pass, contra0: Sequence[Contradiction], room: Room) -> None:
        """One run over the stages of a pass of the Batch calendar: ask what is not stored yet (a task is queued, a stored one is read), and stop at
        the first stage that waits. The pass is written when nothing waits."""
        b = p.batch
        assert b is not None
        active = list(b.active)
        contra1 = tuple(contra0)
        match_waits = False
        if any(e in WITH_MATCH for e in active):
            self.match_task(p, "CONTEXT", match.context_request(p.slice_, at=p.at))
            if not self.exhausted:
                self.match_task(
                    p,
                    "EVALUATION",
                    match.evaluation_request(p.slice_, p.naming, at=p.at, contradictions=contra0),
                )
            if not self.exhausted:
                self.stats_task(p, contra0)
            match_waits = any(a.pending for a in p.match_users)
            if not match_waits:
                contra1 = contra.detect(
                    p.package.document, naming=p.naming, assessments=p.assessed, at=p.at
                )
        ready = [e for e in active if e not in WITH_MATCH or not match_waits]
        self.councils(p, active, contra0, contra1, room, only=ready)
        if match_waits or any(a.pending for a in p.asked.values()):
            self.park(p)
            return
        self.escalate(p, contra1, room)
        if any(a.pending for a in p.asked.values()):
            self.park(p)
            return
        self.batch_end(p, contra1)

    def batch_end(self, p: _Pass, contra1: Sequence[Contradiction]) -> None:
        """Write the pass of the Batch calendar: nothing waits any more (a task still open at ``ABANDON_BEFORE`` was ended ``batch_too_late``)."""
        b = p.batch
        assert b is not None
        self.store(p, contra1, b.paused)
        self.tally.ran += 1
        log.info(
            "orchestrator.pass",
            extra={"fixture": p.work.fixture_id, "pass": p.work.pass_kind, "engines": list(b.active), "batch": True},
        )

    def park(self, p: _Pass) -> None:
        """The pass waits for the Batch: what this run queued is sent NOW (the same run that recorded it), and the job's next run looks again."""
        b = p.batch
        assert b is not None
        if b.queued_now:
            report = b.queue.flush()
            self.tally.queued += b.queued_now
            if report.error is not None and "limit_reached" in report.error:
                self.exhausted = True
                self.tally.budget_stop = "exhausted"
                self.stopped = True
        else:
            self.conn.commit()
        self.tally.waiting += 1
        log.info(
            "orchestrator.waiting",
            extra={"fixture": p.work.fixture_id, "pass": p.work.pass_kind, "queued": b.queued_now},
        )

    # -- planning --------------------------------------------------------------------------------------------------------------------

    @dataclass(frozen=True, slots=True)
    class Plan:
        estimate: Decimal

    def plan(self, p: _Pass, contra0: Sequence[Contradiction], *, batch: bool = False) -> Plan:
        """The estimate of the pass: every call it plans, at the full price (the Batch's half), with the Council's view as it will be without the
        assessments. A pass of the Batch calendar is checked against the LAB's day as a WHOLE before anything is queued."""
        total = Decimal(0)
        if any(e in WITH_MATCH for e in p.engines):
            total += self.estimate(
                match.model_of("CONTEXT"), match.context_request(p.slice_, at=p.at), batch=batch
            )
            total += self.estimate(
                match.model_of("EVALUATION"),
                match.evaluation_request(p.slice_, p.naming, at=p.at, contradictions=contra0),
                batch=batch,
            )
            total += self.stats_estimate(p, contra0, batch=batch)
        view = council.council_view(p.slice_, p.naming, assessments=(), contradictions=contra0)
        if view.fits:
            for engine in p.engines:
                request = council.council_request(
                    view, p.naming, level=cast(council.CouncilLevel, ENGINE_LEVEL[engine]), at=p.at
                )
                total += self.estimate(
                    council.model_of(cast(council.CouncilLevel, ENGINE_LEVEL[engine])),
                    request,
                    batch=batch,
                )
        return _Runner.Plan(estimate=total * ESTIMATE_MARGIN)

    def pausing(self, p: _Pass, room: Room) -> dict[str, list[str]]:
        """The arms that do not run for this pass, with why (``runtime.arm_pause``): the circuit of a model they need is open, the arm's day is over
        3 % invalid outputs, or the envelope is spent."""
        now = self.clock()
        paused: dict[str, list[str]] = {}
        for engine in p.engines:
            models = [council.model_of(cast(council.CouncilLevel, ENGINE_LEVEL[engine]))]
            if engine in WITH_MATCH:
                models.append(match.model_of("CONTEXT"))
                if p.stats_on and p.stats_slice is not None and stats.model_of() not in models:
                    models.append(stats.model_of())
            states = {m: self.circuit.state(m, now) for m in models}
            answers, invalid = store_arm_today(self.conn, engine, now)
            reasons = runtime.arm_pause(
                invalid=invalid,
                calls=answers,
                circuit_state="open" if "open" in states.values() else "closed",
                envelope_left_usd=room.remaining,
            )
            if reasons:
                paused[engine] = reasons
                self.tally.circuit_open.update(m for m, s in states.items() if s == "open")
                self.tally.paused.extend(f"{engine}:{r}" for r in reasons)
        return paused

    # -- the Match Agent -------------------------------------------------------------------------------------------------------------

    def match_round(self, p: _Pass, contra0: Sequence[Contradiction]) -> tuple[Contradiction, ...]:
        """The Match Agent's two tasks and the detector over the whole package with what it assessed. A task that does not stand leaves the Council to
        read the others (fail open)."""
        self.match_task(p, "CONTEXT", match.context_request(p.slice_, at=p.at))
        if not self.exhausted:
            self.match_task(
                p,
                "EVALUATION",
                match.evaluation_request(p.slice_, p.naming, at=p.at, contradictions=contra0),
            )
        if not self.exhausted:
            self.stats_task(p, contra0)
        return contra.detect(p.package.document, naming=p.naming, assessments=p.assessed, at=p.at)

    def match_task(self, p: _Pass, mode: str, request: JsonRequest) -> Asked:
        task = match.TASK[mode]
        model = match.model_of(cast(Any, mode))
        candidates = match.asked_keys(p.naming) if mode == "EVALUATION" else ()
        identity = REGISTRY.identity_for(
            "match",
            task,
            workspace="lab",
            input_version=mcp_package.VERSION,
            input_hash=p.slice_.hash,
            pass_kind=p.work.pass_kind,
            fixture_id=p.work.fixture_id,
            candidates=candidates,
        )
        decision = router.route(
            router.Signals(
                task=cast(router.Task, task),
                day=self.day(self.room()),
                budget_state="NORMAL",
                pass_kind=p.work.pass_kind,
                blocking=(),
            )
        )
        asked = self.ask(
            p,
            identity=identity,
            task_kind=task,
            level="simple",
            request=request,
            purpose="match_analysis",
            prompt_version=prompt_labels.MATCH_CONTEXT_VERSION
            if mode == "CONTEXT"
            else prompt_labels.MATCH_ASSESS_VERSION,
            input_hash=match.input_hash(request),
            decision=decision,
            model=model,
            agent=match.AGENT,
            stage=1,
        )
        p.match_users.append(asked)
        if asked.data is not None and asked.error is None:
            reading = match.read(
                asked.data,
                mode=cast(Any, mode),
                slice_=p.slice_,
                naming=p.naming if mode == "EVALUATION" else None,
            )
            self.finish_match(p, asked, reading, mode)
        return asked

    def finish_match(
        self, p: _Pass, asked: Asked, reading: match.Reading, mode: str, *, agent: str = match.AGENT
    ) -> None:
        """Complete a task of the agents that assess (``match``, and ``stats`` in phase 4: the same contract, the same reader of an answer) and keep
        its assessment, with the label the Council and the detector cite it by, when it stands."""
        if asked.reused:
            pass  # stored and paid before: nothing of it is written again
        elif reading.ok and reading.assessment is not None:
            out = reading.assessment
            asked.status, asked.state = "ok", "done"
            asked.output = out.model_dump(mode="json")
            stances = [c.stance for c in out.candidates]
            asked.verdict = verdict_string(stances) or None
            asked.evidence_ids, asked.data_refs = self.refs(asked.output)
        else:
            asked.status, asked.state, asked.error = (
                "invalid",
                "done",
                ",".join(reading.problems)[:2000] or "invalid_output",
            )
            self.tally.invalid += 1
            asked.data = None
        got = (
            stats.assessed(reading)
            if agent == stats.AGENT
            else match.assessed(reading, mode=cast(Any, mode))
        )
        if got is not None and reading.assessment is not None:
            p.assessed.append(got)
            p.stances[got.label] = {c.candidate: c.stance for c in got.out.candidates}
            if got.out.research:
                p.ignored_asks.extend(r.topic for r in got.out.research)

    # -- the Statistics Agent --------------------------------------------------------------------------------------------------------

    def stats_estimate(self, p: _Pass, contra0: Sequence[Contradiction], *, batch: bool) -> Decimal:
        """What the Statistics Agent's task will cost, for the plan of the pass: nothing when it will not be asked."""
        if not p.stats_on or p.stats_slice is None or not stats.asked_keys(p.naming):
            return Decimal(0)
        try:
            request = stats.evaluation_request(p.stats_slice, p.naming, at=p.at, contradictions=contra0)
        except ValueError:  # a slice that cannot be asked about costs nothing: the task is skipped, with the code
            return Decimal(0)
        return self.estimate(stats.model_of(), request, batch=batch)

    def stats_task(self, p: _Pass, contra0: Sequence[Contradiction]) -> Asked | None:
        """The Statistics Agent's task: the corners and cards of the whole match, assessed over the ``stats`` slice (Haiku, the router's ``evaluation``).
        Nothing is asked when the agent is off or there is no count to assess. A slice that cannot be read (blocked, over its cap) leaves the task
        SKIPPED with the code, and the Council reads the others: fail open. An answer that does not stand abstains in the same way."""
        stats_slice = p.stats_slice
        if not p.stats_on or stats_slice is None:
            return None
        keys = stats.asked_keys(p.naming)
        if not keys:
            p.stats_note = "no_count_to_assess"
            return None
        identity = REGISTRY.identity_for(
            stats.AGENT,
            stats.TASK,
            workspace="lab",
            input_version=mcp_package.VERSION,
            input_hash=stats_slice.hash,
            pass_kind=p.work.pass_kind,
            fixture_id=p.work.fixture_id,
            candidates=keys,
        )
        try:
            request = stats.evaluation_request(stats_slice, p.naming, at=p.at, contradictions=contra0)
        except ValueError:
            why = "stats_slice_over_its_cap" if not stats_slice.fits else "stats_request_refused"
            p.stats_note = why
            skipped = self.skipped_task(p, identity, stats.TASK, why, Decimal("0.000001"))
            p.match_users.append(skipped)
            return skipped
        decision = router.route(
            router.Signals(
                task=stats.TASK,
                day=self.day(self.room()),
                budget_state="NORMAL",
                pass_kind=p.work.pass_kind,
                blocking=(),
            )
        )
        asked = self.ask(
            p,
            identity=identity,
            task_kind=stats.TASK,
            level="simple",
            request=request,
            purpose="match_analysis",
            prompt_version=prompt_labels.STATS_ASSESS_VERSION,
            input_hash=stats.input_hash(request),
            decision=decision,
            model=stats.model_of(),
            agent=stats.AGENT,
            stage=1,
        )
        p.match_users.append(asked)
        if asked.data is not None and asked.error is None:
            reading = stats.read(asked.data, slice_=stats_slice, naming=p.naming)
            self.finish_match(p, asked, reading, stats.MODE, agent=stats.AGENT)
        return asked

    @staticmethod
    def refs(output: dict[str, Any]) -> tuple[tuple[int, ...], tuple[str, ...]]:
        evidence, paths = refs_in(output)
        return tuple(evidence), tuple(paths)

    # -- the Council -----------------------------------------------------------------------------------------------------------------

    def councils(
        self,
        p: _Pass,
        active: Sequence[str],
        contra0: Sequence[Contradiction],
        contra1: Sequence[Contradiction],
        room: Room,
        *,
        only: Sequence[str] | None = None,
    ) -> None:
        """The arms of the pass and the Council task of each one that is active. ``only`` (the Batch calendar) names the engines whose Council can
        be asked now - the ones that read assessments wait for the Match Agent's stage - and the others get their arm and no task yet."""
        shared_view: council.CouncilView | None = None
        solo_view: council.CouncilView | None = None
        for engine in p.engines:
            arm = Arm(engine=engine, level=ENGINE_LEVEL[engine])
            p.arms.append(arm)
            if engine not in active:
                arm.reason = "paused"
                continue
            if only is not None and engine not in only:
                continue
            if engine in WITH_MATCH:
                shared_view = shared_view or council.council_view(
                    p.slice_, p.naming, assessments=p.assessed, contradictions=contra1
                )
                arm.view = shared_view
                arm.users.extend(a for a in p.match_users)
            else:
                solo_view = solo_view or council.council_view(
                    p.slice_, p.naming, assessments=(), contradictions=contra0
                )
                arm.view = solo_view
            self.council_task(p, arm, room)

    def council_task(self, p: _Pass, arm: Arm, room: Room) -> None:
        view = arm.view
        assert view is not None
        level = cast(council.CouncilLevel, arm.level)
        model = council.model_of(level)
        if not view.fits:
            arm.reason = "view_too_large"
            identity = REGISTRY.identity_for(
                "council",
                "council",
                workspace="lab",
                input_version=council.VIEW_VERSION,
                input_hash=view.hash,
                pass_kind=p.work.pass_kind,
                fixture_id=p.work.fixture_id,
                candidates=p.naming.keys,
                model=model,
            )
            skipped = self.skipped_task(
                p, identity, "council", "view_too_large", Decimal("0.000001")
            )
            arm.asked = skipped
            arm.users.append(skipped)
            return
        request = council.council_request(view, p.naming, level=level, at=p.at)
        identity = REGISTRY.identity_for(
            "council",
            "council",
            workspace="lab",
            input_version=council.VIEW_VERSION,
            input_hash=view.hash,
            pass_kind=p.work.pass_kind,
            fixture_id=p.work.fixture_id,
            candidates=p.naming.keys,
            model=model,
        )
        decision = router.route(
            router.Signals(
                task="council",
                day=self.day(room),
                budget_state="NORMAL",
                pass_kind=p.work.pass_kind,
                arm_model=model,
            )
        )
        asked = self.ask(
            p,
            identity=identity,
            task_kind="council",
            level=arm.level,
            request=request,
            purpose="pick_review",
            prompt_version=prompt_labels.COUNCIL_VERSION,
            input_hash=council.input_hash(request),
            decision=decision,
            model=model,
            agent=council.AGENT,
            stage=2 if arm.engine in WITH_MATCH else 1,
        )
        arm.asked = asked
        arm.users.append(asked)
        self.read_council(p, arm, asked, view, asked_keys=None)

    def read_council(
        self,
        p: _Pass,
        arm: Arm,
        asked: Asked,
        view: council.CouncilView,
        *,
        asked_keys: Sequence[str] | None,
    ) -> council.Reading | None:
        """Read a Council answer against ITS view and complete the task with what the server makes of it."""
        if asked.data is None or asked.error is not None:
            return None
        reading = council.read(asked.data, view=view, naming=p.naming, asked=asked_keys)
        self.settle(asked, reading)
        return reading

    def settle(self, asked: Asked, reading: council.Reading) -> None:
        """Complete a task that was answered with what the contract made of the answer (once: a stored or shared task is already complete)."""
        if asked.reused or asked.status in ("ok", "abstain", "invalid"):
            return
        if reading.status == "ok" and reading.council is not None:
            verdicts = [v.verdict for v in reading.council.verdicts]
            asked.status = "abstain" if verdicts and all(v == "ABSTAIN" for v in verdicts) else "ok"
            asked.state = "done"
            asked.output = reading.council.model_dump(mode="json")
            asked.verdict = verdict_string(verdicts) or None
            asked.evidence_ids, asked.data_refs = self.refs(asked.output)
        else:
            asked.status, asked.state = "invalid", "done"
            asked.error = ",".join(reading.problems)[:2000] or "invalid_output"
            self.tally.invalid += 1
            asked.data = None

    # -- the escalation --------------------------------------------------------------------------------------------------------------

    def escalate(self, p: _Pass, contra1: Sequence[Contradiction], room: Room) -> None:
        for arm in p.arms:
            if (arm.asked is not None and arm.asked.answered) or (
                arm.asked is not None and arm.asked.reused and arm.asked.data is not None
            ):
                assert arm.view is not None
                arm.reading = council.read(arm.asked.data, view=arm.view, naming=p.naming)
            if arm.engine not in WITH_MATCH or arm.reading is None:
                continue
            facts = council.escalation_facts(
                arm.reading,
                self.escalation_naming(p),
                contra1,
                hours_to_kickoff=self.hours_for(p),
                pick_of_the_day=(),
                main_parlay_legs=(),
                researched=False,
                edge_validated=(),
            )
            fired = {k: rules[0] for k, f in facts.items() if (rules := router.fired_rules(f))}
            if not fired:
                continue
            qualified = [q for k in fired if (q := router.qualify(k, facts[k])) is not None]
            top = router.escalation_order(qualified)[0]
            arm.escalated = dict(sorted(fired.items(), key=lambda kv: (len(kv[0]), kv[0])))
            self.opus_task(p, arm, facts_of_top=top.facts, room=room)

    @staticmethod
    def escalation_naming(p: _Pass) -> Naming:
        """The candidates the rules E1-E7 of ``router-v1`` look at: those of goals and result, as in phase 3. The counts (corners and cards) of the
        Statistics Agent's shadow are never sent to Opus: its three calls a day are the Council's for the selections the plan escalated, and a count
        whose rules nobody has measured does not take them."""
        if not p.stats_on:
            return p.naming
        return Naming(tuple(n for n in p.naming.named if n.family in GOALS_RESULT), p.naming.left_out, p.naming.version)

    def hours_for(self, p: _Pass) -> Decimal:
        """The hours to the kick-off the escalation rules read. In the Batch calendar they are frozen the first time (the first Opus task keeps them
        in its route): the rules must fire on the same candidates when a later run reads the same pass again, or the question would be another."""
        b = p.batch
        if b is None:
            return hours_to(p.work.kickoff_at, self.clock())
        if b.hours is None:
            b.hours = hours_to(p.work.kickoff_at, self.clock())
        return b.hours

    def opus_task(self, p: _Pass, arm: Arm, *, facts_of_top: router.Facts, room: Room) -> None:
        view = arm.view
        reading = arm.reading
        assert view is not None and reading is not None
        keys = sorted(arm.escalated, key=lambda k: (len(k), k))
        first = [
            (v.candidate, v.verdict, v.confidence)
            for v in (reading.council.verdicts if reading.council is not None else ())
            if v.candidate in arm.escalated
        ]
        request = council.council_request(
            view,
            p.naming,
            level="critical",
            at=p.at,
            asked=keys,
            escalation=arm.escalated,
            first_round=first,
        )
        model = council.model_of("critical")
        identity = REGISTRY.identity_for(
            "council",
            "escalation",
            workspace="lab",
            input_version=council.VIEW_VERSION,
            input_hash=council.input_hash(request),
            pass_kind=p.work.pass_kind,
            fixture_id=p.work.fixture_id,
            candidates=keys,
            model=model,
        )
        parent = arm.asked.key if arm.asked is not None else None
        shared = p.asked.get(identity.key)
        if (
            shared is not None
        ):  # the other arm asked the very same question: one call serves both, and is paid once
            asked = shared
            shared.shared = True
        else:
            decision = router.route(
                router.Signals(
                    task="escalation",
                    day=self.day(room),
                    budget_state="NORMAL",
                    pass_kind=p.work.pass_kind,
                    facts=facts_of_top,
                )
            )
            est = self.estimate(model, request, batch=p.batch is not None)
            if p.batch is None and decision.call and not self.affordable(est):
                decision = replace(
                    decision, action="SKIP", rule="budget", reasons=("lab_envelope",)
                )
            asked = self.ask(
                p,
                identity=identity,
                task_kind="escalation",
                level="critical",
                request=request,
                purpose="pick_review",
                prompt_version=prompt_labels.COUNCIL_OPUS_VERSION,
                input_hash=council.input_hash(request),
                decision=decision,
                model=model,
                agent=council.AGENT,
                parent_key=parent,
                est=est,
                stage=3,
                route_extra={"hours_to_kickoff": str(self.hours_for(p)), "escalated": dict(arm.escalated)},
            )
            if asked.calls and asked.batch_task is None:
                self.opus_made += 1
                self.opus_cost += asked.cost
            elif asked.pending and asked.batch_task is not None and asked.queued_here:
                self.opus_made += 1
                self.opus_cost += asked.est
        arm.opus = asked
        arm.users.append(asked)
        if asked.skip is not None and not asked.calls:
            self.tally.escalation_skipped += len(keys)
            arm.skipped_escalation = dict.fromkeys(keys, asked.skip)
            return
        if asked.calls and not asked.shared:
            self.tally.escalated += len(keys)
        if asked.data is not None and asked.error is None:
            got = council.read(asked.data, view=view, naming=p.naming, asked=keys)
            self.settle(asked, got)
            if got.status == "ok" and got.council is not None and asked.error is None:
                arm.opus_reading = got

    # -- the call --------------------------------------------------------------------------------------------------------------------

    def affordable(self, estimate: Decimal) -> bool:
        room = self.room()
        return budget_stop_reason(room.can_spend, room.remaining, room.reason, estimate) is None

    def skipped_task(
        self, p: _Pass, identity: TaskIdentity, task_kind: str, why: str, est: Decimal
    ) -> Asked:
        now = self.clock()
        decision = router.Decision(
            task=task_kind, action="SKIP", rule="task", reasons=(why,), params=router.params_hash()
        )
        asked = Asked(
            identity,
            task_kind,
            est,
            decision,
            now,
            now,
            skip=why,
            status="skipped",
            state="skipped",
            error=why,
        )
        p.asked[asked.key] = asked
        return asked

    def ask(
        self,
        p: _Pass,
        *,
        identity: TaskIdentity,
        task_kind: str,
        level: str,
        request: JsonRequest,
        purpose: str,
        prompt_version: str,
        input_hash: str,
        decision: router.Decision,
        model: str,
        agent: str,
        parent_key: str | None = None,
        est: Decimal | None = None,
        stage: int = 1,
        route_extra: Mapping[str, Any] | None = None,
    ) -> Asked:
        """THE place where a task of the shadow becomes a model call - or an item of the Message Batches API, for a pass of the Batch calendar
        (``ask_batch``: ``stage`` and ``route_extra`` are for that route and mean nothing in real time).

        In order: the same question already asked in this pass is not asked again; one already stored (a task with this idempotency key) is read, not
        paid; the router's decision (a cap or the budget may say no); the deadline; the production budget's tier; the configuration; then a slot of the
        level, the circuit of the model and the retries of transport failures, in ``runtime``. The model and the request are the router's and never change."""
        key = identity.key
        seen = p.asked.get(key)
        if seen is not None:
            seen.shared = True
            return seen
        now = self.clock()
        in_batch = getattr(p, "batch", None) is not None
        price = est if est is not None else self.estimate(model, request, batch=in_batch)
        asked = Asked(identity, task_kind, price, decision, now, now, parent_key=parent_key)
        p.asked[key] = asked
        if in_batch:
            return self.ask_batch(
                p,
                asked,
                level=level,
                request=request,
                purpose=purpose,
                prompt_version=prompt_version,
                input_hash=input_hash,
                model=model,
                agent=agent,
                stage=stage,
                route_extra=route_extra or {},
            )
        old = existing(self.conn, key)
        if old is not None:
            return self.reuse(asked, old)
        if not decision.call:
            return self.skip(
                asked,
                decision.reasons[0] if decision.reasons else "router",
                "budget_skip",
                "skipped",
            )
        if self.exhausted:
            return self.skip(asked, "exhausted", "budget_skip", "skipped")
        left = runtime.time_left(p.work.pass_kind, p.work.kickoff_at, now).total_seconds()
        if left < MIN_CALL_S:
            return self.skip(asked, "deadline", "expired", "expired")
        tier = router.TIER_OF_LEVEL[level]
        if not p.tiers_ok.get(tier, False):
            return self.skip(asked, f"tier_{tier}_not_allowed", "budget_skip", "skipped")
        if self.provider is None:
            configured = self.settings.tier(cast(Tier, tier), lab=True)
            if configured is None or configured.model != model:
                return self.skip(asked, "model_not_configured", "skipped", "skipped")
        timed = replace(request, timeout_s=max(1.0, min(request.timeout_s, left - 5.0)))
        outcomes: list[usage.CallOutcome] = []

        def call() -> usage.CallOutcome:
            made = usage.call_json(
                self.conn,
                self.settings,
                tier=cast(Tier, tier),
                purpose=cast(Any, purpose),
                request=timed,
                at=self.clock(),
                prompt_version=prompt_version,
                input_hash=input_hash,
                fixture_id=p.work.fixture_id,
                ledger=self.ledger,
                transport=self.transport,
                provider=None if self.provider is None else (self.provider, model),
                lab=True,
                agent=agent,
                run_id=None,
            )
            outcomes.append(made)
            return made

        with self.slots.acquire(level, timeout_s=SLOT_WAIT_S) as got:
            if not got:
                return self.skip(asked, "no_slot", "skipped", "skipped")
            attempts = runtime.run_with_retries(
                call,
                sleep=self.sleep,
                circuit=self.circuit,
                model=model,
                now=self.clock,
                deadline_at=runtime.final_deadline(p.work.kickoff_at),
            )
        asked.finished = self.clock()
        asked.calls = attempts.calls
        asked.stopped_by = attempts.stopped_by
        self.tally.calls += attempts.calls
        asked.cost = sum((o.cost for o in outcomes), Decimal(0))
        self.tally.cost += asked.cost
        asked.usage_ids = [o.usage_id for o in outcomes if o.usage_id]
        last = attempts.last
        if last is None:  # no call was made: the circuit refused or the deadline came
            if attempts.stopped_by == "circuit_open":
                self.tally.circuit_open.add(model)
                return self.skip(asked, "circuit_open", "skipped", "skipped")
            return self.skip(asked, "deadline", "expired", "expired")
        asked.provider = last.provider
        asked.model = last.model
        if last.error is not None:
            asked.error = last.error
            asked.status, asked.state = outcome_status(last.error)
            if last.error == "over_budget":
                self.exhausted = True
                self.tally.budget_stop = "exhausted"
                self.stopped = True
            elif last.error == "invalid_output":
                self.tally.invalid += 1
            elif attempts.stopped_by == "circuit_open":
                self.tally.circuit_open.add(model)
            return asked
        if last.result is None or last.model != model:
            asked.status, asked.state, asked.error = "invalid", "done", "model_mismatch"
            self.tally.invalid += 1
            return asked
        asked.data = dict(last.result.data)
        return asked

    # -- the Batch route of a task ---------------------------------------------------------------------------------------------------

    def ask_batch(
        self,
        p: _Pass,
        asked: Asked,
        *,
        level: str,
        request: JsonRequest,
        purpose: str,
        prompt_version: str,
        input_hash: str,
        model: str,
        agent: str,
        stage: int,
        route_extra: Mapping[str, Any],
    ) -> Asked:
        """A task of a pass of the Batch calendar. A task stored ``queued`` is READ: its item is still open (the pass waits), has the poll's raw answer
        (the task becomes an answered ``Asked``, validated by the reader exactly as an answer in real time is), or ended without one (an arm
        ``fallback`` with the code, unpaid, never asked again; an item that was only abandoned, never sent, is asked again by the queue, whose
        limits hold). A task not stored is QUEUED - after the router, the gates of the stage and the queue's own budget check - and its row is
        written in the same transaction as its batch item. There is no way from here to a paid call in real time."""
        b = p.batch
        assert b is not None
        key = asked.key
        st = b.stored.get(key) or batch_task(self.conn, key)
        if st is None or not st.open:
            old = existing(self.conn, key)
            if old is not None:  # asked before (by another pass with the same question, or stored ended): read, not paid
                return self.reuse(asked, old)
        lead = p.work.kickoff_at - self.clock()

        def queue_it(old: StoredTask | None) -> Asked | StoredTask:
            return self.batch_add(
                p,
                asked,
                old,
                lead=lead,
                level=level,
                request=request,
                purpose=purpose,
                prompt_version=prompt_version,
                input_hash=input_hash,
                model=model,
                agent=agent,
                stage=stage,
                route_extra=route_extra,
            )

        if st is not None and st.open:
            if key not in b.stored:  # the question of ANOTHER pass (the same slice under another packet): its answer may be read, its task is not ours
                got = self.batch_read(p, asked, st, lead, redo=None)
                asked.batch_task, asked.batch_custom = None, None
                asked.cost, asked.usage_ids = Decimal(0), []
                return got
            return self.batch_read(p, asked, st, lead, redo=lambda: queue_it(st))
        if not asked.decision.call:
            return self.skip(
                asked,
                asked.decision.reasons[0] if asked.decision.reasons else "router",
                "budget_skip",
                "skipped",
            )
        if self.exhausted:
            return self.skip(asked, "exhausted", "budget_skip", "skipped")
        fresh = queue_it(None)
        if isinstance(fresh, Asked):
            return fresh
        return self.batch_read(p, asked, fresh, lead, redo=None)

    def batch_add(
        self,
        p: _Pass,
        asked: Asked,
        old: StoredTask | None,
        *,
        lead: timedelta,
        level: str,
        request: JsonRequest,
        purpose: str,
        prompt_version: str,
        input_hash: str,
        model: str,
        agent: str,
        stage: int,
        route_extra: Mapping[str, Any],
    ) -> Asked | StoredTask:
        """Put a task into the queue of the Batch (``BatchQueue.add``) and store it ``queued`` (or, for an abandoned item asked again, point the
        stored task at its new batch). Returns the stored task, or the ``Asked`` when the task may not be queued (and says why)."""
        b = p.batch
        assert b is not None
        if lead < STAGE_MIN_LEAD:  # the stage cannot be answered before the final pass: the pass is given up, not asked in real time
            return self.batch_stop(p, asked, old, "too_late")
        if stage > 1 and not gates.enabled(self.conn, self.settings, "batch", model=model):
            return self.skip(asked, "batch_off", "skipped", "skipped")
        tier = router.TIER_OF_LEVEL[level]
        configured = self.settings.tier(cast(Tier, tier), lab=True)
        if configured is None or configured.model != model:
            return self.skip(asked, "model_not_configured", "skipped", "skipped")
        task = Task(
            purpose="other",
            tier=cast(Tier, tier),
            request=request,
            prompt_version=prompt_version,
            input_hash=input_hash,
            fixture_id=p.work.fixture_id,
            deadline_at=p.work.kickoff_at - BATCH_DEADLINE,
            context={
                "lab": "shadow",
                "idem": asked.key,
                "fixture": p.work.fixture_id,
                "pass": p.work.pass_kind,
                "packet_id": p.work.packet_id,
                "task": asked.task_kind,
                "stage": stage,
                "purpose": purpose,
            },
            lab=True,
            agent=agent,
            typical_output=request.max_tokens // 2,
        )
        adm = b.queue.add(task)
        if adm.status == "refused":
            why = adm.reason or "refused"
            if old is not None:
                return self.batch_stop(p, asked, old, "abandoned", why)
            if why == "lab_budget":
                return self.skip(asked, "lab_envelope", "budget_skip", "skipped")
            return self.skip(asked, f"batch_refused_{why}", "skipped", "skipped")
        batch_id = open_batch_of(self.conn, adm.custom_id)
        if adm.status == "queued":
            b.queued_now += 1
            asked.queued_here = True
            if adm.est_cost > 0:
                asked.est = adm.est_cost
        if old is not None:  # the stored task follows its item to the new batch
            link_batch(self.conn, old.task_id, batch_id)
            fresh = batch_task(self.conn, asked.key)
            assert fresh is not None
            b.stored[asked.key] = fresh
            return fresh
        route = {
            "stage": stage,
            "engines": list(p.engines),
            "active": list(b.active),
            "paused": {k: list(v) for k, v in b.paused.items()},
            "stats": p.stats_on,
            "adm": adm.status,
        } | dict(route_extra)
        rec = self.record(p, asked)
        rec = replace(
            rec,
            route=rec.route | route,
            deadline_at=p.work.kickoff_at - BATCH_DEADLINE,
            state="queued",
        )
        task_id = queue_task(self.conn, rec, custom_id=adm.custom_id, batch_id=batch_id)
        stored = batch_task(self.conn, asked.key)
        assert stored is not None and stored.task_id == task_id
        b.stored[asked.key] = stored
        return stored

    def batch_read(
        self,
        p: _Pass,
        asked: Asked,
        st: StoredTask,
        lead: timedelta,
        *,
        redo: Callable[[], Asked | StoredTask] | None,
    ) -> Asked:
        """What a stored task of the Batch is now: waiting, answered, or ended without an answer (see ``ask_batch``)."""
        asked.batch_task = st.task_id
        asked.batch_custom = st.custom_id
        asked.started = st.created_at
        status = st.item_status
        if status in ("submitting", "submitted"):
            if lead <= ABANDON_BEFORE:  # not settled by T-100: given up, and never asked in real time
                return self.batch_stop(p, asked, st, "too_late")
            asked.pending = True
            return asked
        if status in ("succeeded", "late", "invalid"):
            return self.batch_answer(asked, st)
        if status in ("errored", "canceled", "expired"):
            return self.batch_stop(p, asked, st, status, st.item_error)
        if status == "abandoned" and redo is not None:
            again = redo()
            if isinstance(again, Asked):
                return again
            if again.item_status in ("submitting", "submitted"):
                asked.pending = True
                return asked
            return self.batch_read(p, asked, again, lead, redo=None)
        return self.batch_stop(
            p, asked, st, "abandoned" if status == "abandoned" else "missing", st.item_error
        )

    def batch_answer(self, asked: Asked, st: StoredTask) -> Asked:
        """The poll's raw answer of an item, as a task answered: the reader (``match.read``, ``council.read``) validates it next, as in real time. An
        item shared with another task (the same request, answered once) is paid by the first one only."""
        res = st.result or {}
        asked.finished = self.clock()
        asked.calls = 1
        asked.provider = "anthropic"
        asked.model = st.item_model
        asked.batch_id = st.item_batch
        if st.item_idem is None or st.item_idem == asked.key:
            asked.cost = st.cost
            asked.usage_ids = [st.usage_id] if st.usage_id else []
        data = res.get("data")
        if res.get("ok") is True and isinstance(data, dict):
            asked.data = dict(data)
            return asked
        code = str(res.get("error") or st.item_error or "invalid_output")[:300]
        asked.error = code
        asked.status, asked.state = ("invalid", "done") if st.item_status == "invalid" else outcome_status(code)
        if asked.status == "invalid":
            self.tally.invalid += 1
        return asked

    def batch_stop(
        self, p: _Pass, asked: Asked, st: StoredTask | None, kind: str, detail: str | None = None
    ) -> Asked:
        """A task of the Batch that has no answer and will have none: its arm is ``fallback`` with ``batch_<kind>``. Nothing was paid; nothing is
        asked again."""
        status, state = BATCH_CODES[kind]
        code = f"batch_{kind}"
        if st is not None:
            asked.batch_task = st.task_id
            asked.batch_custom = st.custom_id
            asked.started = st.created_at
        self.skip(asked, code, status, state)
        asked.pending = False
        if detail:
            asked.error = f"{code}: {detail}"[:300]
        if kind == "too_late":
            p.too_late = True
            self.tally.abandoned += 1
        return asked

    def skip(self, asked: Asked, why: str, status: str, state: str) -> Asked:
        asked.skip, asked.error, asked.status, asked.state = why, why, status, state
        asked.finished = self.clock()
        return asked

    def reuse(self, asked: Asked, old: Existing) -> Asked:
        """The question was asked and stored before: its answer is read, nothing is paid and nothing is written again."""
        asked.reused = True
        self.tally.reused += 1
        asked.status = old.status or "skipped"
        asked.data = old.output if old.status in ("ok", "abstain") else None
        asked.model = old.model
        asked.error = None if asked.data is not None else (old.status or "task_exists")
        return asked

    # -- what is written -------------------------------------------------------------------------------------------------------------

    def tokens(self, asked: Asked) -> Tokens | None:
        return tokens_of(self.conn, asked.usage_ids[-1] if asked.usage_ids else None)

    def record(self, p: _Pass, asked: Asked) -> TaskRecord:
        route = asked.decision.record() | {
            "packet_id": p.work.packet_id,
            "engines": list(p.engines),
            "stopped_by": asked.stopped_by,
            "calls": asked.calls,
        }
        settings = self.settings
        return TaskRecord(
            identity=asked.identity,
            task_kind=asked.task_kind,
            reason=f"shadow {asked.task_kind} {p.work.pass_kind} match {p.work.fixture_id}",
            route=route,
            est_cost=asked.est,
            priority=priority_of(p.work.pass_kind, asked.task_kind),
            deadline_at=runtime.final_deadline(p.work.kickoff_at),
            state=asked.state,
            status=asked.status,
            started_at=asked.started,
            finished_at=asked.finished,
            known_at=p.package.known_at,
            package_hash=p.package.hash,
            slice_hash=p.stats_slice.hash
            if asked.identity.agent == stats.AGENT and p.stats_slice is not None
            else p.slice_.hash,
            model=asked.model,
            attempts=asked.calls,
            output=asked.output,
            verdict=asked.verdict,
            error=asked.error,
            tokens=self.tokens(asked) if asked.status in ("ok", "abstain", "invalid") else None,
            cost=asked.cost,
            usage_id=asked.usage_ids[-1] if asked.usage_ids else None,
            evidence_ids=asked.evidence_ids,
            data_refs=asked.data_refs,
            parent_key=asked.parent_key,
            workspace=settings.workspace_lab,
            key_label=settings.key_label_lab,
            router_version=router.VERSION,
            batch_id=asked.batch_id,
            custom_id=asked.batch_custom,
        )

    def finals(self, p: _Pass, arm: Arm, contra1: Sequence[Contradiction]) -> None:
        """What stands for each candidate of an engine: the Council's verdict, replaced by Opus' where Opus was asked and answered."""
        reading = arm.reading
        council_model = (
            arm.asked.model
            if arm.asked is not None and arm.asked.model
            else council.model_of(cast(council.CouncilLevel, arm.level))
        )
        if reading is not None and reading.council is not None:
            arm.status = STATUS_OK
            for v in reading.council.verdicts:
                arm.finals[v.candidate] = Verdict(
                    v.verdict,
                    v.confidence,
                    list(v.drivers),
                    list(v.risks),
                    list(v.refs),
                    council_model,
                )
            for change in reading.verified.changes if reading.verified is not None else ():
                if change.candidate in arm.finals:
                    arm.finals[change.candidate].changed.append(change.why)
        elif arm.asked is not None:
            arm.status, arm.reason = self.arm_status(arm.asked)
        else:
            arm.status = STATUS_FALLBACK
        opus_reading = arm.opus_reading
        if opus_reading is not None and opus_reading.council is not None and arm.opus is not None:
            opus_model = arm.opus.model or council.model_of("critical")
            for v in opus_reading.council.verdicts:
                if v.candidate in arm.escalated:
                    arm.finals[v.candidate] = Verdict(
                        v.verdict,
                        v.confidence,
                        list(v.drivers),
                        list(v.risks),
                        list(v.refs),
                        opus_model,
                        escalation=arm.escalated[v.candidate],
                        replaced=True,
                    )
            arm.status = STATUS_OK

    @staticmethod
    def arm_status(asked: Asked) -> tuple[str, str | None]:
        """The status of an engine whose Council has no verdict: why (``over_budget``, a failed call, an answer that did not validate, or an arm that
        did not run) and the code that says so."""
        if (
            asked.error == "over_budget"
            or asked.skip in ("exhausted", "lab_envelope")
            or (asked.status == "budget_skip" and asked.skip is None)
        ):
            return STATUS_OVER_BUDGET, asked.error
        if asked.status == "invalid":
            return STATUS_INVALID, asked.error
        if asked.skip is not None or (asked.status == "skipped" and asked.error is None):
            return STATUS_FALLBACK, asked.skip or asked.error
        if asked.status in ("timeout", "skipped", "expired"):
            return STATUS_FAILED, asked.error
        return STATUS_FALLBACK, asked.error

    def store(
        self, p: _Pass, contra1: Sequence[Contradiction], paused: Mapping[str, Sequence[str]]
    ) -> None:
        for arm in p.arms:
            if arm.engine in paused:
                arm.status, arm.reason = STATUS_FALLBACK, "paused:" + ",".join(paused[arm.engine])
                continue
            self.finals(p, arm, contra1)
        self.write(p, contra1, paused)

    def write(
        self, p: _Pass, contra1: Sequence[Contradiction], paused: Mapping[str, Sequence[str]]
    ) -> None:
        w = p.work
        now = self.clock()
        runs: dict[str, int] = {}
        asks = [a for a in p.asked.values() if not a.reused]
        state = StateRecord(
            work=w,
            created_at=now,
            package_version=mcp_package.VERSION,
            package_hash=p.package.hash,
            elapsed_ms=int((now - p.started).total_seconds() * 1000),
            slices=self.slices_of(p),
            blocking=tuple(p.package.blocking),
            flags=tuple(p.package.flags),
            model_status=self.model_status(p, contra1),
            research_status={
                "asks_ignored": len(p.ignored_asks),
                "topics": sorted(set(p.ignored_asks)),
                "mode": "shadow",
            },
            agents=[self.agent_row(a) for a in p.asked.values()],
            contradictions=[c.to_json() for c in contra1],
            candidates=self.candidate_rows(p),
            final=self.final_row(p, paused),
        )
        if write_state(self.conn, state) is None:
            raise _AlreadyShadowedError(w.where())
        for a in asks:
            rec = self.record(p, a)
            if a.batch_task is not None:  # queued in an earlier run: its run ends it
                end_task(self.conn, rec, runs, a.batch_task)
                if a.calls:
                    self.tally.settled += 1
            else:
                write_task(self.conn, rec, runs)
        costs = self.engine_costs(p)
        for arm in p.arms:
            for row in self.review_rows(p, arm, contra1, costs.get(arm.engine, (Decimal(0), ()))):
                write_review(self.conn, row, packet=p.packet, packet_id=w.packet_id, at=now)
        self.conn.commit()

    def not_run(
        self, p: _Pass, reason: str, *, paused: Mapping[str, Sequence[str]] | None = None
    ) -> None:
        """A pass no model could be asked about: its state is written with the reason and a fallback review per candidate and engine, so that it is
        not selected again and the arms' comparison counts it as what it was."""
        w = p.work
        now = self.clock()
        for arm_engine in p.engines:
            arm = Arm(
                engine=arm_engine,
                level=ENGINE_LEVEL[arm_engine],
                status=STATUS_FALLBACK,
                reason=reason,
            )
            p.arms.append(arm)
        state = StateRecord(
            work=w,
            created_at=now,
            package_version=mcp_package.VERSION,
            package_hash=p.package.hash,
            elapsed_ms=0,
            slices=self.slices_of(p),
            blocking=tuple(p.package.blocking),
            flags=tuple(p.package.flags),
            model_status=self.model_status(p, ()),
            research_status={},
            agents=[],
            contradictions=[],
            candidates=self.candidate_rows(p),
            final=self.final_row(p, paused or {}, not_run=reason),
        )
        if write_state(self.conn, state) is None:
            raise _AlreadyShadowedError(w.where())
        for arm in p.arms:
            for row in self.review_rows(p, arm, (), (Decimal(0), ())):
                write_review(self.conn, row, packet=p.packet, packet_id=w.packet_id, at=now)
        self.conn.commit()
        self.tally.not_run += 1
        log.info(
            "orchestrator.not_run",
            extra={"fixture": w.fixture_id, "pass": w.pass_kind, "code": reason.split(":")[0]},
        )

    # -- the rows --------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def slices_of(p: _Pass) -> list[dict[str, Any]]:
        """The slices of the package, as ``ai.match_runs.slices`` keeps them: ALL of them, in the order of ``SLICE_NAMES``, whether an agent read one or not.
        The audit ``slice_known`` derives the package again and holds the state to every slice of it; phase 3 stored the Match Agent's alone, and the audit
        counted that as a violation of every state of the shadow (found in phase 4, with the Statistics Agent's slice stored beside it)."""
        if not p.slices:
            return [p.slice_.measures()]
        return [p.slices[name].measures() for name in SLICE_NAMES if name in p.slices]

    @staticmethod
    def model_status(p: _Pass, contra1: Sequence[Contradiction]) -> dict[str, Any]:
        """``ai.match_runs.model_status``: the code version and the orchestrator's, and - with the Statistics Agent on - what it was asked and what the
        detector found for corners and cards, apart from goals and result (the figures Gate B reads about C05 and C08 per family)."""
        out: dict[str, Any] = {"code": model_code_version(), "orchestrator": VERSION}
        if p.stats_on:
            asked = stats.asked_keys(p.naming)
            out["stats"] = {
                "version": stats.VERSION,
                "naming": p.naming.version,
                "asked": list(asked),
                "note": p.stats_note,
                "contra": {
                    "fired": contra.tally_by_family(contra1, naming=p.naming),
                    "coverage": contra.coverage_by_family(p.package.document, naming=p.naming),
                },
            }
        return out

    @staticmethod
    def agent_row(a: Asked) -> dict[str, Any]:
        ident = a.identity
        return {
            "agent": ident.agent,
            "version": ident.agent_version,
            "task": a.task_kind,
            "model": ident.model,
            "answered_by": a.model,
            "status": a.status,
            "error": a.error,
            "cost_usd": str(a.cost),
            "idem": a.key[:12],
            "calls": a.calls,
            "reused": a.reused,
            "shared": a.shared,
        }

    def candidate_rows(self, p: _Pass) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in p.naming.named:
            c = n.candidate
            out.append(
                {
                    "candidate": n.key,
                    "family": n.family,
                    "market": c.market_key,
                    "selection": c.selection,
                    "line": str(c.line),
                    "odds": None if c.odds is None else str(c.odds),
                    "p_model": str(c.p_model),
                    "p_market": None if c.p_market is None else str(c.p_market),
                    "edge": None if c.edge is None else str(c.edge),
                    "ev": None if c.ev is None else str(c.ev),
                }
            )
        for c, why in p.naming.left_out:
            out.append(
                {
                    "candidate": None,
                    "left_out": why,
                    "market": c.market_key,
                    "selection": c.selection,
                    "line": str(c.line),
                }
            )
        return out

    def final_row(
        self, p: _Pass, paused: Mapping[str, Sequence[str]], *, not_run: str | None = None
    ) -> dict[str, Any]:
        engines: dict[str, Any] = {}
        for arm in p.arms:
            row: dict[str, Any] = {"status": arm.status, "level": arm.level}
            if arm.reason:
                row["reason"] = arm.reason
            if arm.view is not None:
                row["view"] = arm.view.measures()
            if arm.finals:
                row["verdicts"] = {
                    k: f"{f.verdict}:{f.confidence}"
                    for k, f in sorted(arm.finals.items(), key=lambda kv: (len(kv[0]), kv[0]))
                }
            if arm.escalated:
                row["escalated"] = dict(arm.escalated)
            if arm.skipped_escalation:
                row["escalation_skipped"] = dict(arm.skipped_escalation)
            if arm.engine in paused:
                row["paused"] = list(paused[arm.engine])
            engines[arm.engine] = row
        return {
            "version": VERSION,
            "status": "not_run" if not_run else "ran",
            "reason": not_run,
            "engines": engines,
            "too_late": p.too_late,
            "router": router.VERSION,
            "params": router.params_hash(),
        }

    def engine_costs(self, p: _Pass) -> dict[str, tuple[Decimal, tuple[int, ...]]]:
        """Each engine's cost and usage ids: the tasks it stands on, a task shared by several engines split between them."""
        users: dict[str, list[str]] = {}
        for arm in p.arms:
            for a in arm.users:
                users.setdefault(a.key, [])
                if arm.engine not in users[a.key]:
                    users[a.key].append(arm.engine)
        exact: list[Decimal] = []
        ids_of: list[list[int]] = []
        for arm in p.arms:
            total, ids = Decimal(0), []
            for a in arm.users:
                total += a.cost / len(users[a.key])
                ids.extend(a.usage_ids)
            exact.append(total)
            ids_of.append(ids)
        # What the engines cost adds up to what the run paid: settled on the running total, not engine by engine.
        return {arm.engine: (cost, distinct(ids)) for arm, cost, ids in zip(p.arms, settle_costs(exact), ids_of, strict=True)}

    def review_rows(
        self,
        p: _Pass,
        arm: Arm,
        contra1: Sequence[Contradiction],
        cost: tuple[Decimal, tuple[int, ...]],
    ) -> list[ReviewRow]:
        rows: list[ReviewRow] = []
        named = p.naming.named
        shares = split_cost(cost[0], len(named))
        labels = {
            "council": prompt_labels.COUNCIL_VERSION,
            "match_context": prompt_labels.MATCH_CONTEXT_VERSION,
            "match_assess": prompt_labels.MATCH_ASSESS_VERSION,
        }
        if p.stats_on:
            labels["stats_assess"] = prompt_labels.STATS_ASSESS_VERSION
        version = engine_version(arm.engine, with_stats=p.stats_on)
        for share, n in zip(shares, named, strict=True):
            c = n.candidate
            scores = p.candidates.scores.get(c.key, Scores())
            fair, minimum = fair_and_minimum(c)
            final = arm.finals.get(n.key)
            touching = sorted({k.code for k in contra1 if n.key in k.candidates})
            base: dict[str, Any] = {
                "version": VERSION,
                "engine": arm.engine,
                "arm": arm.engine,
                "contract": "cd-v1",
                "candidate": n.key,
                "round": 1,
                "prompts": labels,
                "contradictions": touching,
                "fair_odds": None if fair is None else float(fair),
                "minimum_playable_odds": None if minimum is None else float(minimum),
                "research_ask_ignored": len(p.ignored_asks),
            }
            if arm.engine in WITH_MATCH:
                base["assessment"] = {
                    label: stances[n.key]
                    for label, stances in sorted(p.stances.items())
                    if n.key in stances
                }
            view_hash = arm.view.hash if arm.view is not None else None
            if final is not None:
                evidence, paths = refs_in({"refs": final.refs})
                out = base | {
                    "verdict": final.verdict,
                    "confidence_level": final.confidence,
                    "confidence": str(confidence_value(final.confidence)),
                    "drivers": final.drivers,
                    "risks": final.risks,
                    "refs": final.refs,
                    "model": final.model,
                    "paths": paths,
                }
                if final.changed:
                    out["changes"] = final.changed
                if final.escalation:
                    out["escalation"] = {
                        "rule": final.escalation,
                        "model": final.model,
                        "replaced": final.replaced,
                    }
                elif n.key in arm.skipped_escalation:
                    out["escalation"] = {
                        "rule": arm.escalated.get(n.key),
                        "skipped": arm.skipped_escalation[n.key],
                    }
                rows.append(
                    ReviewRow(
                        candidate=c,
                        scores=scores,
                        engine=arm.engine,
                        version=version,
                        decision=final.verdict,
                        confidence=confidence_value(final.confidence),
                        output=out,
                        status=STATUS_OK,
                        input_hash=review_hash(
                            arm.engine,
                            view_hash,
                            final.model,
                            arm.opus.key if arm.opus is not None else None,
                        ),
                        provider="anthropic",
                        model=final.model,
                        usage_ids=cost[1],
                        cost=share,
                        evidence_ids=tuple(evidence),
                    )
                )
                continue
            status = arm.status if arm.status != STATUS_OK else STATUS_FALLBACK
            reason = arm.reason or "no_verdict_for_the_candidate"
            out = base | {
                "verdict": "ABSTAIN",
                "confidence": "0",
                "reason": reason,
                "status": status,
            }
            if n.key in arm.skipped_escalation:
                out["escalation"] = {
                    "rule": arm.escalated.get(n.key),
                    "skipped": arm.skipped_escalation[n.key],
                }
            rows.append(
                ReviewRow(
                    candidate=c,
                    scores=scores,
                    engine=arm.engine,
                    version=version,
                    decision="ABSTAIN",
                    confidence=Decimal(0),
                    output=out,
                    status=status,
                    input_hash=review_hash(arm.engine, p.package.hash, view_hash, reason),
                    provider=None,
                    model=None,
                    error=reason,
                    usage_ids=cost[1],
                    cost=share,
                )
            )
        return rows


class _AlreadyShadowedError(Exception):
    """Another worker wrote the shadow of this pass first: nothing of this one is kept."""


# -- the door --------------------------------------------------------------------------------------------------------------------------


def run(
    conn: psycopg.Connection[Any],
    settings: AiSettings,
    *,
    at: datetime,
    limit: int = 20,
    max_seconds: float = 240.0,
    provider: LlmProvider | None = None,
    transport: Any = None,
    ledger: usage.UsageLedger | None = None,
    slots: runtime.Slots | None = None,
    circuit: runtime.Circuit | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    batch_client: BatchClient | None = None,
) -> Report:
    """Shadow the sample of the matches whose passes are pending (see the module's docstring). NEVER raises.

    ``at`` is the moment of the cycle (timezone-aware). ``limit`` bounds the passes looked at, ``max_seconds`` the time the run starts new passes in.
    ``provider`` injects a provider for every model (tests: ``FakeProvider``); ``transport`` an HTTP transport for the real one; ``ledger`` the
    ledger of the calls; ``slots`` and ``circuit`` default to the process-wide ones. ``monotonic`` and ``sleep`` are the clock and the wait of the run,
    injectable so that a test neither waits nor depends on the machine. ``batch_client`` injects the Message Batches API client of the Batch
    calendar (tests: ``FakeBatches``); None = the LAB workspace's own, from the settings."""
    if not settings.orchestrate:
        return Report(skipped="off")
    runner = _Runner(
        conn,
        settings,
        at=at,
        limit=limit,
        max_seconds=max_seconds,
        provider=provider,
        transport=transport,
        ledger=ledger,
        slots=slots,
        circuit=circuit,
        monotonic=monotonic,
        sleep=sleep,
        batch_client=batch_client,
    )
    try:
        runner.close_lapsed()
        runner.go()
    except Exception as exc:  # the run never raises into the job: what could not be done is counted, and the pipeline goes on
        runner.tally.failed_open += 1
        log.warning("orchestrator.run_failed", extra={"code": type(exc).__name__})
        try:
            if not conn.closed:
                conn.rollback()
        except Exception:  # nothing to undo on a connection that is gone
            pass
    return runner.tally.report()


__all__ = [
    "CONFIDENCE",
    "ENGINE_VERSION",
    "STATE_VERSION",
    "VERSION",
    "Report",
    "process_circuit",
    "process_slots",
    "run",
]
