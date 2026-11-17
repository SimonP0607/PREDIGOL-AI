"""The registry of capabilities (IA-056, plan piece AD-003 of the definitive architecture 2026): what each capability of the plan is,
which state it is in and why.

THE STATES, in their one order: ``construida`` (built, off or not yet in shadow) -> ``en_sombra`` (it runs, nothing reaches a reader) ->
``lista_para_revision`` (its safety PASSED and its validation has a verdict: the owner may look at it) -> ``autorizada`` (the owner signed
it). Every move is a row of ``intel.capability_transitions`` (revision 0138, append-only) that names the row before it, with its SAFETY
verdict and its VALIDATION verdict - each with its evidence, and the validation with its sample.

THE RULES (``problems``; the database refuses the same ones, ``capability_transitions_*`` constraints):

1. No state is skipped forward: one step at a time. Going back (to any lower state) is always allowed, by the system or the owner, with a
   reason. A row in the same state records new verdicts.
2. ``autorizada`` needs the OWNER: ``decided_by = 'owner'``, the owner's signature (their own words) and a safety ``PASA``. The system can
   never write it, and nothing here promotes by itself: every row is written by a command a person ran (``scripts/ia_capabilities.py``).
3. Only safety stops a capability: a safety ``NO PASA`` keeps it at ``construida`` (no row above it may carry one), and ``lista_para_revision``
   needs a safety ``PASA``. A validation that is not favourable (``NO VALIDADO``, ``INSUFICIENTE``) is recorded as it is and blocks nothing:
   the capability is shown as not validated, never as validated.
4. A measured validation (``VALIDADO``, ``NO VALIDADO``, ``INSUFICIENTE``) carries its sample; a PASA or NO PASA, its evidence.
5. A forward move is refused while the newest row of a gate the capability answers to (``ai.feature_gates``: ``Capability.safety_gates``)
   says NO PASA, and so is a recorded safety PASA that contradicts it.

THE WORDS are the gates' own (``fbi.ai.gates_panel``): PASA, NO PASA, PENDIENTE POR ACCIONES MANUALES, PENDIENTE POR DEPENDENCIAS; and for
validation the board's (AD-K02): VALIDADO, NO VALIDADO, INSUFICIENTE.

It RECORDS and decides nothing: no switch, no gate, no agent, no pick and no reader reads the registry. Authorising a capability is a
signature, not a switch: turning anything on for readers is still the owner's change of its switch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

VERSION: Final = "capabilities-v1"
Json = dict[str, Any]

BUILT: Final = "construida"
SHADOW: Final = "en_sombra"
REVIEW: Final = "lista_para_revision"
AUTHORISED: Final = "autorizada"
STATES: Final[tuple[str, ...]] = (BUILT, SHADOW, REVIEW, AUTHORISED)
"""In their one order. ``STATES.index`` is the rank a forward move climbs by one."""
FIRST_STATES: Final = frozenset({BUILT, SHADOW})
"""Where a capability can enter the registry: built, or - for what already ran in shadow before the registry existed - in shadow."""

PASS: Final = "PASA"
FAIL: Final = "NO PASA"
PENDING_ACTIONS: Final = "PENDIENTE POR ACCIONES MANUALES"
PENDING_DEPENDENCIES: Final = "PENDIENTE POR DEPENDENCIAS"
SAFETY: Final[tuple[str, ...]] = (PASS, FAIL, PENDING_ACTIONS, PENDING_DEPENDENCIES)
VALIDATED: Final = "VALIDADO"
NOT_VALIDATED: Final = "NO VALIDADO"
INSUFFICIENT: Final = "INSUFICIENTE"
VALIDATION: Final[tuple[str, ...]] = (VALIDATED, NOT_VALIDATED, INSUFFICIENT, PENDING_ACTIONS, PENDING_DEPENDENCIES)
MEASURED: Final = frozenset({VALIDATED, NOT_VALIDATED, INSUFFICIENT})
"""Validation words that come from a measurement, and so carry a sample."""

DecidedBy = Literal["system", "owner"]
SIGNATURE_MIN: Final = 10
SIGNATURE_MAX: Final = 600
REASON_MAX: Final = 600
AGENT_WINDOW: Final = timedelta(days=7)
"""The window of the agents' runs the console reads beside each capability."""


