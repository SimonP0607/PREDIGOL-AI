"""``battery-v4`` in the LAB (IA-065, plan piece AD-A03): the owner's signature of the protocol, the asks, their collection and the row of the gate.

    sign     THE OWNER'S ACTION: the protocol ``AD-A03`` with the ceiling of invalid answers the owner decided (0 %, IA-140, 17-nov-2026) as a row
             of ``ai.feature_gates`` (``battery``, ``decided_by = 'owner'``, ``passed = false``, ``kind = 'protocol-signature'``). Without
             ``confirm_owner``: a preview, nothing written. Nobody else signs: no code path writes it but this one, and only when asked so.
    plan     what a measurement would ask and cost (by the prices measured on 15-nov-2026 and by the queue's own estimate), and whether the LAB can pay
    submit   what is due as ONE batch of the LAB - refused without a valid signature (the protocol and the corpus as they were signed), above
             ``max_usd`` (US$ 3 by default) or above what the LAB may still spend
    collect  the answers; with every ask closed, the rule (``fbi.ai.battery.v4.assess``) and ONE new row of the gate ``battery`` with the method
             of v4 and the signature it was measured under - whatever the verdict
    status   the signature in force, and the runs of the corpus

Nothing of ``battery-v3`` is read or written here: its rows (row 18 included) stay as they are; a v4 row is appended after them, and like every row
of the gate it is the newest that speaks. The signature row is the newest until the first measurement: it says ``passed = false`` (nothing opens).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import httpx
import psycopg
from psycopg.rows import dict_row

from fbi.ai import budget_v3, gates, lab
from fbi.ai.batch import BatchClient, BatchQueue, Task, estimate_cost, poll
from fbi.ai.battery import offline, v4
from fbi.ai.battery.evaluate import Outcome
from fbi.ai.battery.run import CLOSED_WITH_SUMMARY, OPEN, Held, held_from
from fbi.ai.config import AiSettings
from fbi.ai.usage import UsageLedger, with_effort
from fbi.research import protocol

GATE: Final = "battery"
SIGNATURE_KIND: Final = "protocol-signature"
MEASUREMENT_KIND: Final = "measurement"
LAB_KIND: Final = "battery-v4"
MAX_USD: Final = Decimal(3)
"""The ceiling of one execution (the order of IA-065): a round that the estimate puts above it is not sent."""

SIGNATURE_SQL: Final = """
SELECT id, at, evidence FROM ai.feature_gates
 WHERE gate = 'battery' AND decided_by = 'owner' AND evidence ->> 'kind' = 'protocol-signature' AND evidence ->> 'battery' = %(version)s
 ORDER BY at DESC, id DESC LIMIT 1
"""
ITEMS_SQL: Final = """
SELECT i.id, i.status, i.error, i.model, i.context, u.cost_usd
  FROM ai.batch_items i LEFT JOIN ai.usage u ON u.id = i.usage_id
 WHERE i.purpose = 'other' AND i.prompt_version = %(version)s AND i.context ->> 'run' = %(run)s AND i.status <> 'abandoned'
 ORDER BY i.id
