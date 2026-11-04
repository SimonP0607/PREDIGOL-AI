"""The Message Batches API for what can wait (Plan Maestro IA, section 29): the same request, answered later, at half the price.

WHAT GOES IN A BATCH (the plan's table): the ``first`` pass, and the ``pre`` pass when the match starts in four hours or more
(``FBI_AI_BATCH_MIN_LEAD_MINUTES``); never the ``final`` pass, never a task with less margin, never an arbitration that answers an
answer. A task that cannot wait is asked in real time exactly as before - this module only adds a second, cheaper route, and every
refusal of it (a switch, a gate, a budget, a failed batch) sends the task back to the first one.

THE ROUTE of a task:

1. ``BatchQueue.add(task)`` - the cycle's decision. It records the task as an item of today's batch (``ai.batch_items``, status
   ``submitting``) BEFORE anything leaves the machine, and says what became of it: ``queued`` (to be sent), ``in_flight`` (an
   identical task is already open: nothing is paid twice), ``done`` (an identical task was already answered) or ``refused`` (and why).
2. ``BatchQueue.flush()`` - at the end of the cycle, one batch per workspace is created at the provider; the items become
   ``submitted`` and the batch ``in_progress`` with the provider's id.
3. ``poll()`` - the worker job ``ai_batch_poll`` (every 5 minutes) asks for the batches that ended and takes their results: each is
   decoded, PRICED AT HALF, recorded in the ledger (``ai.usage``: ``batch_id`` and ``custom_id``, unique) and handed to the handler of its
   purpose (``register``), which validates and stores the answer exactly as the real-time path would. ``errored``, ``canceled`` and
   ``expired`` cost nothing and are recorded as such; the next pass asks again in real time if the clock allows.

IDEMPOTENCY: ``custom_id`` is a hash of (purpose, prompt version, model, input hash, tier, workspace). The database allows ONE open
item per ``custom_id`` and ONE ledger row per (batch, ``custom_id``), so the same task is never paid twice - not by two cycles, not by a
retry of a result that was half processed, not by a batch followed by a real-time call (the handler stores the answer under the input
hash that the real-time path reuses).

MONEY: an open item RESERVES its estimated cost in the budget until its result arrives (``fbi.ai.usage.reserved_by_day``): a day's
batches cannot exceed it. The estimate is the input tokens of the request plus the typical output of the purpose, priced at half.

FAILURE: a batch that cannot be created (an outage, a refused request, a spent limit) abandons its items; the next cycle asks
again, and after two failures of the same task in 24 hours it is asked in real time. The quantitative pipeline never waits for a
batch: the combined review is the rules' until the model's answer arrives, and then the next cycle combines the two.

The key never appears here: ``batches_for`` hands the client over and the ledger records only the workspace's and the key's NAME.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx
import psycopg
import structlog
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai import gates
from fbi.ai.config import AiSettings, Tier
from fbi.ai.packet import canonical
from fbi.ai.pricing import approx_tokens, token_cost
from fbi.ai.providers import batches_for
from fbi.ai.providers.anthropic import BatchResult, read_message
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError
from fbi.ai.usage import Purpose, UsageLedger, budget, lab_may_spend, with_effort, with_switches

log = structlog.get_logger(__name__)

BATCH_PASSES = frozenset({"first", "pre"})
"""The passes whose tasks can wait (the ``final`` pass, after the line-ups, never does)."""
BATCH_ROLES = frozenset({"candidate", "pick"})
"""The reviews that can wait: a candidate's. A watch and the arbitration of a contradiction answer something that just happened."""
DEADLINE_MARGIN = timedelta(minutes=60)
"""An answer that arrives later than this before the kick-off is still stored (it was paid for) but is marked ``late``."""
MAX_FAILED_ATTEMPTS = 2
"""A task whose batch failed this many times in ``ATTEMPT_WINDOW`` is not sent again: it is asked in real time."""
ATTEMPT_WINDOW = timedelta(hours=24)
TYPICAL_OUTPUT_ROWS = 100
TYPICAL_OUTPUT_DAYS = 14
UNSENT_AFTER = timedelta(minutes=30)
"""A batch still ``submitting`` this long after it was opened, with no cycle running, was never sent (the cycle that opened it stopped)."""
CYCLE_LOCK = 7310073
"""The advisory lock an analysis cycle holds from its start to its end (``fbi.ai.cycle`` takes it; it is defined here because the cycle imports this
module and not the other way round). While it is held the cycle is still recording tasks and sends them in one go at its end, so a batch that is
``submitting`` is not a batch that was never sent, however old it is: the first cycle of the Bogotá day lasted 61 minutes on 31 Oct 2026 and 49
minutes on 1 Nov, and the poll abandoned the 120 tasks it had recorded (plan IA, phase 0)."""
CYCLE_RUNNING_SQL = ("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted "
                     "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                     "AND classid = 0 AND objid = %s::oid AND objsubid = 1)")
