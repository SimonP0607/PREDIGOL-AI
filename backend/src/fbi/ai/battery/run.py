"""Running the battery in the LAB: the asks, the Message Batches route, the collection of the answers and the ``battery`` gate.

Every ask is the LAB workspace's - its own key, its own name in the ledger, inside its own envelope (``FBI_AI_LAB_MONTHLY_BUDGET_USD``) -
and goes through the Message Batches route (half price), the way ``fbi.ai.lab`` sends its experiments: all of a round or none of it,
paid for (or refused) before the first request, and asking again finds what is already sent instead of paying for it again. A request is
PINNED: production's switches neither add nor take away what is being measured.

    submit   the first round (every base ``CONTROLS`` times clean, every case once) and, once it is in, the repetitions of the suspects
    collect  take the answers; with every ask closed, apply the rule (``fbi.ai.battery.evaluate``) and record the ``battery`` gate

A MEASUREMENT (a ``run``) is named by the version of the battery, the target, a digest of every request of the target and, to repeat it
on purpose, a suffix. A new prompt, schema or case is therefore another run; the same corpus asked again is the same run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from fbi.ai import budget_v3, gates, lab
from fbi.ai.batch import BatchClient, BatchQueue, Task, estimate_cost, poll
from fbi.ai.battery import AGAIN, CONTROLS, TARGETS, VERSION, corpus, evaluate, offline
from fbi.ai.battery.evaluate import Assessment, Outcome
from fbi.ai.battery.model import Case
from fbi.ai.config import AiSettings
from fbi.ai.usage import UsageLedger, with_effort

GATE = "battery"
OPEN = ("submitting", "submitted")
CLOSED_WITH_SUMMARY = ("succeeded", "late", "invalid")


def _h(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def run_id(target: str, *, native: bool = False, suffix: str = "") -> str:
    """The measurement of a target (see the module's docstring)."""
    return f"{VERSION}:{target}:{corpus.requests_hash(target, native=native)[:12]}" + (f":{suffix}" if suffix else "")


@dataclass(frozen=True, slots=True)
class Ask:
    """One request of the battery."""

    target: str
    base: str
    case: Case | None
    stage: int
    n: int

    @property
    def subject(self) -> str:
        return evaluate.base_subject(self.base) if self.case is None else evaluate.case_subject(self.case.id)

    @property
    def key(self) -> str:
        return evaluate.key(self.subject, self.stage, self.n)


def first_round(target: str, *, controls: int = CONTROLS) -> list[Ask]:
    """Every base clean ``controls`` times and every case once."""
    spec = corpus.target(target)
    asks = [Ask(target, base, None, 1, n) for base in spec.bases for n in range(controls)]
    return asks + [Ask(target, c.base, c, 1, 0) for c in corpus.cases_of(target)]


def repetitions(target: str, case_ids: Sequence[str], *, again: int = AGAIN) -> list[Ask]:
    return [Ask(target, c.base, c, 2, n) for cid in case_ids if (c := corpus.case_of(cid)).target == target for n in range(again)]


def task_of(ask: Ask, run: str, *, native: bool = False) -> Task:
    spec = corpus.target(ask.target)
    return Task(
        purpose="other", tier=spec.tier, request=corpus.request_for(ask.target, ask.base, ask.case, native=native),
        prompt_version=VERSION, input_hash=_h(VERSION, run, ask.key), lab=True, typical_output=spec.typical_output,
        context={"lab": "battery", "run": run, "target": ask.target, "base": ask.base, "case": None if ask.case is None else ask.case.id,
                 "ask": ask.key, "stage": ask.stage})


# ── what the ledger holds of a run ───────────────────────────────────────────────────────────────────────────────

ITEMS_SQL = """
SELECT i.id, i.status, i.error, i.model, i.context, u.cost_usd
  FROM ai.batch_items i LEFT JOIN ai.usage u ON u.id = i.usage_id
 WHERE i.purpose = 'other' AND i.prompt_version = %(version)s AND i.context ->> 'run' = %(run)s AND i.status <> 'abandoned'
 ORDER BY i.id
"""


@dataclass(frozen=True, slots=True)
class Held:
    """What the ledger holds of one run."""

    asks: dict[str, Outcome] = field(default_factory=dict)
    """The asks that closed (a closed ask without an answer is an ``error`` outcome: it has to be asked again)."""
    open: frozenset[str] = frozenset()
    """The asks still on their way."""
    models: tuple[str, ...] = ()
    cost: Decimal = Decimal(0)
    items: int = 0

    @property
    def known(self) -> frozenset[str]:
        """The asks that need no new request: on their way, or answered."""
        return self.open | {k for k, o in self.asks.items() if o.state != "error"}


def load_held(conn: psycopg.Connection[Any], run: str) -> Held:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ITEMS_SQL, {"version": VERSION, "run": run})
        rows = [dict(r) for r in cur.fetchall()]
    return held_from(rows)


