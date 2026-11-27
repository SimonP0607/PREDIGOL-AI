"""The door a pick has to pass to be published: the whole list of conditions in one function, in code (plan RP-10.5, findings H01 and H02,
``publication-door-v1``).

The plan's three steps are kept apart: an informative analysis (every match with a plan has one, and it is never worded as a recommendation), a selection under
evaluation (what the rule by evidence would mark, seen by the owner only) and an official pick (published, with the full door and the owner's express
authorization). This module is about the third and answers one question: for each condition of the door, is it met, not met, not yet evaluated or only the owner's to
give, and why.

THE CONDITIONS, by group:

* technical: ``validated_figure`` (a calibrated figure without the market that passed its gates: none exists today) and ``value_history`` (the method has 300
  selections or more out of sample with value against the real close of zero or more, condition 10 of the rule by evidence, RP-10.3);
* statistical: ``coherence`` (G-COH), ``ai_gate`` (the AI layer's prospective gate) and ``research_gate`` (Research v2's equivalence gate);
* security: ``gate_b`` (the 14-day window of the architecture), ``battery`` (the adversarial battery) and ``leaks`` (no violation in the last night's audit);
* ``owner_authorization``: the last one, and the only one the code can never give: it is always «solo el dueño».

``can_publish`` is ALWAYS False, whatever the other conditions say: the door tells the owner whether everything that code can check is met (``ready``); the switch
``FBI_PICKS_SOURCE`` and the authorization stay the owner's. A condition whose evidence is absent is «no evaluada», never «cumplida». No threshold is lowered here:
the numbers are the gates' own. Pure: it reads nothing, writes nothing, switches nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

VERSION: Final = "publication-door-v1"
MIN_VALUE_SELECTIONS: Final = 300
"""Condition 10 of the rule by evidence: selections out of sample before the method has a history."""

State = Literal["cumplida", "no_cumplida", "pendiente", "no_evaluada", "solo_dueno"]
Group = Literal["tecnica", "estadistica", "seguridad", "autorizacion"]

PASSED: Final = "PASA"
FAILED: Final = frozenset({"NO PASA", "RECHAZA"})
PENDING_PREFIX: Final = "PENDIENTE"
NOT_EVALUATED: Final = "NO EVALUADO"


@dataclass(frozen=True, slots=True)
class Condition:
    key: str
    group: Group
    label: str
    state: State
    why: str


@dataclass(frozen=True, slots=True)
class ValueHistory:
    """What RP-10.3's report says of the method: selections out of sample and its value against the real close (None when it has not been measured)."""

    selections: int
    value_vs_close: float | None


@dataclass(frozen=True, slots=True)
class Door:
    conditions: tuple[Condition, ...]
    switch_on: bool

    @property
    def ready(self) -> bool:
        """Every condition the code can check is met; only the owner's authorization is left."""
        return all(c.state == "cumplida" for c in self.conditions if c.group != "autorizacion")

    @property
    def can_publish(self) -> bool:
        """Never: publishing is the owner's act (the switch and the authorization), not the door's."""
        return False

    @property
    def first_open(self) -> str | None:
        """The first condition, in the door's order, that is not met (the reason a pick is not published)."""
        return next((c.key for c in self.conditions if c.state != "cumplida"), None)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "switch_on": self.switch_on, "ready": self.ready, "can_publish": self.can_publish, "first_open": self.first_open,
                "conditions": [{"key": c.key, "group": c.group, "label": c.label, "state": c.state, "why": c.why} for c in self.conditions]}


def state_of_gate(status: str | None) -> tuple[State, str]:
    """A gate's status of the panel as a condition's state."""
    if status is None:
        return "no_evaluada", "el gate no está en el panel"
    if status == PASSED:
        return "cumplida", "PASA con un pase registrado"
    if status in FAILED:
        return "no_cumplida", status
    if status == NOT_EVALUATED:
        return "no_evaluada", "no evaluado: la ventana se cerró sin veredicto"
    if status.startswith(PENDING_PREFIX):
        return "pendiente", status.lower()
    return "no_evaluada", f"estado desconocido: {status}"


