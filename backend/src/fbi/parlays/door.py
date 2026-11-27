"""The door an experimental parlay has to pass to be considered: the conditions of the plan in one function, in code (plan RP-11.3, finding H23,
``parlay-door-v1``).

Nothing here publishes a parlay and nothing changes what the reader sees: Mi parlay and the published parlays are untouched. The door answers, for the experimental
parlays that PrediGol builds in the shadow, which conditions are met:

* ``max_three_legs`` and ``distinct_fixtures``: the structure. They are checked on every combination given and ONE combination of four legs, or with two legs of
  the same match, is refused, always (``refuse``). With no combination to look at they are «no evaluada», never «cumplida» by omission;
* ``legs_pass_pick_door``: every leg is a selection that passes the door of a pick (``fbi.ai.publication_door``): the ten conditions of the rule by evidence. It is
  met only when that door is ready;
* ``historical_reliability``: the joint probability was measured against the real frequency over 1.500 combinations of the saved decisions or more, with the error
  inside the bound of the report (RP-11.1). Not measured today: «no evaluada»;
* ``prospective_reliability``: 100 settled parlays in the shadow or more, and the observed wins inside the interval of the joint expected (the calibration of
  ``fbi.tracking.parlay_v6_shadow``);
* ``owner_authorization``: the owner's express and specific authorization for parlays: always «solo el dueño».

``can_publish`` is always False; ``ready`` says that everything the code can check is met. The thresholds are the plan's own and none is lowered here. Pure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

VERSION: Final = "parlay-door-v1"
MAX_LEGS: Final = 3
MIN_COMBINATIONS: Final = 1500
"""Combinations of saved decisions over which the joint's error is measured (RP-11.1's acceptance)."""
MIN_SETTLED: Final = 100
"""Settled parlays in the shadow before their calibration is judged (the plan's clock for RP-11.3)."""

State = Literal["cumplida", "no_cumplida", "pendiente", "no_evaluada", "solo_dueno"]


@dataclass(frozen=True, slots=True)
class Condition:
    key: str
    label: str
    state: State
    why: str


@dataclass(frozen=True, slots=True)
class Reliability:
    """What RP-11.1's report says of the joint: the combinations measured and whether its calibration error is inside the bound (None: not decided)."""

    combinations: int
    within_bound: bool | None


@dataclass(frozen=True, slots=True)
class Prospective:
    """The shadow parlays settled and how many wins the joint expected, with its interval (low, high)."""

    settled: int
    won: int
    expected_low: float | None
    expected_high: float | None


def refuse(fixture_ids: Sequence[int]) -> str | None:
    """Why a combination is refused, or None. A combination of more than three legs or with two legs of one match is refused always, whatever else is met."""
    if len(fixture_ids) > MAX_LEGS:
        return f"{len(fixture_ids)} selecciones: el máximo es {MAX_LEGS}"
    if len(set(fixture_ids)) != len(fixture_ids):
        return "dos selecciones del mismo partido nunca se combinan"
    return None


@dataclass(frozen=True, slots=True)
class Door:
    conditions: tuple[Condition, ...]
    switch_on: bool = False

    @property
    def ready(self) -> bool:
        return all(c.state == "cumplida" for c in self.conditions if c.state != "solo_dueno") and bool(self.conditions)

    @property
    def can_publish(self) -> bool:
        """Never: the door tells, the owner decides."""
        return False

    @property
    def first_open(self) -> str | None:
        return next((c.key for c in self.conditions if c.state != "cumplida"), None)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "ready": self.ready, "can_publish": self.can_publish, "first_open": self.first_open,
                "conditions": [{"key": c.key, "label": c.label, "state": c.state, "why": c.why} for c in self.conditions]}


