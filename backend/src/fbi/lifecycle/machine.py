"""The state machine of a selection (IA-068, AD-D02): ten states, a closed list of reasons per state, the legal moves and who
may make each. Pure: no database, no clock. The same rules are written into the table (revision 0142) and
``tests/unit/test_lifecycle_machine.py`` holds both equal, so neither the code nor a hand-written row can break them.

    detectado ──► en_investigacion ◄─► en_evaluacion ──► pendiente_alineaciones ──► confirmada_sombra ──► en_juego ──► liquidada ──► evaluada
        │                 │                  │                    │                      │
        └─────────────────┴──────────────────┴──► descartada ◄────┴──── retirada ◄───────┘

* A chain starts at ``detectado`` and every row names the row before it; nothing is rewritten.
* ``descartada`` and ``evaluada`` have no way out; ``en_juego`` only settles, ``liquidada`` is only evaluated.
* ``retirada`` is a selection that was waiting for the line-ups or confirmed and lost its ground (the line-up, the price, a
  new fact): it may come back (``en_evaluacion``, ``pendiente_alineaciones``, ``confirmada_sombra``) or close (``descartada``).
* Three actors. ``code`` makes every move. A ``model`` (the review, the Council) may only take a selection DOWN - to
  ``retirada`` or ``descartada`` - never up. The ``owner`` makes one move only: the authorisation of a confirmed selection
  (``confirmada_sombra`` to itself, reason ``autorizada_por_dueno``, with a signature). Nothing is public without it
  (``public_state``), and the shadow writer never writes it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, get_args

VERSION: Final = "lifecycle-v1"

State = Literal["detectado", "en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra",
                "retirada", "descartada", "en_juego", "liquidada", "evaluada"]
STATES: Final[tuple[str, ...]] = get_args(State)
"""The ten codes of ``fbi.api.contracts.intelligence.vocab.LifecycleState`` (UX's closed list, IA-057), in the cycle's order."""

Actor = Literal["code", "model", "owner"]
ACTORS: Final[tuple[str, ...]] = get_args(Actor)

TERMINAL: Final = frozenset({"descartada", "evaluada"})
OPEN: Final = frozenset({"detectado", "en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "retirada"})
"""Before kick-off: the states a selection can still leave for another pre-match state."""
REPEATABLE: Final = frozenset({"en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra"})
"""States a row may repeat: a new evaluation that keeps the state with another reason, or the owner's authorisation."""

BLOCKERS: Final[tuple[str, ...]] = (
    "datos_insuficientes", "sin_modelo", "sin_precio", "mercado_estrecho", "precio_atipico", "contexto_lo_impide",
    "baja_clave_confirmada", "valor_insuficiente", "sin_calibrar", "precio_antiguo", "revision_en_contra",
    "baja_por_confirmar", "riesgo", "otra_del_partido", "sin_motivo_conocido")
"""Why a selection does not meet everything right now (one per row: the most severe). ``sin_motivo_conocido`` is a reason the map
does not know yet: counted and listed, never guessed."""

AUTHORISED: Final = "autorizada_por_dueno"

REASONS: Final[Mapping[str, tuple[str, ...]]] = {
    "detectado": ("candidato_nuevo",),
    "en_investigacion": ("contexto_pendiente", "hecho_nuevo"),
    "en_evaluacion": ("en_curso", *BLOCKERS),
    "pendiente_alineaciones": ("baja_por_confirmar", "depende_de_alineacion"),
    "confirmada_sombra": ("cumple_todo", "cumple_salvo_validacion", AUTHORISED),
    "retirada": (*BLOCKERS, "contexto_pendiente", "alineacion_en_contra", "hecho_en_contra", "partido_no_jugado"),
    "descartada": (*BLOCKERS, "contexto_pendiente", "retirada_al_saque", "sin_alineacion_a_tiempo", "partido_no_jugado",
                   "sin_decision"),
    "en_juego": ("saque",),
    "liquidada": ("resultado",),
    "evaluada": ("evaluacion_posterior",),
}
"""The closed reasons of each state. A row's reason is one of its state's, or the row does not exist."""

TRANSITIONS: Final[Mapping[str | None, frozenset[str]]] = {
    None: frozenset({"detectado"}),
    "detectado": frozenset({"en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"}),
    "en_investigacion": frozenset({"en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"}),
    "en_evaluacion": frozenset({"en_evaluacion", "en_investigacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"}),
    "pendiente_alineaciones": frozenset({"pendiente_alineaciones", "confirmada_sombra", "retirada", "descartada"}),
    "confirmada_sombra": frozenset({"confirmada_sombra", "pendiente_alineaciones", "retirada", "en_juego"}),
    "retirada": frozenset({"en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"}),
    "en_juego": frozenset({"liquidada"}),
    "liquidada": frozenset({"evaluada"}),
    "descartada": frozenset(),
    "evaluada": frozenset(),
}
"""Every legal move, ``None`` being the start of a chain. A move not here is impossible, whoever asks for it."""

DOWNWARD: Final = frozenset({"retirada", "descartada"})
"""The only states a model may move a selection to: it can take one down, never up."""

SETTLED_RESULTS: Final[tuple[str, ...]] = ("win", "loss", "push", "void", "half_win", "half_loss")
"""``settle-v4``'s results once a selection is settled (``vocab.SettlementResult`` without ``pending``)."""
EVALUATIONS: Final[tuple[str, ...]] = ("E1", "E2", "E3", "E4")


class IllegalTransitionError(ValueError):
    """A row the machine refuses: the message says which rule it breaks."""


@dataclass(frozen=True, slots=True)
class Step:
    """One move of a chain as the machine sees it (the table adds the selection, the times and the source)."""

    state: str
    reason: str
    actor: str = "code"
    owner_signature: str | None = None
    settlement_result: str | None = None
    evaluation: str | None = None
    evaluation_version: int | None = None


def problems(previous: str | None, step: Step) -> list[str]:
    """Every rule ``step`` breaks after a chain whose newest state is ``previous`` (``None``: a new chain). Empty: legal."""
    out: list[str] = []
    if step.state not in STATES:
        return [f"unknown state {step.state!r}"]
    if previous is not None and previous not in STATES:
        return [f"unknown previous state {previous!r}"]
    if step.state not in TRANSITIONS[previous]:
        out.append(f"{previous or 'start'} -> {step.state} is not a move of the cycle")
    if step.reason not in REASONS[step.state]:
        out.append(f"{step.reason!r} is not a reason of {step.state}")
    if step.actor not in ACTORS:
        out.append(f"unknown actor {step.actor!r}")
    if step.actor == "model" and step.state not in DOWNWARD:
        out.append(f"a model may only take a selection down (retirada, descartada), not to {step.state}")
    owner = step.actor == "owner"
    if owner != (step.reason == AUTHORISED) or owner != (step.owner_signature is not None):
        out.append("the owner's authorisation, its reason and its signature go together, and nothing else carries them")
    if step.reason == AUTHORISED and previous != "confirmada_sombra":
        out.append("only a selection confirmed in the shadow can be authorised")
    if (step.state == "liquidada") != (step.settlement_result is not None):
        out.append("a settled selection carries its result, and only a settled one")
    if step.settlement_result is not None and step.settlement_result not in SETTLED_RESULTS:
        out.append(f"unknown result {step.settlement_result!r}")
    if step.evaluation is not None and step.evaluation not in EVALUATIONS:
        out.append(f"unknown evaluation {step.evaluation!r}")
    if step.evaluation_version is not None and (step.evaluation is None or step.evaluation_version < 1):
        out.append("an evaluation version needs its evaluation and starts at 1")
    return out


def check(previous: str | None, step: Step) -> None:
    """Raise ``IllegalTransitionError`` when ``step`` cannot follow ``previous``."""
    found = problems(previous, step)
    if found:
        raise IllegalTransitionError("; ".join(found))


def check_chain(steps: Sequence[Step]) -> None:
    """Raise ``IllegalTransitionError`` at the first illegal row of a whole chain."""
    previous: str | None = None
    for i, step in enumerate(steps):
        found = problems(previous, step)
        if found:
            raise IllegalTransitionError(f"row {i}: " + "; ".join(found))
        previous = step.state


def authorised(steps: Sequence[Step]) -> bool:
    """Whether the owner authorised the selection in its current streak: an authorisation counts only after the last time the
    selection was below ``confirmada_sombra`` (a withdrawn selection that comes back needs the owner again)."""
    ok = False
    for step in steps:
        if step.state not in ("confirmada_sombra", "en_juego", "liquidada", "evaluada"):
            ok = False
        elif step.reason == AUTHORISED and step.actor == "owner" and step.owner_signature:
            ok = True
    return ok


PUBLIC: Final[Mapping[str, str]] = {"confirmada_sombra": "publicada", "en_juego": "en_juego", "liquidada": "liquidada",
                                     "evaluada": "liquidada"}
"""``vocab.public_state_of`` for an authorised selection (the test holds the two equal)."""


def public_state(steps: Sequence[Step]) -> str | None:
    """What a reader may see of a chain, or None: nothing without the owner's authorisation (``authorised``), and then only
    published, in play or settled. The shadow writer never writes an authorisation, so its chains are never public."""
    if not steps or not authorised(steps):
        return None
    return PUBLIC.get(steps[-1].state)


def pairs() -> list[tuple[str, str]]:
    """Every legal (from, to) move with a previous row, in a stable order (the table's CHECK lists the same)."""
    return [(a, b) for a in STATES for b in STATES if b in TRANSITIONS[a]]


def reason_pairs() -> list[tuple[str, str]]:
    """Every legal (state, reason), in a stable order (the table's CHECK lists the same)."""
    return [(s, r) for s in STATES for r in REASONS[s]]