"""


def _h(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def run_id(target: str, *, suffix: str = "") -> str:
    return f"{v4.VERSION}:{target}:{v4.requests_hash(target)[:12]}" + (f":{suffix}" if suffix else "")


# ── the signature ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Signature:
    row: int
    at: datetime
    params: v4.Params
    protocol_fingerprint: str
    corpus_hash: str

    def problems(self) -> list[str]:
        """Why this signature does not cover the battery in force - or nothing."""
        out = []
        if self.params.invalid_max != v4.OWNER_INVALID_MAX:
            out.append(f"the signature allows {self.params.invalid_max:.1%} of invalid answers; the owner decided "
                       f"{v4.OWNER_INVALID_MAX:.0%} on {v4.OWNER_INVALID_MAX_DECISION['decided_on']} (IA-140)")
        if self.protocol_fingerprint != protocol.fingerprint(protocol.require(v4.PROTOCOL_KEY)):
            out.append("the protocol AD-A03 is not the one that was signed")
        if self.corpus_hash != v4.corpus_hash():
            out.append("the corpus of battery-v4 is not the one that was signed")
        return out

    def as_json(self) -> dict[str, Any]:
        return {"row": self.row, "at": self.at.isoformat(), "params": self.params.as_json(), "protocol_fingerprint": self.protocol_fingerprint,
                "corpus_hash": self.corpus_hash, "problems": self.problems()}


def signature_evidence(params: v4.Params, *, reason: str) -> dict[str, Any]:
    return {"kind": SIGNATURE_KIND, "battery": v4.VERSION, "protocol": protocol.stamp(v4.PROTOCOL_KEY), "params": params.as_json(),
            "params_fingerprint": params.fingerprint(), "corpus_hash": v4.corpus_hash(), "reason": reason.strip()[:500],
            "owner_decision": dict(v4.OWNER_INVALID_MAX_DECISION),
            "note": "firma del dueño del protocolo de battery-v4: no es una medición; la fila 18 (battery-v3) no cambia"}


def signature(conn: psycopg.Connection[Any]) -> Signature | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SIGNATURE_SQL, {"version": v4.VERSION})
        row = cur.fetchone()
    if row is None:
        return None
    ev = row["evidence"]
    return Signature(int(row["id"]), row["at"], v4.Params(**ev["params"]), str(ev["protocol"]["fingerprint"]), str(ev["corpus_hash"]))


def sign(conn: psycopg.Connection[Any], *, invalid_max: float, reason: str | None, confirm_owner: bool, at: datetime) -> dict[str, Any]:
    """THE OWNER'S ACTION. Without ``confirm_owner``: what would be written, and nothing written. With it: one row appended (the caller commits)."""
    try:
        params = v4.Params(invalid_max=invalid_max)
    except ValueError as exc:
        return {"error": f"{exc} (nothing was written)"}
    if params.invalid_max != v4.OWNER_INVALID_MAX:
        return {"error": f"invalid_max {params.invalid_max} is not the owner's decision: {v4.OWNER_INVALID_MAX:.0%} of invalid answers "
                         f"(IA-140, {v4.OWNER_INVALID_MAX_DECISION['decided_on']}); sign with --invalid-max 0 (nothing was written)"}
    if not reason or not reason.strip():
        return {"error": "sign needs --reason \"...\" (nothing was written)"}
    evidence = signature_evidence(params, reason=reason)
    if not confirm_owner:
        return {"preview": True, "written": None, "would_write": {"table": "ai.feature_gates", "gate": GATE, "passed": False,
                                                                     "decided_by": "owner", "evidence": evidence},
                "lines": ["VISTA PREVIA (sin --confirm-owner): no se ha escrito nada.",
                          f"Protocolo {v4.PROTOCOL_KEY} ({protocol.require(v4.PROTOCOL_KEY).version}), umbral de salidas inválidas "
                          f"{params.invalid_max:.1%}. Para firmarlo, el dueño repite el comando con --confirm-owner."]}
    row = gates.record_gate(conn, gate=GATE, passed=False, evidence=evidence, at=at, decided_by="owner")
    return {"preview": False, "written": row, "evidence": evidence}


# ── plan and submit ──────────────────────────────────────────────────────────────────────────────────────────────

def task_of(target: str, ask: str, base: str, case: v4.Case4 | None, run: str, stage: int) -> Task:
    return Task(purpose="other", tier=v4.tier_of(target, base), request=v4.request_for(target, base, case), prompt_version=v4.VERSION,
                input_hash=_h(v4.VERSION, run, ask), lab=True, typical_output=v4.typical_output(target),
                context={"lab": LAB_KIND, "run": run, "target": target, "base": base, "case": None if case is None else case.id, "ask": ask,
                         "stage": stage})


def load_held(conn: psycopg.Connection[Any], run: str) -> Held:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ITEMS_SQL, {"version": v4.VERSION, "run": run})
        return held_from([dict(r) for r in cur.fetchall()])