@dataclass(frozen=True, slots=True)
class Capability:
    """One entry of the catalog. ``safety_gates`` and ``validation_gates`` name rows of ``ai.feature_gates`` the console reads beside
    the recorded verdicts (and a forward move respects); ``agents`` names rows of ``ai.agent_runs``. ``switch`` is None for a job of the
    worker that has none."""

    key: str
    piece: str
    title: str
    description: str
    switch: str | None
    components: tuple[str, ...]
    safety_gates: tuple[str, ...] = ()
    validation_gates: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()

    def entry(self) -> Json:
        """What ``intel.capabilities`` keeps of it (the readings are code, not catalog)."""
        return {"key": self.key, "piece": self.piece, "title": self.title, "description": self.description, "switch": self.switch,
                "components": list(self.components)}


CATALOG: Final[tuple[Capability, ...]] = (
    Capability("research_v2", "AD-C05", "Research v2: investigación por entidad y tema",
               "Busca y extrae afirmaciones tipadas por entidad y tema (extract-v3, claim-v1) detrás de la puerta untrusted-v3, "
               "al lado de la investigación v1; lo que escribe no mueve ningún estado, paquete ni pick de v1.",
               "FBI_AI_RESEARCH_V2", ("extract-v3", "claim-v1"), safety_gates=("battery",), validation_gates=("research_v2",)),
    Capability("readers", "AD-D09", "Lectores especialistas: Partido y Estadísticas",
               "Los agentes de Partido y de Estadísticas leen el paquete del partido y alimentan al Council solo dentro de la sombra.",
               "FBI_AI_AGENTS", ("match-v5", "stats-v4"), safety_gates=("battery",), agents=("match", "stats")),
    Capability("council", "AD-D10", "Council: juez council-v1 sobre council-protocol-v1",
               "El juez del Council y su protocolo por reglas deciden la revisión del motor de sombra ma-v1 (FBI_AI_ENGINES); "
               "nunca suben un estado ni tocan números.",
               "FBI_AI_AGENTS", ("council-v1", "council-protocol-v1", "ma-v1"), safety_gates=("battery",), agents=("council",)),
    Capability("haiku_arm", "AD-D10", "Brazo Haiku del Council (ma-v1-h)",
               "El mismo camino del Council con el modelo pequeño, como brazo de comparación; se retira cuando cumpla su criterio.",
               "FBI_AI_ENGINES", ("ma-v1-h",), safety_gates=("battery",)),
    Capability("family_decisions", "AD-B07", "Familias de conteos: córners, tarjetas y goles por mitad",
               "Las familias deciden en sombra con versiones propias (decision-fam-v1) que ningún pick, filtro ni lector usa.",
               "FBI_FAMILY_DECISIONS", ("decision-fam-v1",)),
    Capability("attribution", "AD-K03", "Atribución de la sombra (attr-v1)",
               "Clasifica por código qué agente y versión acertó o falló en los partidos terminados; no cambia nada de lo que decide.",
               "FBI_AI_PM_REVIEWER", ("attr-v1",)),
    Capability("chronicle_review", "AD-F06", "Revisión posterior de la crónica (chronicle-review-v1)",
               "Contrasta la crónica de cada partido terminado con lo que pasó; solo base de datos, sin modelo ni coste; nadie la lee "
               "para decidir.",
               None, ("chronicle-review-v1",)),
)
"""Every capability of the plan the registry knows. The first seven are the ones that already ran in shadow on 16 Nov 2026 (seeded by
revision 0138 at ``en_sombra``); a piece that builds a new one adds it here, and ``scripts/ia_capabilities.py sync --write`` registers it
at ``construida``."""
BY_KEY: Final[Mapping[str, Capability]] = {c.key: c for c in CATALOG}


