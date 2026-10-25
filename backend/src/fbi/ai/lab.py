"""LAB experiments (Plan Maestro IA, Phase 0): what the evidence of the gates is made of.

* The PROBES - the prompt cache writes and reads, structured outputs answer inside their schema, and the Message Batches API does
  both of those inside a batch - open the ``batch`` gate (per model) and say whether the cache works for a model.
* The EQUIVALENCE test - the same stored review inputs asked as they are asked today (twice), with structured outputs and with the
  match's common block first - opens ``native_schema`` and ``cache_layout`` when the verdict changes no more than repeating the same
  call changes it (plan, gate A: «cambio de veredicto con las optimizaciones ≤ el de repetir la misma llamada, sobre ≥ 200 paquetes
  guardados»).

Every call here is the LAB workspace's: its own key, its own name in the ledger, inside its own envelope
(``FBI_AI_LAB_MONTHLY_BUDGET_USD``). Production's key is never read and no pick, probability or threshold is touched. What cannot be
paid for says so and stops (``blockers``): nothing here half-runs. The work goes through the Message Batches route (half price); the
answers are taken by the poll that takes every batch (``ai_batch_poll``) and handed to ``settle_lab``, registered for the purpose
``other`` - so collecting never depends on who submitted, and a re-run on the same day finds what is already paid for instead of
paying it again. A request is PINNED: production's switches neither add nor take away what is being measured, and the LAB never
changes the model of an experiment (a tier the budget would lower is a probe that did not run, not a probe of another model).

The rules of a gate are written down here, before any data (see ``assess``), and the evidence a gate keeps is the measurement itself -
every input's verdicts - so that anyone can recompute the decision. A gate row is appended only when it says something the newest row
does not; the rows are never edited, so the history of attempts is the table itself."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, ValidationError

from fbi.ai import budget_v3, gates
from fbi.ai.batch import BatchClient, BatchQueue, Resolved, Task, estimate_cost, poll, register
from fbi.ai.config import AiSettings, Tier
from fbi.ai.packet import Packet, load_packet
from fbi.ai.providers.base import JsonRequest, LlmProvider, LlmUsage
from fbi.ai.review import Candidate, answer_review, review_request, signals_for
from fbi.ai.usage import UsageLedger, call_json, with_effort
from fbi.ai.views import review_view

PROBE_CACHE_VERSION = "probe-cache-v1"
PROBE_SCHEMA_VERSION = "probe-schema-v1"
PROBE_BATCH_VERSION = "probe-batch-v1"
EQUIVALENCE_VERSION = "equiv-v1"

PROBE_TYPICAL_OUTPUT = 40
"""Tokens a probe's answer is expected to write (one word and a number): the reservation of its cost."""
EQUIVALENCE_TYPICAL_OUTPUT = 1000
"""Tokens a review's answer is expected to write (the baseline's average is 973): the reservation of its cost."""

PROBE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["word", "number"],
    "properties": {"word": {"type": "string", "enum": ["alpha", "beta", "gamma"]}, "number": {"type": "integer"}}}


class ProbeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: Literal["alpha", "beta", "gamma"]
    number: int


