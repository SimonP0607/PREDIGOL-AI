"""The five optimisations of Phase 0 (Plan Maestro IA, sections 19, 26, 28, 29), each behind a switch and, where it can change
what the layer reads or answers, behind EVIDENCE.

A switch is the owner's (``config.SWITCH_ENV``): ``off`` = rolled back, ``on`` = forced, ``auto`` (the default) = on once the
evidence of its own gate allows it:

    cache           auto = on. A cache only changes what a call is BILLED (the same tokens are read), never what it answers.
    brief_material  auto = on. A brief is paid again only for a material change (``fbi.ai.material``).
    budget_v3       auto = on. The adaptive budget of section 26 (``fbi.ai.budget_v3``).
    batch           auto = needs the ``batch`` gate: a real probe of the Message Batches API in the LAB workspace.
    native_schema   auto = needs the ``native_schema`` gate: structured outputs agree with the forced tool call on stored packets.

The shared match block of the cache layout (the same bytes first, what varies last) always needs its own ``cache_layout`` gate -
not even ``on`` skips it: it is the one change of Phase 0 that reorders what a model reads.

The evidence is a row of ``ai.feature_gates`` (append-only, written by ``scripts/ia_probe.py`` and ``scripts/ia_equivalence.py`` from
measurements, never by hand): the NEWEST row of a gate decides, so a failing re-run switches the optimisation off again. A row may
name the ``models`` it was measured with; another model is not covered by it.

Nothing here reads a key and nothing changes a probability, a threshold or a pick."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.config import SWITCH_ENV, AiSettings

GATES = ("batch", "native_schema", "cache_layout", "gate_a")
AUTO_WITHOUT_EVIDENCE: dict[str, bool] = {"cache": True, "brief_material": True, "budget_v3": True, "batch": False,
                                          "native_schema": False}
"""What ``auto`` means for each switch when no gate is needed (True) or one is (False)."""
GATE_OF: dict[str, str] = {"batch": "batch", "native_schema": "native_schema"}
"""The gate whose evidence an ``auto`` switch waits for."""

STATE_SQL = "SELECT at, passed, evidence, evidence_hash FROM ai.feature_gates WHERE gate = %s ORDER BY at DESC, id DESC LIMIT 1"
INSERT_SQL = ("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by, code_version) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id")


@dataclass(frozen=True, slots=True)
class GateState:
    gate: str
    passed: bool
    at: datetime | None = None
    evidence_hash: str | None = None
    models: tuple[str, ...] | None = None
    """The models the evidence was measured with; None = it does not name any (it covers every model)."""

    def covers(self, model: str | None) -> bool:
        return self.passed and (self.models is None or (model is not None and model in self.models))

    def as_json(self) -> dict[str, Any]:
        return {"gate": self.gate, "passed": self.passed, "at": None if self.at is None else self.at.isoformat(),
                "evidence_hash": self.evidence_hash, "models": None if self.models is None else list(self.models)}


def evidence_hash(evidence: dict[str, Any]) -> str:
    """sha256 of the evidence in its canonical JSON (sorted keys, no spaces): the same measurements, the same hash."""
    text = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def gate_state(conn: psycopg.Connection[Any], gate: str) -> GateState:
    """The newest evidence of a gate; no row = not passed."""
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STATE_SQL, (gate,))
        row = cur.fetchone()
    if row is None:
        return GateState(gate, False)
    models = row["evidence"].get("models") if isinstance(row["evidence"], dict) else None
    named = tuple(str(m) for m in models) if isinstance(models, list) and models else None
    return GateState(gate, bool(row["passed"]), row["at"], str(row["evidence_hash"]), named)


def record_gate(conn: psycopg.Connection[Any], *, gate: str, passed: bool, evidence: dict[str, Any], at: datetime,
                decided_by: str = "script", code_version: str | None = None) -> int:
    """Append the evidence of a gate (the caller commits). Returns the row's id."""
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}")
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, (gate, at, passed, Jsonb(evidence), evidence_hash(evidence), decided_by, code_version))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def enabled(conn: psycopg.Connection[Any], settings: AiSettings, name: str, *, model: str | None = None) -> bool:
    """Whether an optimisation is in force now: the owner's switch, then (for ``auto``) its evidence. An unknown name is off."""
    if name not in SWITCH_ENV:
        return False
    mode = settings.switch(name)
    if mode == "off":
        return False
    if mode == "on" or AUTO_WITHOUT_EVIDENCE.get(name, False):
        return True
    gate = GATE_OF.get(name)
    return gate is not None and gate_state(conn, gate).covers(model)


def layout_shared(conn: psycopg.Connection[Any], settings: AiSettings, *, model: str | None = None) -> bool:
    """Whether the match block goes FIRST and shared (cached for 5 minutes) with what varies after it: the cache is not off and the
    ``cache_layout`` gate has passed for the model. ``FBI_AI_CACHE=on`` forces the cache of the system block, not this."""
    return settings.switch("cache") != "off" and gate_state(conn, "cache_layout").covers(model)


def describe(conn: psycopg.Connection[Any], settings: AiSettings) -> dict[str, Any]:
    """What each optimisation is doing and why - for the admin panel and the run reports. Names and states only."""
    states = {g: gate_state(conn, g) for g in GATES}
    out: dict[str, Any] = {}
    for name in SWITCH_ENV:
        mode = settings.switch(name)
        gate = GATE_OF.get(name)
        if mode == "off":
            on, why = False, f"rolled back by the owner ({SWITCH_ENV[name]}=0)"
        elif mode == "on":
            on, why = True, "forced on by the owner"
        elif AUTO_WITHOUT_EVIDENCE.get(name, False):
            on, why = True, "on by default: it changes what is billed or reused, never a verdict"
        elif gate is not None and states[gate].passed:
            on, why = True, f"the {gate} gate passed"
        else:
            on, why = False, f"waiting for the {gate} gate's evidence"
        out[name] = {"mode": mode, "on": on, "why": why, "gate": gate}
    out["cache_layout"] = {"mode": settings.switch("cache"), "on": settings.switch("cache") != "off"
                           and states["cache_layout"].passed, "gate": "cache_layout",
                           "why": "the shared match block needs the cache_layout gate"}
    out["gates"] = {g: s.as_json() for g, s in states.items()}
    return out
