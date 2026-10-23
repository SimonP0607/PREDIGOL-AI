"""The registry of context factors (plan F6, pre-match v3): is what PrediGol says about a match a DESCRIPTION, or has an experiment
shown that it adds something?

The weighted head-to-head, what a match alone does to its table and to its tie, the observable tactics of each side, and the rest and
congestion read from the calendar in every competition are context. They reach the AI's packet and the admin's page so that the brief
can reason about them and a person can check them. They read like evidence, and nobody has tested any of them. This module keeps the
answer apart from the data, in the one place a person can read and change it: ``intel.context_factors`` (revision 0088).

* A factor is DESCRIPTIVE - PrediGol can say it, no model reads it (``tests/unit/test_context_isolation.py``) and the AI may not use it
  to move a probability or to claim an edge - until a person decides it is VALIDATED. Every factor starts DESCRIPTIVE: no row means
  DESCRIPTIVE.
* A validation is about ONE computation. The registry is keyed by (factor, version), the version being the one of the code that
  computes the factor (``CATALOGUE``): changing a weight or a rule bumps that version and sends the factor back to DESCRIPTIVE until an
  experiment has tested the new one. A result is never stretched to code it was not measured on.
* VALIDATED needs a person (``who``), the name of the experiment and the experiment's result, and the database refuses a row without
  them. Taking a validation back is a new DESCRIPTIVE row. Nothing is edited or deleted, so «what was this factor on the 3rd?» has one
  answer: ``standings(conn, at=...)``, the newest decision decided by then.
* Everything is read AS OF a moment, like every other block of the packet: a decision taken after the packet's moment is not in it, and
  the nightly audit proves it (``fbi.intel.leakage``, rule ``factors_known``).

VALIDATED does not by itself feed any model. It lets the AI treat a factor as signal rather than as description (``fbi.ai.prompts``) and it
is the record a later phase (F10-F12) needs before it puts a factor into a model - which will change the isolation test, with its reason,
and not happen as a side effect of this registry.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.competitions import team_calendar
from fbi.core.clock import now
from fbi.intel import h2h, scenarios, tactics

VERSION: Final = "factors-v1"
"""The shape of the packet block (``block``)."""

DESCRIPTIVE: Final = "DESCRIPTIVE"
VALIDATED: Final = "VALIDATED"
STATUSES: Final = (DESCRIPTIVE, VALIDATED)

H2H: Final = h2h.FACTOR
SCENARIOS: Final = scenarios.FACTOR
TACTICS: Final = tactics.FACTOR
CALENDAR: Final = "rest_congestion"
"""Rest and congestion from the calendar of a team in every competition (``fbi.competitions.team_calendar``)."""

MIN_REASON: Final = 10
"""A decision says why in at least this many characters (the same floor as the neutral-venue switch)."""

MAX_RESULT_BYTES: Final = 64_000
"""What the registry keeps of an experiment's result. A larger result stays in its own file and the row names it."""

NOTE: Final = (
    "Estado de cada factor de contexto del paquete. DESCRIPTIVE: PrediGol lo describe, ningún modelo lo lee y no justifica mover una "
    "probabilidad ni afirmar ventaja. VALIDATED: una persona decidió, con el resultado de un experimento sobre ESTA versión del factor, "
    "que aporta algo; `decision` dice cuándo y con qué experimento. Un factor que no aparece aquí es DESCRIPTIVE.")


@dataclass(frozen=True, slots=True)
class Factor:
    """One context factor of the packet: its key in the registry, the version of the code that computes it, the path of the block
    that carries what it describes, whether that block says its own ``status`` (the nightly audit makes it agree with the registry)
    and, in Spanish and for the owner, what it is and what an experiment would have to show."""

    key: str
    version: str
    block: tuple[str, ...]
    states: bool
    label: str
    claim: str

    @property
    def where(self) -> str:
        """The block as a claim cites it (``P:<where>``)."""
        return ".".join(self.block)