"""How a session sees that another holds ``CYCLE_LOCK``: a one-key advisory lock (``pg_try_advisory_lock(bigint)``) is listed with the
key's high half in ``classid`` (0: the key is under 2^32), its low half in ``objid`` and ``objsubid`` 1 (the two-key form has 2), in this
database only."""
OPEN = ("submitting", "submitted")
ANSWERED = ("succeeded", "invalid", "late")
FAILED = ("errored", "canceled", "expired")

Handler = Callable[[psycopg.Connection[Any], "Resolved"], None]
_HANDLERS: dict[str, Handler] = {}
_MODULES = ("fbi.ai.review", "fbi.ai.lab")
"""The modules that register the handlers: imported on first use, so the worker's poll never depends on who imported what."""

ITEMS_SQL = """
SELECT id, custom_id, purpose, tier, model, fixture_id, input_hash, prompt_version, est_cost_usd, deadline_at, context
  FROM ai.batch_items WHERE batch_id = %(batch)s AND status = 'submitted' ORDER BY id
"""

SENDABLE_SQL = """
SELECT i.id, i.custom_id, i.model, i.tier, i.purpose, i.context, b.id AS batch_id, b.workspace, b.key_label, b.kind
  FROM ai.batch_items i JOIN ai.batches b ON b.id = i.batch_id
 WHERE b.status = 'submitting' AND b.provider = 'anthropic' AND b.created_at = %(at)s AND i.status = 'submitting'
 ORDER BY b.id, i.id
"""

OPEN_BATCHES_SQL = """
SELECT id FROM ai.batches WHERE status IN ('in_progress', 'canceling') AND processed_at IS NULL AND batch_ref IS NOT NULL
 ORDER BY created_at, id LIMIT %(limit)s
"""

LOCK_BATCH_SQL = """
SELECT id, batch_ref, workspace, key_label, kind, status, created_at, expires_at FROM ai.batches
 WHERE id = %(id)s AND status IN ('in_progress', 'canceling') AND processed_at IS NULL FOR UPDATE SKIP LOCKED
"""

KNOWN_SQL = """
SELECT status FROM ai.batch_items WHERE custom_id = %(cid)s AND status IN ('submitting', 'submitted', 'succeeded', 'invalid', 'late')
 ORDER BY (status IN ('submitting', 'submitted')) DESC, id DESC LIMIT 1
"""

ATTEMPTS_SQL = """
SELECT count(*) FROM ai.batch_items
 WHERE custom_id = %(cid)s AND created_at >= %(since)s
   AND (status IN ('errored', 'canceled', 'expired') OR (status = 'abandoned' AND error IS NOT NULL AND error <> 'never_sent'))
"""

TYPICAL_OUTPUT_SQL = """
SELECT avg(output_tokens) FROM (
    SELECT output_tokens FROM ai.usage WHERE purpose = %(purpose)s AND model = %(model)s AND status = 'ok'
       AND at >= %(since)s AND batch_id IS NULL ORDER BY at DESC LIMIT %(rows)s) x
"""

INSERT_ITEM_SQL = """
INSERT INTO ai.batch_items (batch_id, custom_id, purpose, tier, model, fixture_id, input_hash, prompt_version, est_cost_usd,
                            deadline_at, status, created_at, context)
VALUES (%(batch)s, %(cid)s, %(purpose)s, %(tier)s, %(model)s, %(fixture)s, %(hash)s, %(version)s, %(est)s, %(deadline)s,
        'submitting', %(at)s, %(context)s)
ON CONFLICT (custom_id) WHERE status IN ('submitting', 'submitted') DO NOTHING RETURNING id
"""


