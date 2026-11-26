"""The state machine of the learning cycle of a hypothesis (plan RP-8.1, finding H25). Pure: no database, no clock.

A hypothesis is a line of ``analytics.research_hypotheses``; its ``status`` follows ONE graph, written here and nowhere else, so that the code that moves it
(``fbi.research.evolution``, the triage of RP-8.2, the executor of RP-8.3) and the screens that show it agree on what may follow what and on who may do it.

    PROPOSED ──► INVESTIGATING ──► ACCEPTED ──► RUNNING ──► SHADOW ──► DONE ──► PROMOTED
        │              │              │            │           │          │
        └──► REJECTED ◄┘              └────────────┴───────────┴──────────┴──► ARCHIVED ──► PROPOSED / INVESTIGATING (reopened)

* WHO. The decisions that change what the system does (accept, reject, promote, archive, reopen) are the OWNER's. The movement of an accepted experiment
  through its stages (RUNNING, SHADOW, DONE) is the SYSTEM's, and it never reaches PROMOTED on its own.
* ARCHIVED is a state, not a deletion: the line, its evidence and its history stay, and a later decision may reopen it.
  The table says ``PROPOSED`` if and only if ``decided_at`` is empty: archiving stamps ``decided_at`` (the day it was put away) and REOPENING as PROPOSED must
  clear it again (the code of RP-8.2 does both in the same statement, with the reason in the history of stages).
* REJECTED and PROMOTED are final.
* ``next_step`` says in Spanish what is waiting for each state, so that no hypothesis is left without a next move or a person responsible for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

VERSION: Final = "cycle-state-v1"

Who = Literal["owner", "system"]

PROPOSED: Final = "PROPOSED"
INVESTIGATING: Final = "INVESTIGATING"
ACCEPTED: Final = "ACCEPTED"
REJECTED: Final = "REJECTED"
RUNNING: Final = "RUNNING"
SHADOW: Final = "SHADOW"
DONE: Final = "DONE"
PROMOTED: Final = "PROMOTED"
ARCHIVED: Final = "ARCHIVED"

STATES: Final = (PROPOSED, INVESTIGATING, ACCEPTED, RUNNING, SHADOW, DONE, PROMOTED, REJECTED, ARCHIVED)
"""All the states a hypothesis may have: the ones the database accepts (migration 0183), in the order of the cycle."""

FINAL: Final = frozenset({REJECTED, PROMOTED})
"""States with no way out."""

OPEN: Final = frozenset(STATES) - FINAL - {ARCHIVED}
"""States in which the hypothesis is still alive and has a next step."""

# from -> {to: who may make the move}
TRANSITIONS: Final[Mapping[str, Mapping[str, Who]]] = {
    PROPOSED: {INVESTIGATING: "owner", ACCEPTED: "owner", REJECTED: "owner", ARCHIVED: "owner"},
    INVESTIGATING: {ACCEPTED: "owner", REJECTED: "owner", ARCHIVED: "owner"},
    ACCEPTED: {RUNNING: "system", ARCHIVED: "owner"},
    RUNNING: {SHADOW: "system", DONE: "system", ARCHIVED: "owner"},
    SHADOW: {DONE: "system", ARCHIVED: "owner"},
    DONE: {PROMOTED: "owner", ARCHIVED: "owner"},
    ARCHIVED: {PROPOSED: "owner", INVESTIGATING: "owner"},
    REJECTED: {},
    PROMOTED: {},
}

NEXT_STEP: Final[Mapping[str, str]] = {
    PROPOSED: "Espera la decisión del dueño: rechazar, investigar más o aprobar el experimento; o archivarla si ya no aplica.",
    INVESTIGATING: "Se reúne más evidencia antes de decidir; después el dueño la aprueba, la rechaza o la archiva.",
    ACCEPTED: "El experimento está aprobado y espera su turno en la investigación (retrospectivo sobre datos ya vistos, con su protocolo).",
    RUNNING: "Corre el retrospectivo; al terminar pasa a la sombra prospectiva o se juzga.",
    SHADOW: "Se mide en la sombra prospectiva con la muestra fijada; no se mira el veredicto antes de llegar a ella.",
    DONE: "Está juzgada, con su resultado guardado. Solo el dueño puede promoverla, y solo si pasó su puerta (prueba intacta, sombra, coherencia).",
    PROMOTED: "Final: el dueño la promovió; ponerla en producción es otro acto, deliberado, con su propia puerta.",
    REJECTED: "Final: el dueño la rechazó; queda su razón y su historia.",
    ARCHIVED: "Puesta aparte con su razón, sin borrar nada; el dueño puede reabrirla como propuesta o como investigación.",
}


class TransitionRefusedError(ValueError):
    """A move the graph does not allow, or one made by someone who may not make it."""


@dataclass(frozen=True, slots=True)
class Move:
    source: str
    target: str
    who: Who


def known(state: str) -> bool:
    return state in TRANSITIONS


def allowed(source: str) -> dict[str, Who]:
    """The states a hypothesis in ``source`` may go to, with who decides each. Unknown or final states: nothing."""
    return dict(TRANSITIONS.get(source, {}))


def check(source: str, target: str, *, by: Who) -> Move:
    """The move ``source`` → ``target`` made by ``by``, or ``TransitionRefusedError`` saying why not."""
    if not known(source):
        raise TransitionRefusedError(f"estado desconocido: {source!r}")
    if not known(target):
        raise TransitionRefusedError(f"estado desconocido: {target!r}")
    who = TRANSITIONS[source].get(target)
    if who is None:
        raise TransitionRefusedError(f"de {source} no se pasa a {target}" + (" (estado final)" if source in FINAL else ""))
    if who == "owner" and by != "owner":
        raise TransitionRefusedError(f"de {source} a {target} decide el dueño, no el sistema")
    return Move(source, target, who)


def next_step(state: str) -> str:
    return NEXT_STEP.get(state, "Estado desconocido: no tiene siguiente paso definido.")


def reachable(source: str) -> frozenset[str]:
    """Every state that can be reached from ``source`` by any sequence of allowed moves (used to assert that nothing is left stranded)."""
    seen: set[str] = set()
    todo = [source]
    while todo:
        for to in TRANSITIONS.get(todo.pop(), {}):
            if to not in seen:
                seen.add(to)
                todo.append(to)
    return frozenset(seen)


__all__ = [
    "FINAL",
    "NEXT_STEP",
    "OPEN",
    "STATES",
    "TRANSITIONS",
    "VERSION",
    "Move",
    "TransitionRefusedError",
    "allowed",
    "check",
    "known",
    "next_step",
    "reachable",
]
