"""The regression test of the bank over what it already collected (IA-136, AD-K04): read, judge, and - only with the owner's signed
tolerance - append the verdict to ``ai.replay_assessments`` (method ``replay-regression-v1``, protocol ``AD-K04``). It asks no model and
pays nothing: the answers are the ones ``harness.collect`` kept.

    check    per scope: the INT-C02 measure, the regression verdict (``regression.judge``), its cause (``regression.diagnose``), the
             version measured against the version in force (``regression.due``). Read only.
    record   the same, appended one row per scope that has nothing on its way - refused when the owner has not signed the tolerance
             (``signed``, checked by the owner's command against the registry of IA-139), or when an earlier regression row of the scope
             and variant used any of the same stored runs (``regression.admissible``: no repeating to change a verdict).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.agents.registry import REGISTRY, RegistryError
from fbi.ai.replay import SAME, VERSION, harness, measure, regression

STRATA_SQL: Final = """
SELECT b.source_run_id, b.scope, b.stored_in_batch, b.model AS stored_model, b.agent_version, r.repetition, r.model AS replay_model
  FROM ai.replay_bank_items b
  LEFT JOIN ai.replay_results r ON r.bank_item_id = b.id AND r.variant = %(variant)s
 WHERE b.bank_version = %(bank)s AND b.admitted AND b.source_run_id = ANY(%(runs)s)
 ORDER BY b.source_run_id, r.repetition
"""
EARLIER_SQL: Final = """
SELECT id, evidence -> 'runs' AS runs FROM ai.replay_assessments
 WHERE bank_version = %(bank)s AND variant = %(variant)s AND scope = %(scope)s AND method = %(method)s
 ORDER BY at, id