def held_from(rows: Sequence[Mapping[str, Any]]) -> Held:
    """The newest item of each ask decides it (an ask that came back as an error is asked again, in a new item)."""
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        latest[str((row["context"] or {}).get("ask"))] = row
    asks: dict[str, Outcome] = {}
    open_: set[str] = set()
    for ask, row in latest.items():
        summary = (row["context"] or {}).get("result")
        if row["status"] in OPEN:
            open_.add(ask)
        elif row["status"] in CLOSED_WITH_SUMMARY and isinstance(summary, dict):
            asks[ask] = Outcome.from_json(summary)
        else:
            asks[ask] = Outcome("error")
    return Held(asks, frozenset(open_), tuple(sorted({str(r["model"]) for r in rows if r["model"]})),
                sum((Decimal(r["cost_usd"] or 0) for r in rows), Decimal(0)), len(rows))


def assess_run(target: str, held: Held) -> Assessment:
    return evaluate.assess(target, list(corpus.target(target).bases.values()), corpus.cases_of(target), held.asks)


def due(target: str, held: Held) -> list[Ask]:
    """The asks of a target that have not been made: the first round, and the repetitions of the suspects - whom the rule names only
    once the first round is whole (``evaluate.assess`` names nobody before)."""
    asks = first_round(target) + repetitions(target, assess_run(target, held).again_due)
    return [ask for ask in asks if ask.key not in held.known]


# ── submit ───────────────────────────────────────────────────────────────────────────────────────────────────────