def _gate(key: str, group: Group, label: str, gates: Mapping[str, str]) -> Condition:
    state, why = state_of_gate(gates.get(key))
    return Condition(key, group, label, state, why)


def evaluate(*, gates: Mapping[str, str], battery: str | None, leak_violations: int | None, validated_figures: int | None,
             value_history: ValueHistory | None, switch_on: bool) -> Door:
    """The door from what the console already reads. ``gates`` maps the panel's gate id to its status; ``battery`` is the newest verdict of the battery's gate
    (``PASA`` / ``NO PASA``) or None; ``leak_violations`` the violations of the newest night or None when there is no audit; ``validated_figures`` how many
    calibrated figures without the market passed their gates (None: not measured); ``value_history`` the method's history (None: not measured)."""
    if validated_figures is None:
        figure = Condition("validated_figure", "tecnica", "Cifra calibrada sin mercado que superó sus puertas", "no_evaluada", "no hay medida de la cifra validada")
    elif validated_figures > 0:
        figure = Condition("validated_figure", "tecnica", "Cifra calibrada sin mercado que superó sus puertas", "cumplida", f"{validated_figures} cifras")
    else:
        figure = Condition("validated_figure", "tecnica", "Cifra calibrada sin mercado que superó sus puertas", "no_cumplida", "ninguna cifra la supera hoy")
    if value_history is None:
        history = Condition("value_history", "tecnica", "El método tiene historial: 300 selecciones fuera de muestra con valor frente al cierre real ≥ 0",
                            "no_evaluada", "la regla por evidencia (RP-10.3) no ha medido el método")
    elif value_history.selections < MIN_VALUE_SELECTIONS:
        history = Condition("value_history", "tecnica", "El método tiene historial: 300 selecciones fuera de muestra con valor frente al cierre real ≥ 0",
                            "pendiente", f"{value_history.selections} de {MIN_VALUE_SELECTIONS} selecciones")
    elif value_history.value_vs_close is None or value_history.value_vs_close < 0:
        history = Condition("value_history", "tecnica", "El método tiene historial: 300 selecciones fuera de muestra con valor frente al cierre real ≥ 0",
                            "no_cumplida", "el valor frente al cierre real es negativo o no se midió")
    else:
        history = Condition("value_history", "tecnica", "El método tiene historial: 300 selecciones fuera de muestra con valor frente al cierre real ≥ 0",
                            "cumplida", f"{value_history.selections} selecciones, valor {value_history.value_vs_close:+.4f}")
    if battery is None:
        bat = Condition("battery", "seguridad", "Batería adversarial", "no_evaluada", "sin fila de la batería")
    else:
        s, why = state_of_gate(battery)
        bat = Condition("battery", "seguridad", "Batería adversarial", s, why)
    if leak_violations is None:
        leaks = Condition("leaks", "seguridad", "Auditoría de fugas de la última noche limpia", "no_evaluada", "sin auditoría")
    elif leak_violations == 0:
        leaks = Condition("leaks", "seguridad", "Auditoría de fugas de la última noche limpia", "cumplida", "0 violaciones")
    else:
        leaks = Condition("leaks", "seguridad", "Auditoría de fugas de la última noche limpia", "no_cumplida", f"{leak_violations} violaciones")
    owner = Condition("owner_authorization", "autorizacion", "Tu autorización expresa", "solo_dueno",
                      "la da el dueño con el interruptor FBI_PICKS_SOURCE; el código no puede darla ni inferirla")
    return Door((figure, history, _gate("g_coh", "estadistica", "Coherencia de las probabilidades (G-COH)", gates),
                 _gate("ai_gate_v2", "estadistica", "Puerta de la capa de IA", gates),
                 _gate("research_v2", "estadistica", "Gate de Research v2", gates),
                 _gate("gate_b", "seguridad", "Gate B", gates), bat, leaks, owner), switch_on)


__all__ = ["MIN_VALUE_SELECTIONS", "VERSION", "Condition", "Door", "ValueHistory", "evaluate", "state_of_gate"]