def submit(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, targets: Sequence[str] = v4.TARGETS, suffix: str = "",
           max_usd: Decimal = MAX_USD, ledger: UsageLedger | None = None, client: BatchClient | None = None,
           transport: httpx.BaseTransport | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Send what is due as ONE batch of the LAB, or say why not. ``dry_run`` is the plan: it needs no signature and sends nothing."""
    sig = signature(conn)
    params = v4.DEFAULT if sig is None else sig.params
    stop = (["the protocol AD-A03 has not been signed by the owner (scripts/ia_battery.py v4-sign ... --confirm-owner)"]
            if sig is None else sig.problems())
    tiers = sorted({v4.tier_of(t, b) for t in targets for b in v4.bases_of(t)})
    stop += lab.blockers(settings, tiers)
    tasks: list[Task] = []
    plan: dict[str, Any] = {}
    for t in targets:
        rid = run_id(t, suffix=suffix)
        held = load_held(conn, rid)
        asks = v4.due(t, held.asks, held.known, params)
        tasks += [task_of(t, k, b, c, rid, int(k.rsplit("/", 1)[1].split(".")[0])) for k, b, c in asks]
        plan[t] = {"run": rid, "due": len(asks), "already": len(held.known), "open": len(held.open)}
    estimate = Decimal(0)
    for task in tasks:
        tm = settings.tier(task.tier, lab=True)
        if tm is not None:
            estimate += estimate_cost(tm.model, with_effort(task.request, task.tier), typical_output=task.typical_output, at=at)
    room = budget_v3.lab_day(conn, at=at, settings=settings)
    out: dict[str, Any] = {"version": v4.VERSION, "signature": None if sig is None else sig.as_json(), "params": params.as_json(),
                           "targets": plan, "asks": len(tasks), "estimate_usd": str(estimate.quantize(Decimal("0.01"))),
                           "measured_prices": v4.planned_cost(params), "max_usd": str(max_usd),
                           "lab_remaining_usd": str(room.remaining.quantize(Decimal("0.01"))), "lab_day": room.reason}
    if estimate > max_usd:
        stop.append(f"the round is estimated at US$ {estimate:.2f}, above the ceiling of US$ {max_usd} of one execution: "
                    "send fewer targets at a time (--targets)")
    if not room.can_spend or estimate > room.remaining:
        stop.append("the LAB cannot pay for this round now (see lab_day and lab_remaining_usd)")
    if dry_run:
        return out | {"submitted": 0, "dry_run": True, "would_stop": stop}
    if stop:
        return out | {"submitted": 0, "blockers": stop}
    if not tasks:
        return out | {"submitted": 0, "nothing_due": True}
    queue = BatchQueue(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    admissions = [queue.add(t) for t in tasks]
    if any(not a.pending for a in admissions):
        conn.rollback()
        return out | {"submitted": 0, "refused": dict(queue.refused), "blockers": ["the queue refused part of the round: nothing was sent"]}
    report = queue.flush()
    return out | {"submitted": report.sent, "failed": report.failed, "error": report.error}


# ── what an answer becomes ───────────────────────────────────────────────────────────────────────────────────────

def summarise(r: Any, ctx: Mapping[str, Any]) -> dict[str, Any]:
    """The summary of one answer of v4 as ``lab.settle_lab`` keeps it: the targets of v3 by v3's own reducers (the same reading of an answer),
    the quarantined extractor's by ``v4.quarantine_outcome``."""
    target = str(ctx["target"])
    if r.result is None:
        code = "invalid_output" if r.error is None else r.error.code
        return Outcome("refused" if code == "refused" else "invalid").as_json() | {"error": code}
    if target in v4.QUARANTINE:
        subject = str(ctx.get("case") or ctx["base"])
        return v4.quarantine_outcome(target, subject, r.result.data) | {"stop_reason": r.result.extra.get("stop_reason")}
    from fbi.ai.battery.settle import summarise as v3_summarise

    return v3_summarise(r, ctx)


# ── collect ──────────────────────────────────────────────────────────────────────────────────────────────────────

def collect(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, targets: Sequence[str] = v4.TARGETS, suffix: str = "",
            ledger: UsageLedger | None = None, client: BatchClient | None = None, transport: httpx.BaseTransport | None = None,
            record: bool = True) -> dict[str, Any]:
    """Take the answers and, with every ask of every target closed, the rule and one row of the gate (whatever the verdict). The caller commits."""
    sig = signature(conn)
    if sig is None or sig.problems():
        return {"state": "unsigned", "blockers": ["no valid signature of the protocol AD-A03: a measurement is never judged without it"]}
    polled = poll(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    runs = {t: run_id(t, suffix=suffix) for t in targets}
    helds = {t: load_held(conn, runs[t]) for t in targets}
    assessments = {t: v4.assess(t, helds[t].asks, sig.params) for t in targets}
    out: dict[str, Any] = {"runs": runs, "poll_errors": polled.errors, "signature": sig.as_json(),
                           "targets": {t: a.as_json() | {"cost_usd": str(helds[t].cost), "open": len(helds[t].open)} for t, a in assessments.items()}}
    if any(h.open for h in helds.values()):
        return out | {"state": "waiting"}
    v3_targets = [t for t in targets if t not in v4.QUARANTINE]
    offline_report = offline.run(v3_targets) if v3_targets else None
    verdict = v4.overall(assessments.values(), offline_report is None or offline_report.ok)
    out["verdict"] = verdict
    if verdict == "INCOMPLETA":
        return out | {"state": "incomplete", "next": "submit: the repetitions of the suspects are due, or an ask came back without an answer"}
    out["state"] = "ended"
    if record and set(targets) == set(v4.TARGETS):
        evidence = evidence_of(assessments, helds, runs, sig, offline_report)
        out["gate_id"] = lab._record_if_new(conn, gate=GATE, passed=verdict == "PASA", evidence=evidence, at=at)
    return out


def evidence_of(assessments: Mapping[str, v4.Assessment4], helds: Mapping[str, Held], runs: Mapping[str, str], sig: Signature,
                offline_report: offline.OfflineReport | None) -> dict[str, Any]:
    """The row of a measurement of v4: the method, the signature it was judged under and every ask's outcome, so anyone can recompute it."""
    from fbi.ai.battery import corpus

    def covers(t: str) -> dict[str, Any]:
        if t in v4.QUARANTINE:
            return {"target": t, "agent": "quarantine_extractor", "prompts": ["extract-v4"], "contract": "claim-v2", "tiers": ["bulk"]}
        return corpus.target(t).covers()

    return {
        "battery": v4.VERSION, "kind": MEASUREMENT_KIND, "method": "battery-v4: zero obeyed/invented/refused, invalid <= signed ceiling, "
        "moved by one-sided Fisher tests corrected by Holm", "params": sig.params.as_json(), "signature_row": sig.row,
        "protocol": protocol.stamp(v4.PROTOCOL_KEY), "corpus_hash": v4.corpus_hash(), "target_list": list(assessments),
        "covers": [covers(t) for t in assessments],
        "models": sorted({m for h in helds.values() for m in h.models}),
        "targets": {t: {"run": runs[t], "requests_hash": v4.requests_hash(t), "models": list(helds[t].models), "cost_usd": str(helds[t].cost),
                        "assessment": a.as_json(), **({"agent": covers(t)["agent"], "prompts": covers(t)["prompts"]})}
                    for t, a in assessments.items()},
        "offline": None if offline_report is None else offline_report.as_json(),
        "asks": {t: {k: o.as_json() for k, o in sorted(helds[t].asks.items())} for t in assessments}}


def status(conn: psycopg.Connection[Any], *, suffix: str = "") -> dict[str, Any]:
    sig = signature(conn)
    runs: dict[str, Any] = {}
    for t in v4.TARGETS:
        rid = run_id(t, suffix=suffix)
        held = load_held(conn, rid)
        runs[t] = {"run": rid, "asks": held.items, "open": len(held.open), "cost_usd": str(held.cost)}
    return {"version": v4.VERSION, "signature": None if sig is None else sig.as_json(), "corpus_hash": v4.corpus_hash(),
            "protocol": protocol.stamp(v4.PROTOCOL_KEY), "runs": runs, "planned": v4.planned_cost(v4.DEFAULT if sig is None else sig.params)}


__all__ = ["CLOSED_WITH_SUMMARY", "GATE", "MAX_USD", "OPEN", "Signature", "collect", "load_held", "run_id", "sign", "signature", "status",
           "submit", "summarise", "task_of"]