def evidence_hash(document: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON (sorted keys, no spaces): the same verdicts and evidence, the same hash (revision 0138 uses the
    same function for its seed)."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def rank(state: str) -> int:
    return STATES.index(state)


@dataclass(frozen=True, slots=True)
class Tip:
    """The newest row of a capability's chain."""

    id: int
    state: str
    safety: str
    validation: str
    validation_sample: int | None
    at: datetime
    decided_by: str


@dataclass(frozen=True, slots=True)
class Proposal:
    """A row to append: a move (or new verdicts in the same state)."""

    key: str
    to_state: str
    safety: str
    validation: str
    reason: str
    safety_evidence: Json = field(default_factory=dict)
    validation_evidence: Json = field(default_factory=dict)
    validation_sample: int | None = None
    observed: Json = field(default_factory=dict)
    decided_by: DecidedBy = "system"
    owner_signature: str | None = None

    def document(self) -> Json:
        return {"safety": self.safety, "safety_evidence": self.safety_evidence, "validation": self.validation,
                "validation_evidence": self.validation_evidence, "validation_sample": self.validation_sample, "reason": self.reason,
                "observed": self.observed}


def problems(tip: Tip | None, p: Proposal, *, live_safety: Mapping[str, str] | None = None) -> list[str]:
    """Why ``p`` may not follow ``tip`` (empty: it may). Pure. ``live_safety`` is the newest verdict of each gate the capability answers
    to (``PASA`` / ``NO PASA``); a gate without a row is not in it."""
    out: list[str] = []
    if p.key not in BY_KEY:
        out.append(f"unknown capability {p.key!r} (it is not in the catalog of fbi.intel.capabilities)")
    if p.to_state not in STATES:
        return [*out, f"unknown state {p.to_state!r}: one of {', '.join(STATES)}"]
    if p.safety not in SAFETY:
        out.append(f"unknown safety verdict {p.safety!r}: one of {', '.join(SAFETY)}")
    if p.validation not in VALIDATION:
        out.append(f"unknown validation verdict {p.validation!r}: one of {', '.join(VALIDATION)}")
    reason = p.reason.strip()
    if not reason or len(reason) > REASON_MAX:
        out.append(f"a row needs its reason (1 to {REASON_MAX} characters)")
    if p.decided_by not in ("system", "owner"):
        out.append(f"decided_by is 'system' or 'owner', not {p.decided_by!r}")
    signed = p.owner_signature is not None and SIGNATURE_MIN <= len(p.owner_signature.strip()) <= SIGNATURE_MAX
    if p.decided_by == "owner" and not signed:
        out.append(f"the owner's row carries the owner's signature, in their own words ({SIGNATURE_MIN} to {SIGNATURE_MAX} characters)")
    if p.decided_by == "system" and p.owner_signature is not None:
        out.append("a row of the system carries no signature: only the owner signs")
    if tip is None:
        if p.to_state not in FIRST_STATES:
            out.append(f"a capability enters the registry at {BUILT} or {SHADOW}, not at {p.to_state}")
    elif rank(p.to_state) > rank(tip.state) + 1:
        out.append(f"no state is skipped: from {tip.state} the next one is {STATES[rank(tip.state) + 1]}, not {p.to_state}")
    if p.to_state == AUTHORISED and p.decided_by != "owner":
        out.append(f"{AUTHORISED} is the owner's alone: it needs --confirm-owner and the owner's signature")
    if p.to_state != BUILT and p.safety == FAIL:
        out.append(f"a safety {FAIL} keeps the capability at {BUILT}: no row above it may carry one")
    if p.to_state in (REVIEW, AUTHORISED) and p.safety != PASS:
        out.append(f"{p.to_state} needs a safety {PASS}, not {p.safety}")
    if p.safety in (PASS, FAIL) and not p.safety_evidence:
        out.append(f"a safety {p.safety} carries its evidence")
    if p.validation in MEASURED and (p.validation_sample is None or p.validation_sample < 0):
        out.append(f"a validation {p.validation} carries its sample (a whole number, 0 or more)")
    if p.validation in MEASURED and not p.validation_evidence:
        out.append(f"a validation {p.validation} carries its evidence")
    forward = tip is None or (p.to_state in STATES and rank(p.to_state) > rank(tip.state))
    failing = sorted(g for g, v in (live_safety or {}).items() if v == FAIL)
    if failing and forward and p.to_state != BUILT:
        out.append(f"the newest row of {', '.join(failing)} (ai.feature_gates) says {FAIL}: no forward move while it does")
    if failing and p.safety == PASS:
        out.append(f"a safety {PASS} contradicts the newest row of {', '.join(failing)} (ai.feature_gates), which says {FAIL}")
    return out


# ── the database ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

CATALOG_SQL: Final = """
    SELECT DISTINCT ON (key) id, key, version, piece, title, description, switch, components, registered_at, registered_by
      FROM intel.capabilities ORDER BY key, version DESC"""
TIPS_SQL: Final = """
    SELECT DISTINCT ON (capability_key) id, capability_key, to_state, safety, safety_evidence, validation, validation_evidence,
           validation_sample, observed, reason, decided_by, owner_signature IS NOT NULL AS signed, at, evidence_hash
      FROM intel.capability_transitions ORDER BY capability_key, id DESC"""
COUNTS_SQL: Final = "SELECT capability_key, count(*) AS n FROM intel.capability_transitions GROUP BY 1"
HISTORY_SQL: Final = """
    SELECT id, previous_id, at, from_state, to_state, safety, validation, validation_sample, reason, decided_by,
           owner_signature IS NOT NULL AS signed, evidence_hash
      FROM intel.capability_transitions WHERE capability_key = %s ORDER BY id"""
GATES_SQL: Final = """
    SELECT DISTINCT ON (gate) gate, id, at, passed FROM ai.feature_gates WHERE gate = ANY(%s) ORDER BY gate, at DESC, id DESC"""
AGENTS_SQL: Final = """
    SELECT agent, agent_version, status, count(*) AS n FROM ai.agent_runs
     WHERE agent = ANY(%(agents)s) AND started_at >= %(since)s GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"""
INSERT_CATALOG_SQL: Final = """
    INSERT INTO intel.capabilities (key, version, supersedes, piece, title, description, switch, components, registered_at,
                                    registered_by, code_version)
    VALUES (%(key)s, %(version)s, %(supersedes)s, %(piece)s, %(title)s, %(description)s, %(switch)s, %(components)s, %(at)s,
            %(by)s, %(code)s) RETURNING id"""
INSERT_SQL: Final = """
    INSERT INTO intel.capability_transitions (capability_key, capability_id, previous_id, at, from_state, to_state, safety,
        safety_evidence, validation, validation_evidence, validation_sample, observed, reason, decided_by, owner_signature,
        code_version, evidence_hash)
    VALUES (%(key)s, %(capability_id)s, %(previous_id)s, %(at)s, %(from_state)s, %(to_state)s, %(safety)s, %(safety_evidence)s,
            %(validation)s, %(validation_evidence)s, %(sample)s, %(observed)s, %(reason)s, %(by)s, %(signature)s, %(code)s,
            %(hash)s) RETURNING id"""


def _rows(conn: psycopg.Connection[Any], query: str, params: Any = None) -> list[Json]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def catalog_rows(conn: psycopg.Connection[Any]) -> dict[str, Json]:
    """The newest version of every entry of ``intel.capabilities``, by key."""
    return {str(r["key"]): r for r in _rows(conn, CATALOG_SQL)}


def tips(conn: psycopg.Connection[Any]) -> dict[str, Json]:
    """The newest row of every capability's chain, by key."""
    return {str(r["capability_key"]): r for r in _rows(conn, TIPS_SQL)}


def tip_of(row: Mapping[str, Any] | None) -> Tip | None:
    if row is None:
        return None
    return Tip(int(row["id"]), str(row["to_state"]), str(row["safety"]), str(row["validation"]),
               None if row["validation_sample"] is None else int(row["validation_sample"]), row["at"], str(row["decided_by"]))


def live_gates(conn: psycopg.Connection[Any], gates: Sequence[str]) -> dict[str, Json]:
    """The newest row of each of these gates of ``ai.feature_gates`` (a gate without one is absent), in the gates' words."""
    if not gates:
        return {}
    return {str(r["gate"]): {"gate": r["gate"], "row": int(r["id"]), "at": _iso(r["at"]),
                             "verdict": PASS if r["passed"] else FAIL} for r in _rows(conn, GATES_SQL, (list(gates),))}


def sync_plan(rows: Mapping[str, Mapping[str, Any]]) -> list[tuple[Capability, int | None, int]]:
    """Pure: the entries of the code catalog whose newest stored version is missing or differs - with the id it supersedes (None: a new
    capability) and the version it becomes."""
    plan: list[tuple[Capability, int | None, int]] = []
    for cap in CATALOG:
        stored = rows.get(cap.key)
        if stored is None:
            plan.append((cap, None, 1))
            continue
        kept = {"key": stored["key"], "piece": stored["piece"], "title": stored["title"], "description": stored["description"],
                "switch": stored["switch"], "components": list(stored["components"] or [])}
        if kept != cap.entry():
            plan.append((cap, int(stored["id"]), int(stored["version"]) + 1))
    return plan


def sync(conn: psycopg.Connection[Any], *, at: datetime, code_version: str | None = None) -> list[Json]:
    """Register what the code catalog has and the database does not (the caller commits): a new version of a changed entry (it names the
    one it replaces), and a NEW capability enters at ``construida`` decided by the system. It never moves the state of one already there."""
    done: list[Json] = []
    chains = tips(conn)
    for cap, supersedes, version in sync_plan(catalog_rows(conn)):
        with conn.cursor() as cur:
            cur.execute(INSERT_CATALOG_SQL, {**cap.entry(), "version": version, "supersedes": supersedes,
                                             "components": list(cap.components), "at": at, "by": "system", "code": code_version})
            row = cur.fetchone()
        assert row is not None
        item: Json = {"key": cap.key, "catalog_id": int(row[0]), "version": version}
        if cap.key not in chains:
            p = Proposal(cap.key, BUILT, PENDING_ACTIONS, PENDING_DEPENDENCIES,
                         "Registro de una capacidad nueva al desplegarse su código: construida, sin veredictos todavía.")
            item["transition_id"] = _insert(conn, p, None, int(row[0]), at=at, code_version=code_version)
        done.append(item)
    return done


def _insert(conn: psycopg.Connection[Any], p: Proposal, tip: Tip | None, capability_id: int, *, at: datetime,
            code_version: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {"key": p.key, "capability_id": capability_id, "previous_id": None if tip is None else tip.id, "at": at,
                                 "from_state": None if tip is None else tip.state, "to_state": p.to_state, "safety": p.safety,
                                 "safety_evidence": Jsonb(p.safety_evidence), "validation": p.validation,
                                 "validation_evidence": Jsonb(p.validation_evidence), "sample": p.validation_sample,
                                 "observed": Jsonb(p.observed), "reason": p.reason.strip(), "by": p.decided_by,
                                 "signature": None if p.owner_signature is None else p.owner_signature.strip(), "code": code_version,
                                 "hash": evidence_hash(p.document())})
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def record(conn: psycopg.Connection[Any], p: Proposal, *, at: datetime, confirmed_by_owner: bool = False,
           code_version: str | None = None) -> int:
    """Append ``p`` after the newest row of its capability (the caller commits). Refuses (``ValueError``, nothing written) whatever
    ``problems`` names; an owner's row without the owner's explicit confirmation is a ``PermissionError``. Two writers that read the same
    newest row cannot both add the next: the database lets a row have one successor."""
    if (p.decided_by == "owner" or p.to_state == AUTHORISED) and not confirmed_by_owner:
        raise PermissionError(f"{AUTHORISED} and every row of the owner need the owner's explicit confirmation (--confirm-owner)")
    stored = catalog_rows(conn).get(p.key)
    if stored is None:
        raise ValueError(f"{p.key!r} is not registered: run sync --write first")
    tip = tip_of(tips(conn).get(p.key))
    cap = BY_KEY.get(p.key)
    live = {g: str(v["verdict"]) for g, v in live_gates(conn, cap.safety_gates if cap else ()).items()}
    found = problems(tip, p, live_safety=live)
    if found:
        raise ValueError("; ".join(found))
    return _insert(conn, p, tip, int(stored["id"]), at=at, code_version=code_version)


def history(conn: psycopg.Connection[Any], key: str) -> list[Json]:
    return _rows(conn, HISTORY_SQL, (key,))


def _verdicts(row: Mapping[str, Any] | None) -> tuple[Json, Json]:
    if row is None:
        return ({"verdict": None, "evidence": None}, {"verdict": None, "sample": None, "evidence": None})
    return ({"verdict": row["safety"], "evidence": row["safety_evidence"]},
            {"verdict": row["validation"], "sample": row["validation_sample"], "evidence": row["validation_evidence"]})


def warnings_for(state: str | None, safety: str | None, validation: str | None, live: Mapping[str, Mapping[str, Any]],
                 validation_live: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """What the console says beside a capability (pure): never a reason to read it as better than it is."""
    out: list[str] = []
    if state is None:
        out.append("sin registrar: falta `python -m scripts.ia_capabilities sync --write`")
        return out
    for gate, g in sorted(live.items()):
        if g["verdict"] == FAIL:
            out.append(f"seguridad: la última fila de {gate} (ai.feature_gates, fila {g['row']}) dice {FAIL}; no puede avanzar")
    for gate, g in sorted(validation_live.items()):
        if g["verdict"] == FAIL:
            out.append(f"validación: la última fila de {gate} (ai.feature_gates, fila {g['row']}) dice {FAIL}")
    if safety in (PENDING_ACTIONS, PENDING_DEPENDENCIES):
        out.append(f"seguridad sin juzgar por el registro ({safety})")
    if validation != VALIDATED:
        out.append(f"no validada ({validation})")
    return out


def overview(conn: psycopg.Connection[Any], *, at: datetime) -> Json:
    """THE REGISTRY for the Admin Console (read-only): every capability of the code catalog with its stored entry, its state, its two
    recorded verdicts (validation with its sample), the newest rows of the gates it answers to, its agents' runs of the last seven days and
    what the console must say beside it. Decides nothing."""
    stored, chains = catalog_rows(conn), tips(conn)
    counts = {str(r["capability_key"]): int(r["n"]) for r in _rows(conn, COUNTS_SQL)}
    gates = sorted({g for c in CATALOG for g in (*c.safety_gates, *c.validation_gates)})
    live = live_gates(conn, gates)
    agents = sorted({a for c in CATALOG for a in c.agents})
    runs: dict[str, list[Json]] = {}
    if agents:
        for r in _rows(conn, AGENTS_SQL, {"agents": agents, "since": at - AGENT_WINDOW}):
            runs.setdefault(str(r["agent"]), []).append({"version": r["agent_version"], "status": r["status"], "runs": int(r["n"])})
    items: list[Json] = []
    for cap in CATALOG:
        entry, tip = stored.get(cap.key), chains.get(cap.key)
        safety, validation = _verdicts(tip)
        safety_live = {g: live[g] for g in cap.safety_gates if g in live}
        validation_live = {g: live[g] for g in cap.validation_gates if g in live}
        items.append({
            "key": cap.key, "piece": cap.piece, "title": cap.title, "description": cap.description, "switch": cap.switch,
            "components": list(cap.components),
            "catalog_version": None if entry is None else int(entry["version"]),
            "registered_at": None if entry is None else _iso(entry["registered_at"]),
            "state": None if tip is None else tip["to_state"],
            "since": None if tip is None else _iso(tip["at"]),
            "decided_by": None if tip is None else tip["decided_by"],
            "signed_by_owner": False if tip is None else bool(tip["signed"]),
            "reason": None if tip is None else tip["reason"],
            "observed": None if tip is None else tip["observed"],
            "safety": safety, "validation": validation,
            "transitions": counts.get(cap.key, 0),
            "live": {"safety_gates": [safety_live.get(g, {"gate": g, "row": None, "at": None, "verdict": None}) for g in cap.safety_gates],
                     "validation_gates": [validation_live.get(g, {"gate": g, "row": None, "at": None, "verdict": None})
                                          for g in cap.validation_gates],
                     "agent_runs_7d": {a: runs.get(a, []) for a in cap.agents}},
            "warnings": warnings_for(None if tip is None else str(tip["to_state"]), safety["verdict"], validation["verdict"],
                                     safety_live, validation_live),
        })
    unknown = sorted(set(stored) - set(BY_KEY))
    by_state = {s: sum(1 for i in items if i["state"] == s) for s in STATES}
    return {"version": VERSION, "at": _iso(at), "decides": False, "states": list(STATES), "safety_words": list(SAFETY),
            "validation_words": list(VALIDATION), "by_state": by_state,
            "unregistered": [i["key"] for i in items if i["state"] is None], "not_in_code": unknown, "capabilities": items,
            "note": ("El registro anota y no decide: ningún interruptor, gate, agente, pick ni lector lo lee. «autorizada» es la firma "
                     "del dueño; encender algo para lectores sigue siendo su cambio de interruptor.")}