def _structure(combinations: Sequence[Sequence[int]]) -> tuple[Condition, Condition]:
    max_label = f"Como mucho {MAX_LEGS} selecciones por parlay"
    distinct_label = "Todas las selecciones son de partidos distintos"
    if not combinations:
        why = "no hay parlays en sombra que mirar"
        return Condition("max_three_legs", max_label, "no_evaluada", why), Condition("distinct_fixtures", distinct_label, "no_evaluada", why)
    too_long = [c for c in combinations if len(c) > MAX_LEGS]
    repeated = [c for c in combinations if len(set(c)) != len(c)]
    return (Condition("max_three_legs", max_label, "no_cumplida" if too_long else "cumplida",
                      f"{len(too_long)} de {len(combinations)} parlays tienen más de {MAX_LEGS}" if too_long else f"{len(combinations)} parlays revisados"),
            Condition("distinct_fixtures", distinct_label, "no_cumplida" if repeated else "cumplida",
                      f"{len(repeated)} de {len(combinations)} repiten un partido" if repeated else f"{len(combinations)} parlays revisados"))


def evaluate(*, combinations: Sequence[Sequence[int]], pick_door_ready: bool | None, reliability: Reliability | None, prospective: Prospective | None,
             switch_on: bool = False) -> Door:
    """The door from what the console reads. ``combinations`` are the fixtures of each parlay built in the shadow; ``pick_door_ready`` whether the door of a
    pick is ready (None: not measured)."""
    max_legs, distinct = _structure(combinations)
    if pick_door_ready is None:
        legs = Condition("legs_pass_pick_door", "Cada selección pasa las condiciones de un pick", "no_evaluada", "la puerta de los picks no se pudo leer")
    elif pick_door_ready:
        legs = Condition("legs_pass_pick_door", "Cada selección pasa las condiciones de un pick", "cumplida", "la puerta de los picks está lista")
    else:
        legs = Condition("legs_pass_pick_door", "Cada selección pasa las condiciones de un pick", "no_cumplida", "la puerta de los picks tiene condiciones abiertas")
    label = f"Fiabilidad histórica de la conjunta: error de calibración medido en {MIN_COMBINATIONS} combinaciones o más"
    if reliability is None:
        hist = Condition("historical_reliability", label, "no_evaluada", "la repetición histórica de RP-11.1 no se ha medido")
    elif reliability.combinations < MIN_COMBINATIONS:
        hist = Condition("historical_reliability", label, "pendiente", f"{reliability.combinations} de {MIN_COMBINATIONS} combinaciones")
    elif reliability.within_bound is None:
        hist = Condition("historical_reliability", label, "no_evaluada", "el informe no dice si el error está dentro de su cota")
    else:
        hist = Condition("historical_reliability", label, "cumplida" if reliability.within_bound else "no_cumplida",
                         f"{reliability.combinations} combinaciones; error {'dentro' if reliability.within_bound else 'fuera'} de la cota")
    label = f"Fiabilidad prospectiva: {MIN_SETTLED} parlays en sombra liquidados con la conjunta calibrada"
    if prospective is None:
        pro = Condition("prospective_reliability", label, "no_evaluada", "no se pudo leer la calibración de los parlays en sombra")
    elif prospective.settled < MIN_SETTLED:
        pro = Condition("prospective_reliability", label, "pendiente", f"{prospective.settled} de {MIN_SETTLED} liquidados")
    elif prospective.expected_low is None or prospective.expected_high is None:
        pro = Condition("prospective_reliability", label, "no_evaluada", "sin intervalo de aciertos esperados")
    else:
        inside = prospective.expected_low <= prospective.won <= prospective.expected_high
        pro = Condition("prospective_reliability", label, "cumplida" if inside else "no_cumplida",
                        f"{prospective.won} aciertos frente a {prospective.expected_low:.1f} a {prospective.expected_high:.1f} esperados")
    owner = Condition("owner_authorization", "Tu autorización expresa y específica para parlays", "solo_dueno",
                      "la da el dueño; el código no puede darla ni inferirla")
    return Door((max_legs, distinct, legs, hist, pro, owner), switch_on)


__all__ = ["MAX_LEGS", "MIN_COMBINATIONS", "MIN_SETTLED", "VERSION", "Condition", "Door", "Prospective", "Reliability", "evaluate", "refuse"]