def _h(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def filler(tag: str, tokens: int) -> str:
    """A fixed text of about ``tokens`` tokens (four characters each): the same bytes every time, so that a cache can match it."""
    out: list[str] = []
    size, n = 0, 0
    while size < tokens * 4:
        n += 1
        line = f"Rule {tag}-{n:04d}: when the data of a match is incomplete, say what is missing and never invent it.\n"
        out.append(line)
        size += len(line)
    return "".join(out)


PROBE_SYSTEM = "You answer a probe. Follow the rules below and answer with the word alpha and a number.\n" + filler("S", 1600)
PROBE_SHARED = json.dumps({"probe": "common block", "rules": filler("M", 1600)})
"""Each of the two blocks is well over the 512 tokens a cache needs: a probe that finds no cache has found something."""


def probe_request(user: str, *, native: bool = False, shared: bool = True) -> JsonRequest:
    return JsonRequest(system=PROBE_SYSTEM, user=user, schema=PROBE_SCHEMA, schema_name="submit_probe", max_tokens=2000,
                       timeout_s=90.0, shared=PROBE_SHARED if shared else "", cache=True, native_schema=native, pinned=True)


def blockers(settings: AiSettings, tiers: Sequence[Tier]) -> list[str]:
    """Why the LAB cannot run an experiment now - NAMES of variables and numbers of owner actions, never a value."""
    out: list[str] = []
    has_key = "anthropic" in settings.lab_keys
    if not has_key:
        out.append("no LAB key: set FBI_AI_KEY_ANTHROPIC_LAB on the server (owner actions 5 and 7)")
    if settings.lab_monthly_budget <= 0:
        out.append("the LAB has no envelope: set FBI_AI_LAB_MONTHLY_BUDGET_USD (owner action 7)")
    if has_key:
        for tier in tiers:
            tm = settings.tier(tier, lab=True)
            if tm is None or tm.provider != "anthropic":
                out.append(f"the {tier} tier has no Anthropic model for the LAB")
    return out


def _record_if_new(conn: psycopg.Connection[Any], *, gate: str, passed: bool, evidence: dict[str, Any], at: datetime) -> int | None:
    """Append the evidence of a gate unless its newest row already says exactly this (the same measurements, the same decision): a
    collection repeated for the same experiment does not fill the table. Returns the row's id, None when nothing was appended."""
    newest = gates.gate_state(conn, gate)
    if newest.evidence_hash == gates.evidence_hash(evidence) and newest.passed == passed:
        return None
    return gates.record_gate(conn, gate=gate, passed=passed, evidence=evidence, at=at)


# ── the probes ───────────────────────────────────────────────────────────────────────────────────────────────────

def cache_verdict(first: LlmUsage, second: LlmUsage) -> dict[str, Any]:
    """What two identical calls in a row say about the prompt cache: the first wrote, the second read what the first wrote."""
    wrote = first.cache_write_tokens
    read_what_was_written = wrote > 0 and second.cached_tokens >= 0.9 * wrote
    return {"wrote_tokens": wrote, "wrote_5m_tokens": first.cache_write_5m_tokens, "wrote_1h_tokens": first.cache_write_1h_tokens,
            "read_tokens": second.cached_tokens, "wrote": wrote > 0, "read": second.cached_tokens > 0,
            "read_what_was_written": read_what_was_written,
            "both_ttls": first.cache_write_5m_tokens > 0 and first.cache_write_1h_tokens > 0,
            "ok": read_what_was_written}


def _usage_json(u: LlmUsage) -> dict[str, int]:
    return {"input": u.input_tokens, "output": u.output_tokens, "read": u.cached_tokens, "wrote_5m": u.cache_write_5m_tokens,
            "wrote_1h": u.cache_write_1h_tokens, "thinking": u.thinking_tokens}


def probe_cache(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, tiers: Sequence[Tier] = ("bulk", "analysis"),
                ledger: UsageLedger | None = None, transport: httpx.BaseTransport | None = None,
                provider: tuple[LlmProvider, str] | None = None) -> dict[str, Any]:
    """Two identical calls per tier in the LAB: does the prompt cache write the first and read the second? Real-time (a cache lives
    five minutes), a few cents. A tier the budget lowered is a probe that did not measure that tier: it is not ok."""
    stop = blockers(settings, tiers) if provider is None else []
    if stop:
        return {"probe": PROBE_CACHE_VERSION, "ok": False, "blockers": stop}
    report: dict[str, Any] = {"probe": PROBE_CACHE_VERSION, "tiers": {}}
    for tier in tiers:
        calls = []
        for n in range(2):
            calls.append(call_json(conn, settings, tier=tier, purpose="other", at=at, prompt_version=PROBE_CACHE_VERSION,
                                   input_hash=_h(PROBE_CACHE_VERSION, tier, at.isoformat(), n), ledger=ledger,
                                   transport=transport, provider=provider, lab=True,
                                   request=probe_request("Answer with the word alpha and the number 1.")))
        first, second = calls
        entry: dict[str, Any] = {"model": first.model, "cost_usd": str(first.cost + second.cost)}
        if first.result is None or second.result is None:
            entry |= {"ok": False, "error": first.error or second.error, "calls": sum(1 for c in calls if c.result)}
        elif first.tier != tier or second.tier != tier:
            entry |= {"ok": False, "error": "the budget lowered the tier: nothing measured for it"}
        else:
            entry |= cache_verdict(first.result.usage, second.result.usage)
            entry["usage"] = [_usage_json(first.result.usage), _usage_json(second.result.usage)]
        report["tiers"][tier] = entry
    report["ok"] = bool(report["tiers"]) and all(t.get("ok") for t in report["tiers"].values())
    return report


def probe_schema(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime,
                 tiers: Sequence[Tier] = ("bulk", "analysis"), ledger: UsageLedger | None = None,
                 transport: httpx.BaseTransport | None = None,
                 provider: tuple[LlmProvider, str] | None = None) -> dict[str, Any]:
    """The same small question through the tool call and through structured outputs: both must answer inside the schema."""
    stop = blockers(settings, tiers) if provider is None else []
    if stop:
        return {"probe": PROBE_SCHEMA_VERSION, "ok": False, "blockers": stop}
    report: dict[str, Any] = {"probe": PROBE_SCHEMA_VERSION, "tiers": {}}
    for tier in tiers:
        entry: dict[str, Any] = {}
        for route, native in (("tool", False), ("native", True)):
            out = call_json(conn, settings, tier=tier, purpose="other", at=at, prompt_version=PROBE_SCHEMA_VERSION,
                            input_hash=_h(PROBE_SCHEMA_VERSION, tier, route, at.isoformat()), ledger=ledger,
                            transport=transport, provider=provider, lab=True,
                            request=probe_request("Answer with the word beta and the number 2.", native=native, shared=False))
            valid = False
            if out.result is not None and out.tier == tier:
                try:
                    ProbeOut.model_validate(out.result.data)
                    valid = True
                except ValidationError:
                    valid = False
            entry[route] = {"model": out.model, "valid": valid, "error": out.error, "cost_usd": str(out.cost),
                            "stop_reason": None if out.result is None else out.result.extra.get("stop_reason")}
        entry["ok"] = entry["tool"]["valid"] and entry["native"]["valid"]
        report["tiers"][tier] = entry
    report["ok"] = bool(report["tiers"]) and all(t["ok"] for t in report["tiers"].values())
    return report


def probe_batch_tasks(settings: AiSettings, *, run: str, tiers: Sequence[Tier]) -> list[Task]:
    """The requests of the batch probe: per MODEL a tool call, structured outputs and a second tool call whose cache may be a read
    (two tiers that share a model are one probe)."""
    tasks: list[Task] = []
    seen: set[str] = set()
    for tier in tiers:
        tm = settings.tier(tier, lab=True)
        if tm is None or tm.model in seen:
            continue
        seen.add(tm.model)
        for variant, native, user in (("tool", False, "Answer with the word alpha and the number 1."),
                                      ("native", True, "Answer with the word beta and the number 2."),
                                      ("tool2", False, "Answer with the word gamma and the number 3.")):
            tasks.append(Task(
                purpose="other", tier=tier, request=probe_request(user, native=native), prompt_version=PROBE_BATCH_VERSION,
                input_hash=_h(PROBE_BATCH_VERSION, run, tier, variant), lab=True, typical_output=PROBE_TYPICAL_OUTPUT,
                context={"lab": "probe", "run": run, "variant": variant}))
    return tasks


def probe_batch_submit(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime,
                       tiers: Sequence[Tier] = ("bulk", "analysis"), ledger: UsageLedger | None = None,
                       client: BatchClient | None = None, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Send the probe batch of the day (asking again the same day finds what is already sent). Returns what was done."""
    stop = blockers(settings, tiers)
    if stop:
        return {"submitted": 0, "blockers": stop}
    run = at.date().isoformat()
    tasks = probe_batch_tasks(settings, run=run, tiers=tiers)
    queue = BatchQueue(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    admissions = [queue.add(t) for t in tasks]
    if any(not a.pending for a in admissions):  # all or nothing: a probe of some of the models proves nothing of the others
        conn.rollback()
        return {"run": run, "submitted": 0, "refused": dict(queue.refused),
                "blockers": ["the queue refused part of the probe (see refused): nothing was sent"]}
    report = queue.flush()
    states: dict[str, int] = {}
    for a in admissions:
        states[a.status] = states.get(a.status, 0) + 1
    return {"run": run, "tasks": len(admissions), "states": states, "sent": report.sent, "failed": report.failed,
            "error": report.error}


ITEMS_OF_RUN_SQL = """
SELECT i.id, i.custom_id, i.tier, i.model, i.status, i.error, i.context, i.created_at, i.resolved_at,
       u.input_tokens, u.output_tokens, u.cached_tokens, u.cache_write_tokens, u.cost_usd, b.created_at AS batch_created,
       b.ended_at AS batch_ended
  FROM ai.batch_items i
  JOIN ai.batches b ON b.id = i.batch_id
  LEFT JOIN ai.usage u ON u.id = i.usage_id
 WHERE i.purpose = 'other' AND i.prompt_version = %(version)s AND i.context ->> 'run' = %(run)s AND i.status <> 'abandoned'
 ORDER BY i.id
"""

LATEST_RUN_SQL = """
SELECT context ->> 'run' FROM ai.batch_items WHERE purpose = 'other' AND prompt_version = %(version)s ORDER BY id DESC LIMIT 1
"""


def batch_evidence(items: Sequence[dict[str, Any]]) -> tuple[bool | None, dict[str, Any]]:
    """The batch gate's decision from the items of a probe run: None = results still on their way; otherwise ``passed`` when at
    least one model's tool call came back inside the schema, and the evidence NAMES those models (``models``): another model is not
    covered. Whether structured outputs and the cache also work INSIDE a batch is said per model, because ``native_schema`` and
    ``cache_layout`` need to know."""
    if any(i["status"] in ("submitting", "submitted") for i in items):
        return None, {"state": "waiting", "open": sum(1 for i in items if i["status"] in ("submitting", "submitted"))}
    by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for i in items:
        ctx = i["context"] or {}
        result = ctx.get("result") or {}
        ok = i["status"] in ("succeeded", "late") and bool(result.get("valid"))
        by_model.setdefault(str(i["model"]), {})[str(ctx.get("variant"))] = {
            "ok": ok, "status": i["status"], "error": i["error"], "stop_reason": result.get("stop_reason"),
            "read_tokens": int(i["cached_tokens"] or 0), "wrote_tokens": int(i["cache_write_tokens"] or 0),
            "input_tokens": int(i["input_tokens"] or 0), "output_tokens": int(i["output_tokens"] or 0),
            "cost_usd": str(i["cost_usd"] or 0)}
    covered = sorted(m for m, v in by_model.items() if v.get("tool", {}).get("ok"))
    ended = [i["batch_ended"] for i in items if i["batch_ended"] is not None]
    created = [i["batch_created"] for i in items if i["batch_created"] is not None]
    minutes = None if not ended or not created else round((max(ended) - min(created)).total_seconds() / 60, 1)
    evidence: dict[str, Any] = {
        "state": "ended", "probe": PROBE_BATCH_VERSION, "models": covered, "failed_models": sorted(set(by_model) - set(covered)),
        "items": by_model, "elapsed_minutes": minutes,
        "native_in_batch": {m: bool(v.get("native", {}).get("ok")) for m, v in sorted(by_model.items())},
        "cache_read_in_batch": {m: any(x["read_tokens"] > 0 for x in v.values()) for m, v in sorted(by_model.items())}}
    return bool(covered), evidence


def probe_batch_collect(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, run: str | None = None,
                        ledger: UsageLedger | None = None, client: BatchClient | None = None,
                        transport: httpx.BaseTransport | None = None, record: bool = True) -> dict[str, Any]:
    """Take the probe batch's results (the poll is idempotent: the worker may have taken them already) and, when every item is
    closed, record the ``batch`` gate - passed or not, with the evidence. Nothing is recorded while results are still on their way."""
    polled = poll(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    if run is None:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(LATEST_RUN_SQL, {"version": PROBE_BATCH_VERSION})
            row = cur.fetchone()
        run = None if row is None else str(row[0])
    if run is None:
        return {"state": "nothing_submitted"}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ITEMS_OF_RUN_SQL, {"version": PROBE_BATCH_VERSION, "run": run})
        items = [dict(r) for r in cur.fetchall()]
    if not items:
        return {"run": run, "state": "nothing_submitted"}
    passed, evidence = batch_evidence(items)
    out: dict[str, Any] = {"run": run, "poll_errors": polled.errors} | evidence
    if passed is None:
        return out
    out["passed"] = passed  # the verdict is shown with or without recording it
    if not record:
        return out
    out["gate_id"] = _record_if_new(conn, gate="batch", passed=passed, evidence=evidence | {"run": run}, at=at)
    conn.commit()
    return out


# ── the handler of what comes back ───────────────────────────────────────────────────────────────────────────────

def _settle_probe(r: Resolved) -> dict[str, Any]:
    if r.result is None:
        return {"valid": False, "error": None if r.error is None else r.error.code}
    try:
        ProbeOut.model_validate(r.result.data)
    except ValidationError:
        return {"valid": False, "error": "schema", "stop_reason": r.result.extra.get("stop_reason")}
    return {"valid": True, "stop_reason": r.result.extra.get("stop_reason")}


def _settle_equivalence(conn: psycopg.Connection[Any], r: Resolved, ctx: dict[str, Any]) -> dict[str, Any]:
    if r.result is None:
        return {"decision": None, "status": "invalid_output", "error": None if r.error is None else r.error.code}
    c = Candidate.from_state(ctx["candidate"])
    packet = load_packet(conn, int(ctx["packet_id"]))
    if packet is None:
        raise LookupError(f"packet {ctx['packet_id']} is not stored")
    at = datetime.fromisoformat(ctx["at"])
    out = answer_review(c, packet, signals_for(c, packet, at=at), r.result.data, view=review_view(packet.content),
                        h=str(r.item["input_hash"]), tier=str(r.item["tier"]), provider="anthropic", model=str(r.item["model"]),
                        usage_ids=[], cost=r.cost, role="candidate", stop_reason=r.result.extra.get("stop_reason"),
                        layout=ctx.get("layout"))
    return {"decision": out.decision if out.status == "ok" else None, "status": out.status,
            "rejected_claims": len(out.output.get("rejected_claims") or []), "stop_reason": r.result.extra.get("stop_reason")}


def settle_lab(conn: psycopg.Connection[Any], r: Resolved) -> None:
    """What an answer of the LAB becomes: a summary kept in its item (``context.result``). A probe's says whether the answer fits its
    schema; an equivalence input's is the verdict the CHECKED review would have had - the same ``answer_review`` as production's.
    Nothing else is written: a LAB answer is never a review, a pick or a state."""
    ctx = r.item["context"] or {}
    kind = ctx.get("lab")
    if kind == "probe":
        summary = _settle_probe(r)
    elif kind == "equivalence":
        summary = _settle_equivalence(conn, r, ctx)
    else:
        raise ValueError("an item of purpose 'other' that is not a probe or an experiment")
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.batch_items SET context = context || %s WHERE id = %s",
                    (Jsonb({"result": summary}), int(r.item["id"])))


register("other", settle_lab)


# ── the equivalence test ─────────────────────────────────────────────────────────────────────────────────────────

MIN_INPUTS = 200
"""Plan, gate A: «sobre ≥ 200 paquetes guardados»."""
MAX_INVALID = 0.03
"""Plan, service objectives: «≤ 3 % de inválidas»."""
INVALID_MARGIN = 0.01
"""A variant may not be invalid more than a point more often than the calls production makes today."""
VARIANTS = ("native_schema", "shared_layout")
BASELINES = ("A1", "A2")
VARIANT_KEY = {"native_schema": "B", "shared_layout": "C"}
GATE_OF_VARIANT = {"native_schema": "native_schema", "shared_layout": "cache_layout"}
LETTER = {"APPROVE": "A", "DOWNGRADE": "D", "REJECT": "R", "ABSTAIN": "S"}

Rows = dict[str, dict[str, str | None]]
"""Per input, the letter of each ask's verdict (``A1``, ``A2``, ``B``, ``C``); None = the ask did not come back as a valid review."""


def _rate(k: int, n: int) -> float | None:
    return None if n == 0 else round(k / n, 4)


def _moves(pairs: Iterable[tuple[str | None, str | None]]) -> dict[str, int]:
    """Which verdicts moved where: 'A>D' = approved by the first call, downgraded by the second."""
    return dict(sorted(Counter(f"{a}>{b}" for a, b in pairs if a != b).items()))


def assess(rows: Rows, variant: str, *, min_inputs: int = MIN_INPUTS) -> dict[str, Any]:
    """The rule of the gate, written before the data. ``rows`` maps an input to its verdicts (``A1``, ``A2`` - the same call twice,
    as production asks it - and ``B`` / ``C``: structured outputs / the common block first); a verdict is a letter of ``LETTER`` or
    None when the call did not come back as a valid review.

    * VERDICT CHANGE: over the inputs whose three verdicts are valid, the number where the variant's verdict differs from the first
      call's must not be larger than the number where the SECOND identical call differs from it - the plan's «≤ el de repetir la
      misma llamada». Both are measured on the same inputs, so the model's own run-to-run noise is the yardstick.
    * VALIDITY: the variant's invalid answers must be at most 3 % and at most one point above the identical calls'.
    * SIZE: at least ``min_inputs`` such inputs. Fewer is INSUFICIENTE, never a pass.

    The direction of the changes (toward APPROVE, toward a restriction), the verdicts that moved and a 95 % interval of the difference
    are reported, not decided on: the pass is the plan's criterion, and the interval says how much a pass or a fail can be luck."""
    key = VARIANT_KEY[variant]
    complete = {i: r for i, r in rows.items() if all(r.get(k) is not None for k in (*BASELINES, key))}
    n = len(complete)
    repeat = [int(r["A2"] != r["A1"]) for r in complete.values()]
    changed = [int(r[key] != r["A1"]) for r in complete.values()]
    diffs = [c - p for c, p in zip(changed, repeat, strict=True)]
    base_calls = [r[k] for r in rows.values() for k in BASELINES if k in r]
    variant_calls = [r[key] for r in rows.values() if key in r]
    base_invalid = _rate(sum(1 for v in base_calls if v is None), len(base_calls))
    variant_invalid = _rate(sum(1 for v in variant_calls if v is None), len(variant_calls))

    def share(k: str) -> float | None:
        return _rate(sum(1 for r in complete.values() if r[k] == "A"), n)

    out: dict[str, Any] = {
        "variant": variant, "inputs": len(rows), "complete_inputs": n,
        "changed_repeat": sum(repeat), "changed_variant": sum(changed),
        "change_repeat": _rate(sum(repeat), n), "change_variant": _rate(sum(changed), n),
        "invalid_baseline": base_invalid, "invalid_variant": variant_invalid,
        "approve_share": {"A1": share("A1"), "A2": share("A2"), key: share(key)},
        "toward_approve": {"repeat": sum(1 for r in complete.values() if r["A1"] != "A" and r["A2"] == "A"),
                           "variant": sum(1 for r in complete.values() if r["A1"] != "A" and r[key] == "A")},
        "toward_restriction": {"repeat": sum(1 for r in complete.values() if r["A1"] == "A" and r["A2"] != "A"),
                               "variant": sum(1 for r in complete.values() if r["A1"] == "A" and r[key] != "A")},
        "moves": {"repeat": _moves((r["A1"], r["A2"]) for r in complete.values()),
                  "variant": _moves((r["A1"], r[key]) for r in complete.values())}}
    if n >= 2:
        diff = sum(diffs) / n
        se = statistics.stdev(diffs) / math.sqrt(n)
        out["difference"] = round(diff, 4)
        out["difference_ci95"] = [round(diff - 1.96 * se, 4), round(diff + 1.96 * se, 4)]
    reasons: list[str] = []
    if n < min_inputs:
        reasons.append(f"insufficient: {n} complete inputs, {min_inputs} needed")
    if sum(changed) > sum(repeat):
        reasons.append(f"the variant changes more verdicts ({sum(changed)}) than repeating the same call ({sum(repeat)})")
    if variant_invalid is not None and (variant_invalid > MAX_INVALID or variant_invalid > (base_invalid or 0.0) + INVALID_MARGIN):
        reasons.append("the variant's answers are invalid more often than allowed")
    out["insufficient"] = n < min_inputs
    out["passed"] = not reasons
    out["verdict"] = "INSUFICIENTE" if n < min_inputs else "PASA" if not reasons else "NO PASA"
    out["reasons"] = reasons
    return out


@dataclass(frozen=True)
class EquivInput:
    ref: str
    candidate: Candidate
    packet_id: int
    at: datetime


SELECT_INPUTS_SQL = """
SELECT * FROM (
  SELECT DISTINCT ON (r.packet_id, r.market_key, r.selection, r.line)
         r.id, r.reviewed_at, r.fixture_id, r.pick_id, r.market_key, r.selection, r.line, r.odds, r.bookmaker_id, r.p_model,
         r.p_low, r.p_market, r.ev, r.packet_id, f.kickoff_at, bk.name AS bookmaker
    FROM ai.pick_reviews r
    JOIN core.fixtures f ON f.id = r.fixture_id
    JOIN ai.match_packets p ON p.id = r.packet_id
    LEFT JOIN market.bookmakers bk ON bk.id = r.bookmaker_id
   WHERE r.engine = 'llm' AND r.status = 'ok' AND r.model = %(model)s AND r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s
     AND r.p_model IS NOT NULL AND r.odds IS NOT NULL AND f.kickoff_at > r.reviewed_at
   ORDER BY r.packet_id, r.market_key, r.selection, r.line, r.id DESC) one
 ORDER BY md5(one.id::text || %(seed)s)
 LIMIT %(n)s
"""


def select_inputs(conn: psycopg.Connection[Any], *, model: str, since: datetime, until: datetime, n: int,
                  seed: str = EQUIVALENCE_VERSION) -> list[EquivInput]:
    """``n`` stored review inputs of ``model`` - the packet as it was when the review was made, the candidate as stored - in an order
    fixed by the seed (the same ones every time). Reconstructed from ``ai.pick_reviews``: what that table does not keep (the interval's
    upper end, the number of bookmakers, the moment of the price) is absent from the prompt the same way for every variant."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SELECT_INPUTS_SQL, {"model": model, "since": since, "until": until, "n": n, "seed": seed})
        rows = [dict(r) for r in cur.fetchall()]
    out: list[EquivInput] = []
    for r in rows:
        c = Candidate(fixture_id=int(r["fixture_id"]), market_key=str(r["market_key"]), selection=str(r["selection"]),
                      line=Decimal(r["line"]), p_model=Decimal(r["p_model"]), kickoff_at=r["kickoff_at"],
                      pick_id=None if r["pick_id"] is None else int(r["pick_id"]), odds=Decimal(r["odds"]),
                      bookmaker_id=r["bookmaker_id"], bookmaker=r["bookmaker"],
                      p_low=None if r["p_low"] is None else Decimal(r["p_low"]),
                      p_market=None if r["p_market"] is None else Decimal(r["p_market"]),
                      ev=None if r["ev"] is None else Decimal(r["ev"]))
        out.append(EquivInput(f"{r['packet_id']}:{r['id']}", c, int(r["packet_id"]), r["reviewed_at"]))
    return out


def equivalence_requests(inp: EquivInput, packet: Packet) -> dict[str, JsonRequest]:
    """The four asks of one input, each PINNED to exactly what it measures: ``A1`` and ``A2`` the call production makes (the system block
    marked for the cache, the tool call, the usual layout), ``B`` the same with structured outputs, ``C`` the same with the
    common block first (and marked)."""
    signals = signals_for(inp.candidate, packet, at=inp.at)
    base = replace(review_request(inp.candidate, packet, signals, at=inp.at), cache=True, pinned=True)
    assert base.split is not None
    return {"A1": base, "A2": base, "B": replace(base, native_schema=True),
            "C": replace(base, shared=base.split[0], user=base.split[1])}


def experiment_id(model: str, seed: str, at: datetime) -> str:
    return f"{EQUIVALENCE_VERSION}:{model}:{seed}:{at.date().isoformat()}"


def equivalence_tasks(inp: EquivInput, packet: Packet, *, tier: Tier, experiment: str) -> list[Task]:
    """The asks of one input as tasks of the queue. No fixture is named: the LAB's spend is not any match's cost."""
    return [Task(
        purpose="other", tier=tier, request=request, prompt_version=EQUIVALENCE_VERSION,
        input_hash=_h(EQUIVALENCE_VERSION, experiment, inp.ref, variant), lab=True, typical_output=EQUIVALENCE_TYPICAL_OUTPUT,
        context={"lab": "equivalence", "experiment": experiment, "input": inp.ref, "variant": variant,
                 "candidate": inp.candidate.to_state(), "packet_id": inp.packet_id, "at": inp.at.isoformat()})
        for variant, request in equivalence_requests(inp, packet).items()]


def equivalence_submit(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, tier: Tier = "analysis",
                       n: int = MIN_INPUTS + 10, since_days: int = 21, seed: str = EQUIVALENCE_VERSION,
                       ledger: UsageLedger | None = None, client: BatchClient | None = None,
                       transport: httpx.BaseTransport | None = None, dry_run: bool = False,
                       min_inputs: int = MIN_INPUTS) -> dict[str, Any]:
    """Send the experiment as ONE batch of the LAB: for each stored input, the four asks. All or nothing: the whole cost is estimated
    first and compared with what the LAB may still spend, and nothing is sent if it does not fit - or if the queue refuses any ask.
    The inputs are those of the days before today (fixed for the whole day), so asking again finds what is already sent.
    ``min_inputs`` is the plan's 200; only a test lowers it (the scripts do not offer it)."""
    tm = settings.tier(tier, lab=True)
    stop = blockers(settings, [tier])
    if stop or tm is None:
        return {"submitted": 0, "blockers": stop or [f"the {tier} tier has no model in the LAB"]}
    experiment = experiment_id(tm.model, seed, at)
    until = at.replace(hour=0, minute=0, second=0, microsecond=0)
    inputs = select_inputs(conn, model=tm.model, since=until - timedelta(days=since_days), until=until, n=n, seed=seed)
    tasks: list[Task] = []
    for inp in inputs:
        packet = load_packet(conn, inp.packet_id)
        if packet is not None:
            tasks.extend(equivalence_tasks(inp, packet, tier=tier, experiment=experiment))
    estimate = sum((estimate_cost(tm.model, with_effort(t.request, t.tier), typical_output=t.typical_output, at=at)
                    for t in tasks), Decimal(0))
    room = budget_v3.lab_day(conn, at=at, settings=settings)  # the LAB's month: its allocation minus what it spent and reserved
    out: dict[str, Any] = {"experiment": experiment, "model": tm.model, "inputs": len(inputs), "asks": len(tasks),
                           "estimate_usd": str(estimate.quantize(Decimal("0.01"))),
                           "lab_remaining_usd": str(room.remaining.quantize(Decimal("0.01"))), "lab_day": room.reason}
    if len(inputs) < min_inputs:
        return out | {"submitted": 0, "blockers": [f"only {len(inputs)} stored reviews of {tm.model} to replay; {min_inputs} are needed"]}
    if not room.can_spend or estimate > room.remaining:
        return out | {"submitted": 0, "blockers": ["the LAB cannot pay for this experiment now (see lab_day and lab_remaining_usd)"]}
    if dry_run:
        return out | {"submitted": 0, "dry_run": True}
    queue = BatchQueue(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    admissions = [queue.add(t) for t in tasks]
    if any(not a.pending for a in admissions):
        conn.rollback()
        return out | {"submitted": 0, "refused": dict(queue.refused),
                      "blockers": ["the queue refused part of the experiment (see refused): nothing was sent"]}
    states: dict[str, int] = {}
    for a in admissions:
        states[a.status] = states.get(a.status, 0) + 1
    report = queue.flush()
    return out | {"submitted": report.sent, "states": states, "failed": report.failed, "error": report.error}


ITEMS_OF_EXPERIMENT_SQL = """
SELECT i.status, i.context, u.cost_usd FROM ai.batch_items i LEFT JOIN ai.usage u ON u.id = i.usage_id
 WHERE i.purpose = 'other' AND i.prompt_version = %(version)s AND i.context ->> 'experiment' = %(experiment)s
   AND i.status <> 'abandoned' ORDER BY i.id
"""

LATEST_EXPERIMENT_SQL = """
SELECT context ->> 'experiment' FROM ai.batch_items WHERE purpose = 'other' AND prompt_version = %(version)s ORDER BY id DESC LIMIT 1
"""


def equivalence_rows(items: Sequence[dict[str, Any]]) -> Rows:
    """Per input, the letter of each ask's verdict (None = it did not come back as a valid review)."""
    rows: Rows = {}
    for i in items:
        ctx = i["context"] or {}
        verdict = str((ctx.get("result") or {}).get("decision"))
        answered = i["status"] in ("succeeded", "late")
        rows.setdefault(str(ctx.get("input")), {})[str(ctx.get("variant"))] = LETTER.get(verdict) if answered else None
    return rows


def _require(verdict: dict[str, Any], ok: bool, why: str) -> None:
    """A condition besides the statistics (a probe that saw what it had to see): without it the gate does not pass, whatever the
    verdicts of the model say. An INSUFICIENTE stays so."""
    if ok:
        return
    verdict["reasons"] = [*verdict["reasons"], why]
    verdict["passed"] = False
    if verdict["verdict"] == "PASA":
        verdict["verdict"] = "NO PASA"


def cache_probe_ok(conn: psycopg.Connection[Any], model: str, *, since: datetime) -> bool:
    """Whether a LAB probe saw the cache READ for this model lately (a row of the ledger, not a claim)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT 1 FROM ai.usage_scoped WHERE scope = 'lab' AND model = %s AND prompt_version = %s AND status = 'ok' "
                    "AND cached_tokens > 0 AND at >= %s LIMIT 1", (model, PROBE_CACHE_VERSION, since))
        return cur.fetchone() is not None


def native_in_batch(conn: psycopg.Connection[Any], model: str) -> bool:
    """Whether the newest ``batch`` gate says structured outputs worked inside a batch for this model."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT evidence FROM ai.feature_gates WHERE gate = 'batch' ORDER BY at DESC, id DESC LIMIT 1")
        row = cur.fetchone()
    evidence = row[0] if row is not None and isinstance(row[0], dict) else {}
    return bool((evidence.get("native_in_batch") or {}).get(model))


def equivalence_collect(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, experiment: str | None = None,
                        model: str | None = None, ledger: UsageLedger | None = None, client: BatchClient | None = None,
                        transport: httpx.BaseTransport | None = None, record: bool = True,
                        min_inputs: int = MIN_INPUTS) -> dict[str, Any]:
    """Take the experiment's results and, when every ask is closed, assess each variant and record its gate: ``native_schema`` (also
    needs structured outputs to have worked inside a batch) and ``cache_layout`` (also needs a probe to have seen the cache read).
    The evidence of a gate holds every input's letters, so the decision can be recomputed from the row. Collecting again, before or
    after the probes, only appends a row when it changes what the newest one says."""
    polled = poll(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    if experiment is None:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(LATEST_EXPERIMENT_SQL, {"version": EQUIVALENCE_VERSION})
            row = cur.fetchone()
        experiment = None if row is None else str(row[0])
    if experiment is None:
        return {"state": "nothing_submitted"}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ITEMS_OF_EXPERIMENT_SQL, {"version": EQUIVALENCE_VERSION, "experiment": experiment})
        items = [dict(r) for r in cur.fetchall()]
    if not items:
        return {"experiment": experiment, "state": "nothing_submitted"}
    open_ = sum(1 for i in items if i["status"] in ("submitting", "submitted"))
    if open_:
        return {"experiment": experiment, "state": "waiting", "open": open_, "asks": len(items), "poll_errors": polled.errors}
    model = model or experiment.split(":")[1]
    rows = equivalence_rows(items)
    cost = sum((Decimal(i["cost_usd"] or 0) for i in items), Decimal(0))
    out: dict[str, Any] = {"experiment": experiment, "state": "ended", "asks": len(items), "cost_usd": str(cost),
                           "variants": {}}
    for variant in VARIANTS:
        verdict = assess(rows, variant, min_inputs=min_inputs)
        extra: dict[str, Any]
        if variant == "native_schema":
            extra = {"native_in_batch": native_in_batch(conn, model)}
            _require(verdict, extra["native_in_batch"], "structured outputs have not worked inside a batch (run ia_probe batch)")
        else:
            extra = {"cache_seen_reading": cache_probe_ok(conn, model, since=at - timedelta(days=14))}
            _require(verdict, extra["cache_seen_reading"], "no probe has seen the cache read for this model (run ia_probe cache)")
        evidence = {"models": [model], "experiment": experiment, "min_inputs": min_inputs,
                    "rule": f"change(variant) <= change(repeat), >= {min_inputs} inputs", "assessment": verdict | extra,
                    "inputs": {ref: "".join(r.get(k) or "-" for k in (*BASELINES, VARIANT_KEY[variant]))
                               for ref, r in sorted(rows.items())}}
        entry = verdict | extra
        if record:
            entry["gate_id"] = _record_if_new(conn, gate=GATE_OF_VARIANT[variant], passed=bool(verdict["passed"]),
                                              evidence=evidence, at=at)
        out["variants"][variant] = entry
    if record:
        conn.commit()
    return out