# ── the task and what becomes of it ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    """One model call that can wait. ``request`` is the request as the real-time path would send it (before the tier's effort and the
    switches of Phase 0, which the queue adds); ``context`` is what the handler needs to validate and store the answer when it arrives
    - never a prompt, never a key."""

    purpose: Purpose
    tier: Tier
    request: JsonRequest
    prompt_version: str
    input_hash: str
    fixture_id: int | None = None
    deadline_at: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)
    lab: bool = False
    agent: str | None = None
    run_id: int | None = None
    typical_output: int | None = None
    """The tokens the answer is expected to write, for the reservation of its cost. None = what the purpose has written lately in real time
    (an experiment of the LAB, whose purpose is ``other``, says its own: the history of ``other`` is not its answer's size)."""


Status = Literal["queued", "in_flight", "done", "refused"]


@dataclass(frozen=True)
class Admission:
    """What the queue did with a task. ``queued``, ``in_flight`` and ``done`` all mean the answer is NOT to be asked for again."""

    status: Status
    custom_id: str
    reason: str | None = None
    est_cost: Decimal = Decimal(0)

    @property
    def pending(self) -> bool:
        return self.status != "refused"


@dataclass(frozen=True)
class Resolved:
    """A result taken from a batch, for the handler of its purpose."""

    item: dict[str, Any]
    """The ``ai.batch_items`` row: id, custom_id, purpose, tier, model, fixture_id, input_hash, prompt_version, deadline_at, context."""
    result: LlmResult | None
    """The decoded answer; None when the model answered but not in a form that could be read (``error`` says why)."""
    error: ProviderError | None
    usage_id: int | None
    cost: Decimal
    at: datetime
    late: bool
    batch_id: int


def register(purpose: str, handler: Handler) -> None:
    """The handler that validates and stores the answers of a purpose. Called when its module is imported."""
    _HANDLERS[purpose] = handler


def handler_for(purpose: str) -> Handler | None:
    if purpose not in _HANDLERS:
        for module in _MODULES:
            importlib.import_module(module)
    return _HANDLERS.get(purpose)


class BatchClient(Protocol):
    def item(self, custom_id: str, model: str, request: JsonRequest) -> dict[str, Any]: ...
    def create(self, items: list[dict[str, Any]]) -> dict[str, Any]: ...
    def get(self, batch_ref: str) -> dict[str, Any]: ...
    def results(self, batch_ref: str) -> list[BatchResult]: ...


# ── pure helpers ─────────────────────────────────────────────────────────────────────────────────────────────────

def custom_id_of(task: Task, model: str) -> str:
    """The task's idempotency key, in the shape the API asks (``^[a-zA-Z0-9_-]{1,64}$``): the same task - the same purpose, prompt
    version, model, input and tier, for the same workspace - always has the same one."""
    key = canonical([task.purpose, task.prompt_version, model, task.input_hash, task.tier, task.lab, task.agent])
    return hashlib.sha256(key.encode()).hexdigest()[:48]


def decode_flags(params: dict[str, Any], schema_name: str) -> dict[str, Any]:
    """How to read the answer of a request built as ``params``: structured outputs or a tool call, and whether the system block asked
    for the one-hour cache entry (which prices a cache write that arrives without the breakdown)."""
    native = "tools" not in params and bool((params.get("output_config") or {}).get("format"))
    system = params.get("system")
    long_ttl = isinstance(system, list) and any(
        isinstance(b, dict) and (b.get("cache_control") or {}).get("ttl") == "1h" for b in system)
    return {"schema_name": schema_name, "native": native, "long_ttl": long_ttl}


def estimate_cost(model: str, request: JsonRequest, *, typical_output: int | None, at: datetime) -> Decimal:
    """What a request will cost in a batch, for the reservation: its input tokens (counted the way the planning estimate does) and the
    typical output of its purpose (its ``max_tokens`` at most), at half price, with no cache credit - the prudent assumption."""
    text = request.system + request.user_text + json.dumps(request.schema)
    tokens_in = approx_tokens(text, "anthropic")
    out = request.max_tokens // 2 if typical_output is None else min(typical_output, request.max_tokens)
    return token_cost("anthropic", model, input_tokens=tokens_in, output_tokens=out, batch=True, at=at)


def _stamp(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── the queue of one cycle ───────────────────────────────────────────────────────────────────────────────────────

@dataclass
class FlushReport:
    batches: int = 0
    sent: int = 0
    failed: int = 0
    orphans: int = 0
    error: str | None = None


class BatchQueue:
    """The tasks of ONE cycle that go to the Message Batches API. ``add`` records them; ``flush`` (at the end of the cycle) sends
    them. The cycle commits per match and rolls back a match that fails: what is recorded in the database is what is sent, and the
    request bodies the queue holds for a task whose record was rolled back are never sent."""

    def __init__(self, conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime,
                 ledger: UsageLedger | None = None, client: BatchClient | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.conn = conn
        self.settings = settings
        self.at = at
        self.ledger = ledger or UsageLedger()
        self._client = client
        self._transport = transport
        self._pending: dict[str, tuple[Task, str, JsonRequest]] = {}
        self._on: dict[str, bool] = {}
        self.refused: dict[str, int] = {}
        """Why tasks were sent back to real time in this cycle: reason -> number."""

    # routing --------------------------------------------------------------------------------------------------
    def routes(self, *, tier: Tier, pass_kind: str, kickoff_at: datetime, role: str = "candidate",
               lab: bool = False) -> bool:
        """Whether a task of this pass, with this much time before the match, goes to a batch: the plan's table, then the owner's
        switch and the evidence of the ``batch`` gate for the tier's model."""
        if role not in BATCH_ROLES or pass_kind not in BATCH_PASSES:
            return False
        if kickoff_at - self.at < timedelta(minutes=self.settings.batch_min_lead_minutes):
            return False
        tm = self.settings.tier(tier, lab=lab)
        if tm is None or tm.provider != "anthropic":
            return False
        if tm.model not in self._on:
            self._on[tm.model] = gates.enabled(self.conn, self.settings, "batch", model=tm.model)
        return self._on[tm.model]

    # admission ------------------------------------------------------------------------------------------------
    def add(self, task: Task) -> Admission:
        tm = self.settings.tier(task.tier, lab=task.lab)
        if tm is None or tm.provider != "anthropic":
            return self._refuse(task, "", "no_model")
        cid = custom_id_of(task, tm.model)
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(KNOWN_SQL, {"cid": cid})
            known = cur.fetchone()
            if known is not None:
                return Admission("in_flight" if known[0] in OPEN else "done", cid)
            cur.execute(ATTEMPTS_SQL, {"cid": cid, "since": self.at - ATTEMPT_WINDOW})
            failed = cur.fetchone()
        if failed is not None and int(failed[0]) >= MAX_FAILED_ATTEMPTS:
            return self._refuse(task, cid, "attempts")
        request = with_switches(self.conn, self.settings, with_effort(task.request, task.tier), tm.model)
        typical = task.typical_output if task.typical_output is not None else self._typical_output(task.purpose, tm.model)
        estimate = estimate_cost(tm.model, request, typical_output=typical, at=self.at)
        why = self._unaffordable(task, estimate)
        if why is not None:
            return self._refuse(task, cid, why, estimate)
        batch_id = self._batch_id(task.lab)
        context = dict(task.context) | {"schema_name": request.schema_name} | ({"layout": "shared"} if request.shared else {})
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(INSERT_ITEM_SQL, {
                "batch": batch_id, "cid": cid, "purpose": task.purpose, "tier": task.tier, "model": tm.model,
                "fixture": task.fixture_id, "hash": task.input_hash, "version": task.prompt_version, "est": estimate,
                "deadline": task.deadline_at, "at": self.at, "context": Jsonb(context)})
            row = cur.fetchone()
        if row is None:  # another open item took the key between the look and the insert
            return Admission("in_flight", cid)
        self._pending[cid] = (task, tm.model, request)
        return Admission("queued", cid, est_cost=estimate)

    def _refuse(self, task: Task, cid: str, reason: str, estimate: Decimal = Decimal(0)) -> Admission:
        self.refused[reason] = self.refused.get(reason, 0) + 1
        return Admission("refused", cid, reason, estimate)

    def _typical_output(self, purpose: str, model: str) -> int | None:
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(TYPICAL_OUTPUT_SQL, {"purpose": purpose, "model": model, "rows": TYPICAL_OUTPUT_ROWS,
                                             "since": self.at - timedelta(days=TYPICAL_OUTPUT_DAYS)})
            row = cur.fetchone()
        return None if row is None or row[0] is None else int(row[0])

    def _unaffordable(self, task: Task, estimate: Decimal) -> str | None:
        """Why the budget cannot hold this task now (None = it can): the day's state must allow the tier and the reservation must fit
        under the day's cap (the LAB: its own envelope)."""
        if task.lab:
            if not lab_may_spend(self.conn, self.settings, self.at):
                return "lab_budget"
            if gates.enabled(self.conn, self.settings, "budget_v3"):
                from fbi.ai import budget_v3

                if budget_v3.lab_day(self.conn, at=self.at, settings=self.settings).remaining < estimate:
                    return "lab_budget"
            return None
        b = budget(self.conn, at=self.at, settings=self.settings)
        if not b.allows(task.tier):
            return "budget_state"
        if b.spent_today + estimate > b.cap:
            return "budget_cap"
        return None

    def _batch_id(self, lab: bool) -> int:
        """Today's batch of a workspace, still being filled: the one opened at this cycle's moment, or a new one. Looked up by what
        identifies it - never remembered by id, because the cycle may roll back the match that opened it."""
        workspace, key_label = self.settings.labelled(lab=lab)
        kind = "lab" if lab else "production"
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT id FROM ai.batches WHERE status = 'submitting' AND provider = 'anthropic' AND workspace = %s "
                        "AND key_label = %s AND kind = %s AND created_at = %s ORDER BY id DESC LIMIT 1",
                        (workspace, key_label, kind, self.at))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO ai.batches (provider, workspace, key_label, kind, status, created_at, n_items) "
                            "VALUES ('anthropic', %s, %s, %s, 'submitting', %s, 0) RETURNING id",
                            (workspace, key_label, kind, self.at))
                row = cur.fetchone()
        assert row is not None
        return int(row[0])

    # sending --------------------------------------------------------------------------------------------------
    def _batches(self, lab: bool) -> BatchClient | None:
        return self._client if self._client is not None else batches_for(self.settings, lab=lab, transport=self._transport)

    def flush(self) -> FlushReport:
        """Send what the cycle recorded: one batch per workspace. A batch that cannot be created abandons its items (they are asked
        again by the next cycle, or in real time after two failures). Commits as it goes: the provider's id is noted at once."""
        report = FlushReport()
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(SENDABLE_SQL, {"at": self.at})
            rows = [dict(r) for r in cur.fetchall()]
        groups: dict[int, list[dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(int(r["batch_id"]), []).append(r)
        for batch_id, group in groups.items():
            mine = [r for r in group if r["custom_id"] in self._pending]
            report.orphans += len(group) - len(mine)
            if len(group) > len(mine):
                self._close_items([int(r["id"]) for r in group if r["custom_id"] not in self._pending], "abandoned",
                                  "never_sent")
            if not mine:
                self._close_batch(batch_id, "abandoned", "never_sent")
                self.conn.commit()
                continue
            self._send(batch_id, mine, report)
            self.conn.commit()
        self._pending.clear()
        return report

    def _send(self, batch_id: int, items: list[dict[str, Any]], report: FlushReport) -> None:
        lab = items[0]["kind"] == "lab"
        workspace, key_label = str(items[0]["workspace"]), str(items[0]["key_label"])
        ids = [int(r["id"]) for r in items]
        client = self._batches(lab)
        if client is None:
            self._fail(batch_id, ids, "create_failed: no_client", report)
            return
        bodies: list[dict[str, Any]] = []
        flags: dict[int, dict[str, Any]] = {}
        for r in items:
            _task, model, request = self._pending[str(r["custom_id"])]
            body = client.item(str(r["custom_id"]), model, request)
            bodies.append(body)
            flags[int(r["id"])] = decode_flags(body["params"], request.schema_name)
        try:
            made = client.create(bodies)
        except ProviderError as exc:
            if exc.code == "limit_reached":
                self.ledger.record_limit_hit(at=self.at, provider="anthropic", workspace=workspace, key_label=key_label,
                                             kind=exc.limit_kind or "workspace_limit", http_status=exc.status or 0,
                                             request_id=exc.request_id, purpose="batch")
            self._fail(batch_id, ids, f"create_failed: {exc.code}", report)
            return
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("UPDATE ai.batches SET batch_ref = %s, status = 'in_progress', submitted_at = %s, expires_at = %s, "
                        "n_items = %s WHERE id = %s",
                        (str(made["id"]), self.at, _stamp(made.get("expires_at")), len(items), batch_id))
            for item_id, flag in flags.items():
                cur.execute("UPDATE ai.batch_items SET status = 'submitted', context = context || %s WHERE id = %s",
                            (Jsonb({"decode": flag}), item_id))
        report.batches += 1
        report.sent += len(items)

    def _fail(self, batch_id: int, item_ids: list[int], error: str, report: FlushReport) -> None:
        self._close_items(item_ids, "abandoned", error)
        self._close_batch(batch_id, "failed", error)
        report.failed += len(item_ids)
        report.error = error

    def _close_items(self, item_ids: list[int], status: str, error: str) -> None:
        if not item_ids:
            return
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("UPDATE ai.batch_items SET status = %s, resolved_at = %s, error = %s WHERE id = ANY(%s) "
                        "AND status = 'submitting'", (status, self.at, error[:300], item_ids))

    def _close_batch(self, batch_id: int, status: str, error: str) -> None:
        with self.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("UPDATE ai.batches SET status = %s, processed_at = %s, error = %s WHERE id = %s",
                        (status, self.at, error[:300], batch_id))


def cycle_is_running(conn: psycopg.Connection[Any]) -> bool:
    """Whether an analysis cycle holds its lock right now, in any session (this one too). It only LOOKS at the lock: taking it to find out
    would make a cycle that starts in that instant believe another one is running and skip its work."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CYCLE_RUNNING_SQL, (CYCLE_LOCK,))
        row = cur.fetchone()
    return bool(row and row[0])


def abandon_unsent(conn: psycopg.Connection[Any], *, at: datetime, before: datetime | None = None) -> int:
    """Batches and items still ``submitting`` from an earlier cycle: they were recorded but never sent (the cycle stopped), so they are
    abandoned and the task is free to be asked again. The cycle calls it at its start, under its lock - nothing else is sending then;
    the poll calls it for those older than ``UNSENT_AFTER``, and only when no cycle is running (``cycle_is_running``): a cycle that is
    still running sends what it recorded at its end, however long it takes. Returns the number of items."""
    cutoff = before if before is not None else at - UNSENT_AFTER
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.batch_items i SET status = 'abandoned', resolved_at = %s, error = 'never_sent' "
                    "FROM ai.batches b WHERE b.id = i.batch_id AND b.status = 'submitting' AND b.created_at < %s "
                    "AND i.status = 'submitting'", (at, cutoff))
        items = cur.rowcount
        cur.execute("UPDATE ai.batches SET status = 'abandoned', processed_at = %s, error = 'never_sent' "
                    "WHERE status = 'submitting' AND created_at < %s", (at, cutoff))
    return max(items, 0)


# ── taking the results ───────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class PollReport:
    batches: int = 0
    ended: int = 0
    waiting: int = 0
    items: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    cost_usd: Decimal = Decimal(0)
    errors: list[str] = field(default_factory=list)
    abandoned: int = 0
    """Items recorded and never sent (the cycle that recorded them stopped) that this poll abandoned."""
    cycle_running: bool = False
    """A cycle was running, so the poll left the unsent batches alone: they are the cycle's own, to be sent when it ends."""

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def poll(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, ledger: UsageLedger | None = None,
         client: BatchClient | None = None, transport: httpx.BaseTransport | None = None, limit: int = 20) -> PollReport:
    """The worker job ``ai_batch_poll``: ask the provider about every open batch and take the results of those that ended. It works
    on whatever is open whatever the switches say: rolling Batch back (``FBI_AI_BATCH=0``) stops new batches, never the collection of
    those already paid for. Never raises for a provider's failure: it is noted on the batch and tried again at the next poll."""
    report = PollReport()
    ledger = ledger or UsageLedger()
    if cycle_is_running(conn):  # its batches are still 'submitting' because it has not reached its flush, not because it never sent them
        report.cycle_running = True
    else:
        report.abandoned = abandon_unsent(conn, at=at)
    conn.commit()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(OPEN_BATCHES_SQL, {"limit": limit})
        ids = [int(r[0]) for r in cur.fetchall()]
    conn.commit()
    for batch_id in ids:
        with conn.cursor(row_factory=dict_row) as cur:  # one batch at a time, locked while it is processed
            cur.execute(LOCK_BATCH_SQL, {"id": batch_id})
            row = cur.fetchone()
        if row is None:  # another poll has it, or it ended meanwhile
            conn.commit()
            continue
        b = dict(row)
        report.batches += 1
        lab = b["kind"] in ("lab", "probe")
        api = client if client is not None else batches_for(settings, lab=lab, transport=transport)
        if api is None:
            report.errors.append(f"batch {b['id']}: no key for workspace {b['workspace']}")
            conn.rollback()
            continue
        try:
            _poll_one(conn, b, api, report, at=at, ledger=ledger)
        except Exception as exc:  # one batch must not stop the others
            conn.rollback()
            report.errors.append(f"batch {b['id']}: {type(exc).__name__}: {exc}"[:200])
            log.error("ai.batch.poll_failed", batch=b["id"], error=f"{type(exc).__name__}: {exc}"[:200])
        conn.commit()
    return report


def _poll_one(conn: psycopg.Connection[Any], b: dict[str, Any], api: BatchClient, report: PollReport, *, at: datetime,
              ledger: UsageLedger) -> None:
    ref = str(b["batch_ref"])
    with conn.cursor(row_factory=tuple_row) as cur:
        try:
            info = api.get(ref)
        except ProviderError as exc:
            cur.execute("UPDATE ai.batches SET last_polled_at = %s, error = %s WHERE id = %s",
                        (at, f"poll_failed: {exc.code}"[:300], b["id"]))
            report.errors.append(f"batch {b['id']}: {exc.code}")
            return
        status = str(info.get("processing_status") or "")
        cur.execute("UPDATE ai.batches SET last_polled_at = %s, status = %s, error = NULL WHERE id = %s",
                    (at, "canceling" if status == "canceling" else "in_progress" if status != "ended" else b["status"],
                     b["id"]))
    if status != "ended":
        report.waiting += 1
        return
    try:
        results = api.results(ref)
    except ProviderError as exc:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("UPDATE ai.batches SET error = %s WHERE id = %s", (f"results_failed: {exc.code}"[:300], b["id"]))
        report.errors.append(f"batch {b['id']}: results {exc.code}")
        return
    by_id = {r.custom_id: r for r in results}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ITEMS_SQL, {"batch": b["id"]})
        items = [dict(r) for r in cur.fetchall()]
    counts: dict[str, int] = {}
    cost = Decimal(0)
    for item in items:
        outcome, spent = _resolve(conn, b, item, by_id.get(str(item["custom_id"])), at=at, ledger=ledger)
        counts[outcome] = counts.get(outcome, 0) + 1
        cost += spent
        report.bump(outcome)
    unknown = len(set(by_id) - {str(i["custom_id"]) for i in items})
    if unknown:
        counts["unknown"] = unknown
        report.bump("unknown", unknown)
    report.items += len(items)
    report.cost_usd += cost
    report.ended += 1
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.batches SET status = 'ended', ended_at = %s, processed_at = %s, counts = %s WHERE id = %s",
                    (_stamp(info.get("ended_at")) or at, at, Jsonb(counts | {"cost_usd": str(cost)}), b["id"]))


def _record(conn: psycopg.Connection[Any], ledger: UsageLedger, b: dict[str, Any], item: dict[str, Any], *, at: datetime,
            usage: Any, cost: Decimal, status: str, error: str | None, request_id: str | None) -> int:
    """The ledger row of a result. The database refuses a second one for the same (batch, custom_id): a result that was half processed
    by an earlier poll finds its row instead of paying again."""
    try:
        with conn.transaction():
            return ledger.record(
                at=at, purpose=item["purpose"], tier=item["tier"], provider="anthropic", model=item["model"], usage=usage,
                cost=cost, status=status, prompt_version=item["prompt_version"], fixture_id=item["fixture_id"], error=error,
                input_hash=item["input_hash"], request_id=request_id, workspace=b["workspace"], key_label=b["key_label"],
                batch_id=int(b["id"]), custom_id=item["custom_id"],
                run_id=(item["context"] or {}).get("run_id"), agent=(item["context"] or {}).get("agent"))
    except UniqueViolation:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT id, cost_usd FROM ai.usage WHERE batch_id = %s AND custom_id = %s",
                        (b["id"], item["custom_id"]))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])