def submit(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, targets: Sequence[str] = TARGETS, native: bool = False,
           suffix: str = "", ledger: UsageLedger | None = None, client: BatchClient | None = None,
           transport: httpx.BaseTransport | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Send what is due of the battery as ONE batch of the LAB, all or nothing: the whole cost is estimated first and compared with what
    the LAB may still spend, and nothing is sent if it does not fit - or if the queue refuses any ask."""
    specs = [corpus.target(t) for t in targets]
    stop = lab.blockers(settings, sorted({s.tier for s in specs}))
    if stop:
        return {"submitted": 0, "blockers": stop}
    tasks: list[Task] = []
    plan: dict[str, Any] = {}
    for spec in specs:
        rid = run_id(spec.name, native=native, suffix=suffix)
        held = load_held(conn, rid)
        asks = due(spec.name, held)
        tasks += [task_of(a, rid, native=native) for a in asks]
        plan[spec.name] = {"run": rid, "due": len(asks), "already": len(held.known), "open": len(held.open)}
    estimate = Decimal(0)
    for t in tasks:
        tm = settings.tier(t.tier, lab=True)
        assert tm is not None  # blockers() said every tier has a model
        # The request as the queue estimates it (with its effort). Today the effort does not change the estimate; this keeps the plan from
        # drifting from what the queue reserves if it ever does.
        estimate += estimate_cost(tm.model, with_effort(t.request, t.tier), typical_output=t.typical_output, at=at)
    room = budget_v3.lab_day(conn, at=at, settings=settings)
    out: dict[str, Any] = {"targets": plan, "asks": len(tasks), "estimate_usd": str(estimate.quantize(Decimal("0.01"))),
                           "lab_remaining_usd": str(room.remaining.quantize(Decimal("0.01"))), "lab_day": room.reason}
    if not tasks:
        return out | {"submitted": 0, "nothing_due": True}
    if not room.can_spend or estimate > room.remaining:
        return out | {"submitted": 0, "blockers": ["the LAB cannot pay for this round now (see lab_day and lab_remaining_usd)"]}
    if dry_run:
        return out | {"submitted": 0, "dry_run": True}
    queue = BatchQueue(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    admissions = [queue.add(t) for t in tasks]
    if any(not a.pending for a in admissions):
        conn.rollback()
        why = ("the queue refused part of the round (see refused): nothing was sent"
               + (". An ask has already failed twice in the last day and is not sent a third time until that day has passed;"
                  " to measure again on purpose, use a suffix" if "attempts" in queue.refused else ""))
        return out | {"submitted": 0, "refused": dict(queue.refused), "blockers": [why]}
    states: dict[str, int] = {}
    for a in admissions:
        states[a.status] = states.get(a.status, 0) + 1
    report = queue.flush()
    return out | {"submitted": report.sent, "states": states, "failed": report.failed, "error": report.error}


# ── collect ──────────────────────────────────────────────────────────────────────────────────────────────────────

def evidence_of(assessments: Mapping[str, Assessment], helds: Mapping[str, Held], runs: Mapping[str, str], offline_report: offline.OfflineReport,
                *, native: bool) -> dict[str, Any]:
    """The evidence of the gate: the measurement itself - every ask's outcome - with what it was measured on, so that anyone can
    recompute the decision (``evaluate.assess`` over ``asks``, with the corpus of ``corpus_hash``)."""
    return {
        "battery": VERSION, "native": native, "corpus_hash": corpus.corpus_hash(),
        "models": sorted({m for h in helds.values() for m in h.models}),
        "rule": {"controls": CONTROLS, "again": AGAIN, "stable_min": evaluate.stable_min(CONTROLS)},
        "targets": {t: {"prompt": corpus.target(t).prompt, "run": runs[t], "requests_hash": corpus.requests_hash(t, native=native),
                        "models": list(helds[t].models), "cost_usd": str(helds[t].cost), "assessment": assessments[t].as_json()}
                    for t in assessments},
        "offline": offline_report.as_json(),
        "asks": {t: {k: o.as_json() for k, o in sorted(helds[t].asks.items())} for t in assessments}}


def collect(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, targets: Sequence[str] = TARGETS, native: bool = False,
            suffix: str = "", ledger: UsageLedger | None = None, client: BatchClient | None = None,
            transport: httpx.BaseTransport | None = None, record: bool = True) -> dict[str, Any]:
    """Take the answers (the poll is idempotent: the worker may have taken them already) and, when every ask of every target is closed
    and no repetition is due, apply the rule and record the ``battery`` gate - whatever the verdict. Nothing is recorded while an ask
    is on its way, or when not every target of the battery was collected (the gate speaks for all of them). The connection is the
    caller's, and so is the commit."""
    polled = poll(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    runs = {t: run_id(t, native=native, suffix=suffix) for t in targets}
    helds = {t: load_held(conn, runs[t]) for t in targets}
    out: dict[str, Any] = {"runs": runs, "poll_errors": polled.errors, "targets": {}}
    if not all(h.items for h in helds.values()):
        out["targets"] = {t: {"asks": h.items} for t, h in helds.items()}
        return out | {"state": "nothing_submitted"}
    assessments = {t: assess_run(t, helds[t]) for t in targets}
    for t, a in assessments.items():
        out["targets"][t] = {"verdict": a.verdict, "asks": helds[t].items, "open": len(helds[t].open), "cost_usd": str(helds[t].cost),
                             "unstable_bases": list(a.unstable), "confirmed": list(a.confirmed), "again_due": list(a.again_due),
                             "pending": len(a.pending), "errors": len(a.errors)}
    if any(h.open for h in helds.values()):
        return out | {"state": "waiting", "open": sum(len(h.open) for h in helds.values())}
    offline_report = offline.run(targets, native=native)
    out["offline"] = offline_report.as_json()
    verdict = evaluate.overall(assessments.values(), offline_report.ok)
    out["verdict"] = verdict
    if verdict == "INCOMPLETA":
        return out | {"state": "incomplete", "next": "submit: some asks are not sent yet (the repetitions of the suspects) or came back without an answer"}
    out["state"] = "ended"
    if record and set(targets) == set(TARGETS):
        evidence = evidence_of(assessments, helds, runs, offline_report, native=native)
        out["gate_id"] = lab._record_if_new(conn, gate=GATE, passed=verdict == "PASA", evidence=evidence, at=at)
    return out


# ── status ───────────────────────────────────────────────────────────────────────────────────────────────────────

def stale(evidence: Mapping[str, Any]) -> list[str]:
    """Why a recorded measurement does not speak for the corpus and the prompts in force now - or nothing, when it does."""
    native = bool(evidence.get("native"))
    reasons: list[str] = []
    if evidence.get("battery") != VERSION:
        reasons.append(f"measured with {evidence.get('battery')}, the battery is {VERSION}")
    if evidence.get("corpus_hash") != corpus.corpus_hash():
        reasons.append("the cases or the bases are not the ones that were measured")
    measured = evidence.get("targets") or {}
    for t in TARGETS:
        if t not in measured:
            reasons.append(f"the target {t} was not measured")
        elif measured[t].get("requests_hash") != corpus.requests_hash(t, native=native):
            reasons.append(f"the requests of {t} (its prompt, schema or layout) are not the ones that were measured")
    return reasons


def status(conn: psycopg.Connection[Any], *, at: datetime, native: bool = False, suffix: str = "") -> dict[str, Any]:
    """The gate, whether its newest evidence still speaks for what is in force, and the runs of today's corpus."""
    state = gates.gate_state(conn, GATE)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT evidence FROM ai.feature_gates WHERE gate = %s ORDER BY at DESC, id DESC LIMIT 1", (GATE,))
        row = cur.fetchone()
    reasons = ["no measurement has been recorded"] if row is None else stale(row["evidence"])
    runs: dict[str, Any] = {}
    for t in TARGETS:
        rid = run_id(t, native=native, suffix=suffix)
        held = load_held(conn, rid)
        counts: dict[str, int] = {}
        for o in held.asks.values():
            counts[o.state] = counts.get(o.state, 0) + 1
        runs[t] = {"run": rid, "asks": held.items, "open": len(held.open), "by_state": counts, "cost_usd": str(held.cost)}
    return {"at": at.isoformat(), "gate": state.as_json(), "fresh": not reasons, "stale": reasons, "runs": runs,
            "corpus_hash": corpus.corpus_hash(), "version": VERSION}
