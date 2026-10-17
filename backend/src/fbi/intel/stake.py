"""How much to stake - ``stake-v1``: a quarter of Kelly on the CALIBRATED probability, in units of 1 % of the bankroll,
rounded DOWN to a quarter unit and capped by the decision's state. Never full Kelly; never a stake for a selection that
is not approved.

    Kelly (with a push):  f* = (p_win * (odds - 1) - p_lose) / (odds - 1),  p_win = p (1 - p_push),
                          p_lose = (1 - p)(1 - p_push)
    stake                 = floor_to_0.25( KELLY_FRACTION * f* * 100 ),   capped:

        CAUTELA 0.25 u   APROBADO / CANDIDATO_PARLAY 1.00 u   PICK_DEL_DIA 1.00 u   PICK_PREMIUM 1.50 u
        parlay 0.25 u    RECHAZADO / INVESTIGACION 0

The quarter and the caps were checked by simulation (``scripts/intel_stake_sim.py``: bankroll paths drawn from the
calibrated probabilities of the walk-forward decisions - growth, drawdown and the chance of losing half the bankroll
for flat, quarter, half and full Kelly). "Más información ≠ más certeza": a higher PrediGol Pick Score never raises a
stake above what the calibrated probability and the price justify.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

VERSION = "stake-v1"
KELLY_FRACTION = 0.25
STEP = 0.25
CAPS: dict[str, float] = {"RECHAZADO": 0.0, "INVESTIGACION": 0.0, "CAUTELA": 0.25, "APROBADO": 1.0,
                          "CANDIDATO_PARLAY": 1.0, "PICK_DEL_DIA": 1.0, "PICK_PREMIUM": 1.5}
PARLAY_CAP = 0.25


@dataclass(frozen=True, slots=True)
class Stake:
    units: float
    kelly: float
    """Full-Kelly fraction of the bankroll (negative: no bet)."""
    fraction: float
    cap: float
    capped: bool

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "units": self.units, "kelly_full": round(self.kelly, 6),
                "kelly_fraction": self.fraction, "cap": self.cap, "capped": self.capped,
                "unit": "1 % del bankroll"}


def kelly(p: float, odds: float, p_push: float = 0.0) -> float:
    """Full-Kelly fraction for a bet won with probability ``p`` (conditional on settling) at decimal ``odds``."""
    b = odds - 1.0
    if b <= 0 or not (0 < p < 1):
        return -1.0
    p_win = p * (1.0 - p_push)
    p_lose = (1.0 - p) * (1.0 - p_push)
    return (p_win * b - p_lose) / b


def stake_for(state: str, p_cal: float | None, odds: float | None, p_push: float = 0.0, *,
              cap: float | None = None) -> Stake:
    limit = CAPS.get(state, 0.0) if cap is None else cap
    if p_cal is None or odds is None or limit <= 0:
        return Stake(0.0, -1.0 if p_cal is None or odds is None else kelly(p_cal, odds, p_push), KELLY_FRACTION,
                     limit, False)
    f = kelly(p_cal, odds, p_push)
    if f <= 0:
        return Stake(0.0, f, KELLY_FRACTION, limit, False)
    raw = KELLY_FRACTION * f * 100.0
    units = math.floor(raw / STEP + 1e-9) * STEP
    capped = units > limit
    return Stake(min(units, limit), f, KELLY_FRACTION, limit, capped)
