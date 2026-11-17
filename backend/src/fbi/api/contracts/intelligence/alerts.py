"""C-05, the owner's private alerts by line-up (AD-J06 for its route; the alerts themselves are AD-D08, IA-107).

``GET /api/v1/admin/intelligence/alerts`` (``require_admin``; no public projection - ``PRIVATE_ONLY``). The alerts of the evaluation cycle
(``eval-cycle-v1``, ``intel.private_alerts``), newest first, each «antes -> ahora»:

* ``retirada`` - a selection that was waiting for its line-up or confirmed in the shadow was withdrawn: its state, figure and price before
  and now, and the cause;
* ``sin_alineacion`` - E4 came and the official line-up the selection waits for had not arrived;
* ``cambio_horario`` - the kick-off moved after the cycle read it (before and now);
* ``cambio_condiciones`` - the match was postponed, cancelled, suspended or started, or its venue changed (before and now).

It is never a notice: ``notifies_reader`` is always false and no notifier, message or reader's page reads these alerts. No health detail:
an absence is a state, a source and a date. The words are the cycle's own; nothing here decides, records or switches anything.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
)
from fbi.api.contracts.intelligence.vocab import EvaluationStep, LifecycleState

LINE_PATTERN: Final = r"^-?\d+\.\d{2}$"
STATUS_PATTERN: Final = r"^[A-Z0-9]{1,6}$"

AlertKind = Literal["retirada", "sin_alineacion", "cambio_horario", "cambio_condiciones"]
PriceState = Literal["vigente", "antiguo", "sin_precio"]
Side = Literal["home", "away"]


class SelectionRef(IntelligenceModel):
    """The selection the alert is about (``market_key`` / ``selection`` / ``line`` as decision-v2 keeps them)."""

    market_key: str = Field(min_length=1, max_length=40)
    selection: str = Field(min_length=1, max_length=60)
    line: str = Field(pattern=LINE_PATTERN, description="The line with two decimals, as stored (2.50).")


class SelectionState(IntelligenceModel):
    """A selection's state in the cycle with the figure and price it held (``retirada``)."""

    shape: Literal["seleccion"] = "seleccion"
    state: LifecycleState
    reason: str = Field(pattern=CODE_PATTERN, description="The cycle's reason of that state (closed list of AD-D02).")
    probability: float | None = Field(ge=0, le=1, description="The figure judged (calibrated when there is a calibrator).")
    odds: float | None = Field(gt=1, description="The price it was judged at.")
    price_state: PriceState | None = Field(default=None, description="vigente / antiguo / sin_precio under the age rule.")
    players_out: list[int] = Field(default_factory=list, description="Players it depends on who do not start (provider ids).")


class LineUpState(IntelligenceModel):
    """The line-up a waiting selection expects (``sin_alineacion``)."""

    shape: Literal["alineacion"] = "alineacion"
    state: LifecycleState
    line_up: Literal["esperada", "sin_alineacion_oficial"]
    sides_missing: list[Side] = Field(default_factory=list)
    minutes_to_kickoff: float | None = Field(default=None, ge=0)


class KickoffState(IntelligenceModel):
    """The kick-off (``cambio_horario``)."""

    shape: Literal["saque"] = "saque"
    kickoff_at: UtcDatetime


class ConditionState(IntelligenceModel):
    """The match's state and venue (``cambio_condiciones``)."""

    shape: Literal["condiciones"] = "condiciones"
    status: str | None = Field(default=None, pattern=STATUS_PATTERN, description="The provider's short state (NS, PST, CANC...).")
    venue_id: int | None = Field(default=None, ge=1)
    in_play_at: UtcDatetime | None = Field(default=None, description="When the in-play feed saw it playing, if it did.")


Value = SelectionState | LineUpState | KickoffState | ConditionState
SHAPE_OF: Final[dict[str, str]] = {"retirada": "seleccion", "sin_alineacion": "alineacion", "cambio_horario": "saque",
                                    "cambio_condiciones": "condiciones"}


class PriceAtAlert(IntelligenceModel):
    odds: float | None = Field(gt=1)
    state: PriceState | None
    at: UtcDatetime | None = Field(description="When the price was last confirmed.")
    age_minutes: float | None = Field(ge=0)


class DecisionRef(IntelligenceModel):
    decision_id: int = Field(ge=1, description="The row of intel.decisions_v2 the alert's evaluation decided with.")
    version: Literal["decision-v2"] = "decision-v2"


class AlertItem(IntelligenceModel):
    alert_id: int = Field(ge=1)
    kind: AlertKind
    fixture_id: int = Field(ge=1)
    selection: SelectionRef | Missing = Field(description="The selection, or sin_datos for an alert about the match itself.")
    cause: str = Field(pattern=CODE_PATTERN, description="What caused it, in the cycle's words.")
    before: Value
    now: Value
    price: PriceAtAlert | Missing
    decision: DecisionRef | Missing
    evaluation: EvaluationStep = Field(description="The evaluation that raised it (or whose reading it was held against).")
    evaluation_version: int = Field(ge=1)
    known_at: UtcDatetime = Field(description="When the cycle knew it.")
    kickoff_at: UtcDatetime = Field(description="The kick-off as read when it was raised.")
    notifies_reader: Literal[False] = Field(default=False, description="Never: an alert is the owner's, it notifies nobody.")

    @model_validator(mode="after")
    def _shapes(self) -> AlertItem:
        shape = SHAPE_OF[self.kind]
        if self.before.shape != shape or self.now.shape != shape:
            raise ValueError(f"a {self.kind} alert says its before and now as {shape}")
        if self.before == self.now:
            raise ValueError("an alert says what changed: before and now cannot be the same")
        if (self.kind in ("retirada", "sin_alineacion")) == isinstance(self.selection, Missing):
            raise ValueError("an alert about a selection names it; one about the match does not")
        return self


class AlertsContract(IntelligenceContract):
    """C-05, private only."""

    CONTRACT_ID: ClassVar[str] = "C-05"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    PRIVATE_ONLY: ClassVar[bool] = True

    decides: Literal[False] = Field(default=False, description="Nothing here decides, records or switches anything.")
    window_hours: int = Field(ge=1, le=720, description="How far back the alerts are listed.")
    alerts: ItemList[AlertItem]