"""


def _agent_of(scope: str) -> str:
    return scope.split("/", 1)[0]


def in_force(scopes: list[str]) -> dict[str, str]:
    """The version in force of the agent of each scope (the Council's judge for its arms); a scope whose agent the registry does not
    know is left out."""
    out: dict[str, str] = {}
    for s in scopes:
        try:
            out[s] = REGISTRY.in_force(_agent_of(s)).version
        except RegistryError:
            continue
    return out


def strata(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, regression.Strata], dict[str, str]]:
    """Per scope, the route and the model of each stored run, and the version the scope measured (the most common one of its runs)."""
    route: dict[str, dict[int, str]] = defaultdict(dict)
    model: dict[str, dict[int, list[bool | None]]] = defaultdict(dict)
    versions: dict[str, Counter[str]] = defaultdict(Counter)
    seen: set[int] = set()
    for r in rows:
        scope, run = str(r["scope"]), int(r["source_run_id"])
        route[scope][run] = "batch" if r["stored_in_batch"] else "tiempo_real"
        if run not in seen:
            versions[scope][str(r["agent_version"])] += 1
            seen.add(run)
        slots = model[scope].setdefault(run, [None, None])
        rep = r.get("repetition")
        if rep in (1, 2):
            slots[int(rep) - 1] = regression.same_model(r["stored_model"], r["replay_model"])
    out = {s: regression.Strata(route[s], {i: (v[0], v[1]) for i, v in model[s].items()}) for s in route}
    return out, {s: c.most_common(1)[0][0] for s, c in versions.items()}


def earlier(conn: psycopg.Connection[Any], *, variant: str, scope: str) -> list[list[int]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EARLIER_SQL, {"bank": VERSION, "variant": variant, "scope": scope, "method": regression.METHOD})
        return [[int(x) for x in (r["runs"] or [])] for r in cur.fetchall()]


def check(conn: psycopg.Connection[Any], *, variant: str = SAME, draws: int = measure.BOOTSTRAP) -> dict[str, Any]:
    """The regression verdict of every scope the bank collected answers for. Writes nothing."""
    from fbi.research import protocol

    held = harness.held_items(conn, variant=variant)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(harness.RESULTS_SQL, {"bank": VERSION, "variant": variant})
        rows = [dict(r) for r in cur.fetchall()]
        runs = sorted({k[0] for k in held.newest} | {int(r["source_run_id"]) for r in rows})
        cur.execute(harness.STORED_SQL, {"bank": VERSION, "runs": runs})
        stored = {int(r["source_run_id"]): dict(r) for r in cur.fetchall()}
        cur.execute(STRATA_SQL, {"bank": VERSION, "variant": variant, "runs": runs})
        split, measured = strata([dict(r) for r in cur.fetchall()])
    try:
        stamp: dict[str, Any] | None = protocol.stamp(regression.PROTOCOL_KEY)
    except LookupError:
        stamp = None
    scopes = harness.scope_units(rows, stored, held)
    out: dict[str, Any] = {"method": regression.METHOD, "bank": VERSION, "variant": variant, "protocol": stamp,
                           "tolerance": regression.TOLERANCE, "tolerance_status": regression.TOLERANCE_STATUS, "scopes": {},
                           "due": regression.due(measured, in_force(sorted(set(measured) | set(scopes)))), "decides": False}
    for name, scope in sorted(scopes.items()):
        answers = scope.answers()
        assessed = measure.assess(scope.units, answers, draws=draws)
        verdict = regression.judge(assessed)
        entry: dict[str, Any] = {"assessment": assessed, "regression": verdict, "measured_version": measured.get(name),
                                 "runs": regression.run_ids(scope.units)}
        if verdict["verdict"] == regression.FAIL:
            entry["diagnosis"] = regression.diagnose(scope.units, split.get(name, regression.Strata({}, {})),
                                                     replays_invalid=regression.invalid_fails(assessed), draws=draws)
        out["scopes"][name] = entry
    return out


def record(conn: psycopg.Connection[Any], report: Mapping[str, Any], *, at: datetime, signed: bool) -> dict[str, Any]:
    """Append the regression verdict of each scope with nothing on its way (the caller commits). Refused without the owner's signed
    tolerance; a scope whose runs an earlier regression row already used is not written, and is said so."""
    if not signed:
        raise PermissionError("the tolerance of AD-K04 is a proposal until the owner signs it (scripts/ia_replay_regression.py propose, "
                              "then scripts/ia_proposals.py sign)")
    stamp = report.get("protocol")
    if not isinstance(stamp, Mapping):
        raise LookupError("the protocol AD-K04 is not registered")
    variant = str(report["variant"])
    written: dict[str, int | None] = {}
    refused: dict[str, list[int]] = {}
    for scope, entry in sorted((report.get("scopes") or {}).items()):
        if entry["assessment"].get("open"):
            continue
        allowed, reused = regression.admissible(entry["runs"], earlier(conn, variant=variant, scope=scope))
        if not allowed:
            refused[scope] = reused[:20]
            continue
        evidence = {"bank": VERSION, "variant": variant, "scope": scope, "method": regression.METHOD, "protocol": dict(stamp),
                    "tolerance": regression.TOLERANCE, "runs": entry["runs"], "regression": entry["regression"],
                    "assessment": entry["assessment"], "diagnosis": entry.get("diagnosis"),
                    "measured_version": entry.get("measured_version")}
        digest = measure.evidence_hash(evidence)
        with conn.cursor() as cur:
            cur.execute(harness.ASSESSMENT_SQL, {"at": at, "bank": VERSION, "variant": variant, "scope": scope,
                                                 "protocol": stamp["version"], "fingerprint": stamp["fingerprint"],
                                                 "method": regression.METHOD, "verdict": entry["regression"]["verdict"],
                                                 "evidence": Jsonb(evidence), "hash": digest})
            row = cur.fetchone()
        written[scope] = None if row is None else int(row[0])
    return {"written": written, "refused_reused_runs": refused}


__all__ = ["EARLIER_SQL", "STRATA_SQL", "check", "earlier", "in_force", "record", "strata"]