CATALOGUE: Final[tuple[Factor, ...]] = (
    Factor(H2H, h2h.VERSION, ("h2h",), True, "Cara a cara ponderado",
           "que el historial entre los dos equipos, ponderado por competición, sede, antigüedad y entrenador, predice el resultado mejor "
           "que la forma reciente de cada uno y que el mercado"),
    Factor(SCENARIOS, scenarios.VERSION, ("scenarios",), True, "Escenarios de tabla y de eliminatoria",
           "que lo que el partido le hace a su tabla o a su eliminatoria («le basta empatar», «necesita ganar por dos») cambia el "
           "resultado más allá de lo que ya dicen el modelo y el mercado"),
    Factor(TACTICS, tactics.VERSION, ("dossier", "tactics"), True, "Táctica observable",
           "que las formaciones, los cambios y el comportamiento con ventaja o desventaja de los últimos partidos de un equipo predicen "
           "su próximo partido mejor que su forma"),
    Factor(CALENDAR, team_calendar.VERSION, ("schedule",), False, "Descanso y congestión",
           "que los días de descanso y la carga de partidos en todas las competiciones cambian el resultado más allá de lo que ya "
           "dicen el modelo y el mercado"),
)
BY_KEY: Final[dict[str, Factor]] = {f.key: f for f in CATALOGUE}
RESERVED: Final = frozenset({"version", "note", "error"})
"""The other keys of the packet block: no factor may be called one of them."""


@dataclass(frozen=True, slots=True)
class Decision:
    """One row of ``intel.context_factors``: a person's (or the system's) decision about a factor at a version."""

    id: int
    factor: str
    version: str
    status: str
    decided_at: datetime
    decided_by: str
    who: str | None
    reason: str
    evidence: dict[str, Any]
    previous_id: int | None

    @property
    def experiment(self) -> str | None:
        """The experiment a validation cites (None on a DESCRIPTIVE decision)."""
        name = self.evidence.get("experiment")
        return str(name) if isinstance(name, str) else None


@dataclass(frozen=True, slots=True)
class Standing:
    """What a factor was at a moment: the decision that says so, or none - born DESCRIPTIVE."""

    factor: Factor
    decision: Decision | None

    @property
    def status(self) -> str:
        return DESCRIPTIVE if self.decision is None else self.decision.status

    def as_packet(self) -> dict[str, Any]:
        """The entry of ``content["factors"]``: the version, where the factor lives in the packet, its status and the decision
        behind it (when there is one). No name and no free text: the packet goes to a language model, the reasons are for the owner."""
        d = self.decision
        return {"version": self.factor.version, "block": self.factor.where, "status": self.status,
                "decision": None if d is None else {"id": d.id, "decided_at": d.decided_at.astimezone(UTC).isoformat(),
                                            "experiment": d.experiment}}


# ---------------------------------------------------------------------------------------------------------------------- reading

_COLUMNS = "id, factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id"


def _decision(row: Mapping[str, Any]) -> Decision:
    return Decision(int(row["id"]), str(row["factor"]), str(row["version"]), str(row["status"]), row["decided_at"],
                    str(row["decided_by"]), None if row["who"] is None else str(row["who"]), str(row["reason"]),
                    dict(row["evidence"]), None if row["previous_id"] is None else int(row["previous_id"]))


def unread() -> dict[str, Standing]:
    """The standings when the registry could not be read: every factor DESCRIPTIVE, which is the safe side of every doubt."""
    return {f.key: Standing(f, None) for f in CATALOGUE}


def standings(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Standing]:
    """Every factor of the catalogue as it stood at ``at``: the newest decision of ITS VERSION that had been taken by then, and
    DESCRIPTIVE when there is none. A decision of an older version of the code says nothing about this one."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT DISTINCT ON (factor, version) {_COLUMNS} FROM intel.context_factors WHERE decided_at <= %s "
                    "ORDER BY factor, version, id DESC", (at,))
        found = {(str(r["factor"]), str(r["version"])): _decision(r) for r in cur.fetchall()}
    return {f.key: Standing(f, found.get((f.key, f.version))) for f in CATALOGUE}


def block(stands: Mapping[str, Standing], *, error: str | None = None) -> dict[str, Any]:
    """The packet block (``content["factors"]``): a status for every factor of the catalogue. ``error`` is set when the registry
    could not be read, and then every factor is the DESCRIPTIVE it is born as."""
    out: dict[str, Any] = {"version": VERSION, "note": NOTE}
    if error is not None:
        out["error"] = error
    for f in CATALOGUE:
        out[f.key] = stands[f.key].as_packet()
    return out


def newest(conn: psycopg.Connection[Any], factor: str, version: str) -> Decision | None:
    """The newest decision about (factor, version), whenever it was taken."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM intel.context_factors WHERE factor = %s AND version = %s ORDER BY id DESC LIMIT 1",
                    (factor, version))
        row = cur.fetchone()
    return None if row is None else _decision(row)