def _resolve(conn: psycopg.Connection[Any], b: dict[str, Any], item: dict[str, Any], result: BatchResult | None, *,
             at: datetime, ledger: UsageLedger) -> tuple[str, Decimal]:
    """One result: priced, recorded, handed to its purpose's handler, and the item closed. Returns (outcome, cost)."""
    item_id = int(item["id"])
    deadline = item["deadline_at"]
    late = deadline is not None and at > deadline
    if result is None or result.kind != "succeeded" or result.message is None:
        if result is None:
            kind, detail = "errored", "no_result"
        elif result.kind == "succeeded":  # a success without its message
            kind, detail = "errored", "no_message"
        else:
            kind, detail = result.kind, result.error_type or result.kind
        uid = _record(conn, ledger, b, item, at=at, usage=None, cost=Decimal(0),
                      status="timeout" if kind == "expired" else "failed", error=f"batch_{kind}: {detail}"[:300],
                      request_id=None)
        _close(conn, item_id, kind, at=at, usage_id=uid, error=detail)
        return kind, Decimal(0)
    decode = (item["context"] or {}).get("decode") or {}
    request = JsonRequest(system="", user="", schema={}, schema_name=str(decode.get("schema_name") or ""))
    answer: LlmResult | None = None
    problem: ProviderError | None = None
    usage: LlmUsage | None
    try:
        answer = read_message(result.message, request, str(item["model"]), native=bool(decode.get("native")), latency_ms=0,
                              request_id=str(result.message.get("id") or "") or None,
                              long_ttl_asked=bool(decode.get("long_ttl")))
        usage = answer.usage
    except ProviderError as exc:
        problem, usage = exc, exc.usage
    except (KeyError, TypeError, ValueError, AttributeError):
        problem, usage = ProviderError("invalid_output", "the batch's message could not be read"), None
    cost = Decimal(0) if usage is None else token_cost(
        "anthropic", str(item["model"]), input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        cached_tokens=usage.cached_tokens, cache_write_5m_tokens=usage.cache_write_5m_tokens,
        cache_write_1h_tokens=usage.cache_write_1h_tokens, batch=True, at=at)
    status = "ok" if problem is None else "invalid_output" if problem.code == "invalid_output" \
        else "refused" if problem.code == "refused" else "failed"
    uid = _record(conn, ledger, b, item, at=at, usage=usage, cost=cost, status=status,
                  error=None if problem is None else f"{problem.code}: {problem}", request_id=str(result.message.get("id") or "") or None)
    outcome = "invalid" if problem is not None else "late" if late else "succeeded"
    error: str | None = None if problem is None else problem.code
    handler = handler_for(str(item["purpose"]))
    if handler is None:
        outcome, error = "invalid", f"no_handler: {item['purpose']}"
    else:
        resolved = Resolved(item, answer, problem, uid, cost, at, late, int(b["id"]))
        try:
            with conn.transaction():
                handler(conn, resolved)
        except Exception as exc:  # the answer was paid for and recorded; its storing failed: it is not asked again
            outcome, error = "invalid", f"handler_failed: {type(exc).__name__}"
            log.error("ai.batch.handler_failed", purpose=item["purpose"], custom_id=item["custom_id"],
                      error=f"{type(exc).__name__}: {exc}"[:200])
    _close(conn, item_id, outcome, at=at, usage_id=uid, error=error)
    return outcome, cost


def _close(conn: psycopg.Connection[Any], item_id: int, status: str, *, at: datetime, usage_id: int | None,
           error: str | None) -> None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.batch_items SET status = %s, resolved_at = %s, usage_id = %s, error = %s WHERE id = %s",
                    (status, at, usage_id, None if error is None else error[:300], item_id))


# ── what is open now ─────────────────────────────────────────────────────────────────────────────────────────────

def open_counts(conn: psycopg.Connection[Any], purpose: str) -> dict[str, int]:
    """The items of a purpose still open (sent or about to be), in total and by tier: the cycle counts them against the day's
    allowance, because their reviews are not in ``ai.pick_reviews`` yet."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT tier, count(*) FROM ai.batch_items WHERE purpose = %s AND status IN ('submitting', 'submitted') "
                    "GROUP BY tier", (purpose,))
        return {str(r[0]): int(r[1]) for r in cur.fetchall()}
