"""The owner's private alerts «antes -> ahora» (IA-107, plan piece AD-D08, ``alerts-v1``). Pure.

Four kinds, each saying what changed with the value of before and the value of now:

    retirada            a selection that was waiting for its line-up or confirmed in the shadow was withdrawn: its state, figure and
                        price before and after, and the cause (the decision, the price, the line-up, the value)
    sin_alineacion      E4 came and the official line-up a selection waits for had not arrived (it closes at kick-off as «sin
                        alineación a tiempo» unless the line-up comes in the last ten minutes)
    cambio_horario      the kick-off moved after the cycle read it
    cambio_condiciones  the match was postponed, cancelled, suspended, started, or its venue changed

Each alert is written once (``dedupe_key``: kind, match, selection, cause and the two values). They are PRIVATE: served only by contract
C-05 under ``require_admin`` (``GET /api/v1/admin/intelligence/alerts``); no notifier, message, e-mail or reader's page imports this module
(``tests/unit/test_eval_cycle_isolation.py``). No health detail ever travels: an absence is a state, a source and a date.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.evalcycle.conditions import Change
from fbi.evalcycle.reevaluate import Outcome, Standing

VERSION: Final = "alerts-v1"
RETIRADA: Final = "retirada"
SIN_ALINEACION: Final = "sin_alineacion"
KINDS: Final = (RETIRADA, SIN_ALINEACION, "cambio_horario", "cambio_condiciones")

Key = tuple[str, str, Decimal]


@dataclass(frozen=True, slots=True)
class Alert:
    kind: str
    fixture_id: int
    key: Key | None
    cause: str
    before: Mapping[str, Any]
    after: Mapping[str, Any]
    price: Mapping[str, Any] | None = None
    decision_id: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        sel = "-" if self.key is None else f"{self.key[0]}|{self.key[1]}|{Decimal(str(self.key[2])).quantize(Decimal('0.01'))}"
        digest = hashlib.sha256(json.dumps([self.before, self.after], sort_keys=True, default=str).encode()).hexdigest()[:16]
        return f"{self.kind}|{self.fixture_id}|{sel}|{self.cause}|{digest}"


def _r(x: float | None, places: int) -> float | None:
    return None if x is None else round(x, places)


def withdrawn(fixture_id: int, key: Key, standing: Standing, outcome: Outcome, *, decision_id: int | None,
              price_at: datetime | None = None, age_minutes: float | None = None) -> Alert | None:
    """The alert of a withdrawal, or None when the outcome is not one."""
    if not outcome.withdrawn or standing.state not in ("pendiente_alineaciones", "confirmada_sombra"):
        return None
    before = {"state": standing.state, "reason": standing.reason, "p": _r(standing.p, 4), "odds": _r(standing.odds, 3)}
    after: dict[str, Any] = {"state": outcome.state, "reason": outcome.reason, "p": _r(outcome.p_after, 4), "odds": _r(outcome.odds_after, 3),
             "price_state": outcome.price_state, "ev": _r(outcome.ev_after, 4)}
    missing = list(outcome.lineup.get("missing") or [])
    if missing:
        after["players_out"] = missing
    price = {"odds": _r(outcome.odds_after, 3), "state": outcome.price_state, "at": None if price_at is None else price_at.isoformat(),
             "age_minutes": _r(age_minutes, 1)}
    return Alert(RETIRADA, fixture_id, key, outcome.reason, before, after, price, decision_id)


def no_line_up(fixture_id: int, key: Key, *, minutes_to_kickoff: float, sides_missing: list[str]) -> Alert:
    """E4 came and the line-up this selection waits for has not arrived."""
    return Alert(SIN_ALINEACION, fixture_id, key, "sin_alineacion_a_tiempo",
                 {"state": "pendiente_alineaciones", "line_up": "esperada"},
                 {"state": "pendiente_alineaciones", "line_up": "sin_alineacion_oficial", "sides_missing": sorted(sides_missing),
                  "minutes_to_kickoff": round(minutes_to_kickoff, 1)})


def changed(fixture_id: int, change: Change) -> Alert:
    """A change of the kick-off or of the conditions of the match (no selection)."""
    return Alert(change.kind, fixture_id, None, change.cause, dict(change.before), dict(change.after))
