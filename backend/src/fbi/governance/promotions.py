"""One registry of promotions, read from the ledgers that exist (``registry-v1``, Plan Maestro IA, phase P0).

WHY THIS EXISTS
---------------
The rule of the plan is that nothing changes what production decides without hypothesis -> experiment -> gate -> promotion, and each kind of
change got its ledger when it got its rule - so today the answer to «what is in force, since when, decided by whom and why» lives in five
places with five shapes:

    source                                  entity_type    key                   version                 decision
    intel.promotions (calibrator)           calibrator     <market>/<model>      calibrator id           to_role (CHAMPION ...)
    intel.promotions (market_edge)          market_edge    <market>/<model>      -                       to_role (VALIDATED ...)
    intel.promotions (selection_rule)       selection_rule <market>/<model>      entity id               to_role
    intel.promotions (model)                model          model_code            the fingerprint         to_role (CHAMPION, RETIRED)
    intel.promotions (agent)                agent          <family>              agent@version[+...]     to_role, signed by the owner
    fbi.research.promotions.LEDGER (F12)    model          model_code            the fingerprint         CHAMPION, declared in code
    analytics.promoted_forecast_spec        goal_spec      forecast_spec         spec-v1:<hash of spec>  PROMOTED
    analytics.neutral_rule_promotion        neutral_rule   neutral_venue         rule_version            PROMOTED / RETIRED
    ai.feature_gates (not ``switches``)     ai_gate        <gate>                code version            PASSED / FAILED

``ai.feature_gates`` is included because its newest row is what switches an optimisation of the AI layer on (``fbi.ai.gates``); its gate
``switches`` is left out on purpose: it is the trace of a change of configuration, not a decision (``passed`` is always true, migration 0116).
The code ledger of F12 is listed beside the rows it is copied into: an entry is ``effective`` only once ``scripts.promotion_trace sync`` has
written it to ``intel.promotions`` - until then it is a decision declared in a commit and not yet on record in the database, and ``current``
never takes it.

WHAT «CURRENT» MEANS, per kind, the way the code that acts on each ledger reads it:

* BY_VERSION (calibrator, agent, model, selection_rule): the newest record that puts a version in force and that no later record of the same
  key and version took out (``fbi.intel.calibration.ROLES_SQL``, ``intel.agent_champion``, ``fbi.research.trace.load_recorded``). A
  CHALLENGER row of another calibrator does not depose the champion; its RETIRED row does.
* NEWEST (market_edge, goal_spec, neutral_rule, ai_gate): the newest record of the key decides (``fbi.intel.calibration.EDGE_SQL``,
  ``fbi.predictions.spec``, ``fbi.catalog.neutral_store``, ``fbi.ai.gates.STATE_SQL``).

When nothing of a key is in force, ``current`` returns its newest record (``in_force`` False says what took it out); ``None`` when the key has
no record. Every reading takes ``at=``: the registry as it stood at that moment (records dated after it do not exist yet).

Nothing here writes: every statement is a SELECT and the connection is the caller's.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.research import promotions as code_ledger
from fbi.research.promotions import CodePromotion

VERSION: Final = "registry-v1"

IN_FORCE: Final = frozenset({"CHAMPION", "VALIDATED", "PROMOTED", "PASSED"})
OUT_OF_FORCE: Final = frozenset({"CHALLENGER", "RETIRED", "REJECTED", "NOT_VALIDATED", "FAILED"})
BY_VERSION: Final = frozenset({"calibrator", "agent", "model", "selection_rule"})
NEWEST: Final = frozenset({"market_edge", "goal_spec", "neutral_rule", "ai_gate"})
ENTITY_TYPES: Final = tuple(sorted(BY_VERSION | NEWEST))
CODE_LEDGER_SOURCE: Final = "fbi.research.promotions.LEDGER"
MODEL_CODE_KEY: Final = "model_code"
GOAL_SPEC_KEY: Final = "forecast_spec"
NEUTRAL_KEY: Final = "neutral_venue"
TEXT_CUT: Final = 160
EVIDENCE_KEYS: Final = 16
"""A record's evidence is compact: at most this many top-level entries, nested objects summarised by their keys, strings cut."""


@dataclass(frozen=True, slots=True)
class Promotion:
    """One decision of any ledger, in one shape."""

    entity_type: str
    entity_key: str
    version: str | None
    decision: str
    in_force: bool | None
    """True when the decision puts ``version`` in force, False when it takes it (or the key) out, None for a word the registry does not know."""
    decided_by: str
    at: datetime
    gate_version: str | None
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    source_table: str = ""
    source_id: str = ""
    effective: bool = True
    """False for an entry of the code ledger: declared in a commit, on record in the database only once synced."""

    def as_json(self) -> dict[str, Any]:
        return {"entity_type": self.entity_type, "entity_key": self.entity_key, "version": self.version, "decision": self.decision,
                "in_force": self.in_force, "effective": self.effective, "decided_by": self.decided_by, "at": self.at.isoformat(),
                "gate_version": self.gate_version, "reason": self.reason, "evidence": dict(self.evidence), "source_table": self.source_table,
                "source_id": self.source_id}