def history(conn: psycopg.Connection[Any], factor: str | None = None) -> list[Decision]:
    """Every decision, oldest first (of one factor, or of all)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM intel.context_factors WHERE (%s::text IS NULL OR factor = %s) ORDER BY id",
                    (factor, factor))
        return [_decision(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------------------------------------------------- writing


@dataclass(frozen=True, slots=True)
class Change:
    decision: Decision
    changed: bool


def known(key: str) -> Factor:
    try:
        return BY_KEY[key]
    except KeyError:
        raise LookupError(f"{key!r} is not a context factor; the registry knows {', '.join(sorted(BY_KEY))}") from None


def check_reason(reason: str) -> str:
    reason = reason.strip()
    if len(reason) < MIN_REASON:
        raise ValueError(f"a decision needs a reason of at least {MIN_REASON} characters")
    return reason


def check_who(who: str) -> str:
    who = who.strip()
    if not who:
        raise ValueError("a decision names the person who takes it")
    return who


def check_evidence(experiment: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """The evidence of a validation, as the registry keeps it: the experiment's name and its result, a JSON object that says something
    and fits (``MAX_RESULT_BYTES``). The caller adds the factor and the version."""
    experiment = experiment.strip()
    if not experiment:
        raise ValueError("a validation names the experiment that tested the factor")
    if not isinstance(result, Mapping) or not result:
        raise ValueError("a validation holds the result of the experiment: a non-empty JSON object")
    try:
        size = len(json.dumps(result, sort_keys=True, allow_nan=False).encode())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"the result of the experiment is not plain JSON: {exc}") from exc
    if size > MAX_RESULT_BYTES:
        raise ValueError(f"the result of the experiment is {size} bytes; the registry keeps {MAX_RESULT_BYTES} at most. "
                         "Keep the whole result in a file and put its summary and the file's name here")
    return {"experiment": experiment, "result": dict(result)}


def _lock(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('intel.context_factors'))")


def _insert(conn: psycopg.Connection[Any], factor: Factor, status: str, *, who: str, reason: str, evidence: dict[str, Any],
            previous: Decision | None, at: datetime | None) -> Decision:
    when = at or now()
    if previous is not None and when < previous.decided_at:
        raise ValueError(f"a decision cannot be dated before the one it follows ({previous.decided_at.isoformat()})")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence, "
                    f"previous_id) VALUES (%s, %s, %s, %s, 'owner', %s, %s, %s, %s) RETURNING {_COLUMNS}",
                    (factor.key, factor.version, status, when, who, reason,
                     Jsonb({"factor": factor.key, "version": factor.version} | evidence), None if previous is None else previous.id))
        row = cur.fetchone()
    assert row is not None
    return _decision(row)


def promote(conn: psycopg.Connection[Any], key: str, *, experiment: str, result: Mapping[str, Any], reason: str, who: str,
            at: datetime | None = None) -> Change:
    """A person validates a factor at the version in force, citing the experiment and its result. Validating what is already
    validated by the same experiment writes nothing; by another experiment, it is a new decision (a re-validation). The caller
    commits."""
    factor = known(key)
    reason, who, evidence = check_reason(reason), check_who(who), check_evidence(experiment, result)
    _lock(conn)
    current = newest(conn, factor.key, factor.version)
    if current is not None and current.status == VALIDATED and current.experiment == evidence["experiment"]:
        return Change(current, False)
    return Change(_insert(conn, factor, VALIDATED, who=who, reason=reason, evidence=evidence, previous=current, at=at), True)


def retire(conn: psycopg.Connection[Any], key: str, *, reason: str, who: str, at: datetime | None = None) -> Change:
    """A person takes a validation back: the factor is DESCRIPTIVE again. Refuses a factor that is not validated. The caller commits."""
    factor = known(key)
    reason, who = check_reason(reason), check_who(who)
    _lock(conn)
    current = newest(conn, factor.key, factor.version)
    if current is None or current.status != VALIDATED:
        raise PermissionError(f"{factor.key} ({factor.version}) is not validated: there is nothing to take back")
    evidence = {"retired_decision": current.id, "retired_experiment": current.experiment}
    return Change(_insert(conn, factor, DESCRIPTIVE, who=who, reason=reason, evidence=evidence, previous=current, at=at), True)