# ── pure: normalising each shape ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def in_force_of(decision: str) -> bool | None:
    if decision in IN_FORCE:
        return True
    if decision in OUT_OF_FORCE:
        return False
    return None


def compact_evidence(value: Any) -> dict[str, Any]:
    """A JSON object reduced to what a listing can show: scalars as they are (strings cut), lists by their length, objects by their keys."""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, Any] = {}
    for k in sorted(value, key=str)[:EVIDENCE_KEYS]:
        v = value[k]
        if isinstance(v, str):
            out[str(k)] = v if len(v) <= TEXT_CUT else v[: TEXT_CUT - 1] + "…"
        elif v is None or isinstance(v, bool | int | float):
            out[str(k)] = v
        elif isinstance(v, Mapping):
            out[str(k)] = {"keys": sorted(str(x) for x in v)[:EVIDENCE_KEYS]}
        elif isinstance(v, list | tuple):
            out[str(k)] = {"items": len(v)}
        else:
            out[str(k)] = str(v)[:TEXT_CUT]
    if len(value) > EVIDENCE_KEYS:
        out["…"] = f"{len(value) - EVIDENCE_KEYS} more"
    return out


def _slot(market_key: Any, model_name: Any) -> str:
    return f"{market_key or '*'}/{model_name or '*'}"


def from_intel_promotion(row: Mapping[str, Any]) -> Promotion:
    """A row of ``intel.promotions`` (any entity)."""
    entity = str(row["entity"])
    criteria = row.get("criteria") or {}
    decision = str(row["to_role"])
    if entity == "model":
        code = criteria.get("model_code") if isinstance(criteria, Mapping) else None
        key, version = MODEL_CODE_KEY, None if code is None else str(code)
    elif entity == "agent":
        key, version = str(row["market_key"]), None if row.get("model_name") is None else str(row["model_name"])
    elif entity == "market_edge":
        key, version = _slot(row.get("market_key"), row.get("model_name")), None
    else:
        key = _slot(row.get("market_key"), row.get("model_name"))
        version = None if row.get("entity_id") is None else str(row["entity_id"])
    evidence = compact_evidence(criteria)
    if row.get("from_role") is not None:
        evidence["from_role"] = str(row["from_role"])
    if entity == "market_edge" and row.get("entity_id") is not None:
        evidence["calibrator_id"] = int(row["entity_id"])
    return Promotion(entity, key, version, decision, in_force_of(decision), str(row["decided_by"]), row["at"], str(row["gate_version"]),
                     str(row["reason"]), evidence, "intel.promotions", str(row["id"]))


def from_code_ledger(entry: CodePromotion, index: int) -> Promotion:
    """An entry of the model code's ledger (F12): a decision declared in code, not effective until it is on record in ``intel.promotions``."""
    evidence = compact_evidence(entry.evidence) | {"phase": entry.phase, "baseline": entry.baseline}
    return Promotion("model", MODEL_CODE_KEY, entry.fingerprint, "CHAMPION", True, entry.decided_by, entry.decided_at, code_ledger.GATE_VERSION,
                     entry.reason, evidence, CODE_LEDGER_SOURCE, str(index), effective=False)


def spec_fingerprint(spec: Any) -> str:
    """The version of a promoted goal spec: its own ``version`` and the first 12 hex digits of the sha256 of its canonical JSON."""
    body = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)
    label = spec.get("version") if isinstance(spec, Mapping) else None
    return f"{label or 'spec'}:{hashlib.sha256(body.encode()).hexdigest()[:12]}"


def from_goal_spec(row: Mapping[str, Any]) -> Promotion:
    """A row of ``analytics.promoted_forecast_spec``: each promotion replaces the spec in force (the newest row is the spec)."""
    evidence = compact_evidence(row.get("evidence")) | {"session_id": int(row["session_id"])}
    if row.get("previous_id") is not None:
        evidence["previous_id"] = int(row["previous_id"])
    return Promotion("goal_spec", GOAL_SPEC_KEY, spec_fingerprint(row.get("spec")), "PROMOTED", True, str(row["promoted_by"]), row["promoted_at"],
                     None, str(row["reason"]), evidence, "analytics.promoted_forecast_spec", str(row["id"]))


def from_neutral_rule(row: Mapping[str, Any]) -> Promotion:
    """A row of ``analytics.neutral_rule_promotion``: ``promote`` puts a rule version in force, ``retire`` switches the rule off."""
    decision = "PROMOTED" if row["action"] == "promote" else "RETIRED" if row["action"] == "retire" else str(row["action"]).upper()
    evidence = compact_evidence(row.get("evidence"))
    for k in ("run_id", "previous_id"):
        if row.get(k) is not None:
            evidence[k] = int(row[k])
    return Promotion("neutral_rule", NEUTRAL_KEY, None if row.get("rule_version") is None else str(row["rule_version"]), decision,
                     in_force_of(decision), str(row["promoted_by"]), row["promoted_at"], None, str(row["reason"]), evidence,
                     "analytics.neutral_rule_promotion", str(row["id"]))


def from_feature_gate(row: Mapping[str, Any]) -> Promotion:
    """A row of ``ai.feature_gates``: the evidence of one gate of the AI layer; the newest row of a gate decides whether it is open."""
    decision = "PASSED" if row["passed"] else "FAILED"
    raw = row.get("evidence") or {}
    gate_version = raw.get("version") if isinstance(raw, Mapping) and isinstance(raw.get("version"), str) else None
    evidence = compact_evidence(raw) | {"evidence_hash": str(row["evidence_hash"])}
    reason = raw.get("reason") if isinstance(raw, Mapping) and isinstance(raw.get("reason"), str) else f"gate {row['gate']} {decision.lower()}"
    return Promotion("ai_gate", str(row["gate"]), None if row.get("code_version") is None else str(row["code_version"]), decision,
                     in_force_of(decision), str(row["decided_by"]), row["at"], gate_version, str(reason)[:TEXT_CUT], evidence,
                     "ai.feature_gates", str(row["id"]))


# ── pure: reading the registry ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _sort_key(p: Promotion) -> tuple[datetime, str, int, str]:
    sid = int(p.source_id) if p.source_id.isdigit() else 0
    return (p.at, p.source_table, sid, p.source_id)


def ordered(records: Iterable[Promotion]) -> list[Promotion]:
    """Oldest first; ties by source and id (the order each ledger wrote them in)."""
    return sorted(records, key=_sort_key)


def as_of(records: Iterable[Promotion], at: datetime | None) -> list[Promotion]:
    return ordered(r for r in records if at is None or r.at <= at)


def history_of(records: Iterable[Promotion], entity_type: str, key: str, *, at: datetime | None = None) -> list[Promotion]:
    return [r for r in as_of(records, at) if r.entity_type == entity_type and r.entity_key == key]


def current_of(records: Iterable[Promotion], entity_type: str, key: str, *, at: datetime | None = None) -> Promotion | None:
    """The decision in force for one key at ``at`` (see the module for the rule of each kind). Only effective records count."""
    rows = [r for r in history_of(records, entity_type, key, at=at) if r.effective]
    if not rows:
        return None
    if entity_type not in BY_VERSION:
        return rows[-1]
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if r.in_force is not True:
            continue
        ended = any(later.version == r.version and later.in_force is False for later in rows[i + 1:])
        if not ended:
            return r
    return rows[-1]


def keys_of(records: Iterable[Promotion]) -> list[tuple[str, str]]:
    return sorted({(r.entity_type, r.entity_key) for r in records})


# ── SQL and reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

INTEL_SQL: Final = """
SELECT id, at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, reason, decided_by
  FROM intel.promotions ORDER BY at, id
"""
GOAL_SPEC_SQL: Final = """
SELECT id, session_id, promoted_at, promoted_by, reason, spec, previous_id, evidence
  FROM analytics.promoted_forecast_spec ORDER BY promoted_at, id
"""
NEUTRAL_SQL: Final = """
SELECT id, promoted_at, promoted_by, action, rule_version, reason, run_id, previous_id, evidence
  FROM analytics.neutral_rule_promotion ORDER BY promoted_at, id
"""
GATES_SQL: Final = """
SELECT id, gate, at, passed, evidence, evidence_hash, decided_by, code_version
  FROM ai.feature_gates WHERE gate <> 'switches' ORDER BY at, id
"""
"""Every gate but ``switches`` (a trace of configuration, not a decision: see the module)."""

SOURCES: Final = (("intel.promotions", INTEL_SQL, from_intel_promotion), ("analytics.promoted_forecast_spec", GOAL_SPEC_SQL, from_goal_spec),
                  ("analytics.neutral_rule_promotion", NEUTRAL_SQL, from_neutral_rule), ("ai.feature_gates", GATES_SQL, from_feature_gate))


def all_promotions(conn: psycopg.Connection[Any], *, at: datetime | None = None, ledger: Sequence[CodePromotion] | None = None,
                   entity_type: str | None = None) -> list[Promotion]:
    """Every record of every ledger (the code ledger's entries included, marked not effective), oldest first, as of ``at``."""
    records: list[Promotion] = []
    for _, sql, normalise in SOURCES:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            records.extend(normalise(r) for r in cur.fetchall())
    entries = code_ledger.LEDGER if ledger is None else ledger
    records.extend(from_code_ledger(e, i) for i, e in enumerate(entries))
    out = as_of(records, at)
    return out if entity_type is None else [r for r in out if r.entity_type == entity_type]


def history(conn: psycopg.Connection[Any], entity_type: str, key: str, *, at: datetime | None = None,
            ledger: Sequence[CodePromotion] | None = None) -> list[Promotion]:
    return history_of(all_promotions(conn, at=at, ledger=ledger), entity_type, key, at=at)


def current(conn: psycopg.Connection[Any], entity_type: str, key: str, *, at: datetime | None = None,
            ledger: Sequence[CodePromotion] | None = None) -> Promotion | None:
    return current_of(all_promotions(conn, at=at, ledger=ledger), entity_type, key, at=at)
