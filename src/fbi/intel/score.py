"""PrediGol Pick Score - ``pick-score-v1``: one number from 0 to 100 that says how well-founded a candidate is, and
exactly why. It ranks; it never creates value: a candidate is APPROVED by the filters (``fbi.intel.decision``), and its
stake comes from the calibrated probability and the price (``fbi.intel.stake``), not from the score.

Twelve components, each scaled to [0, 1] by a fixed linear rule and weighted (weights sum to 100):

    ev               15   calibrated EV, 0 at 0 %, 1 at >= 8 %
    edge             10   calibrated probability - de-vigged market, 0 at 0, 1 at >= 5 points
    calibration      10   the market calibrator's out-of-sample ECE, 1 at <= 1 %, 0 at >= 5 %
    model_history    10   out-of-sample closing-line value of the market's calibrated rule, 0 at <= -3 %, 1 at >= +2 %
    data_quality     10   the competition's data class and the match's validation
    price_freshness   5   age of the price, 1 at <= 10 min, 0 at >= 3 h
    market_quality   10   bookmakers quoting (2 -> 0, >= 8 -> 1) and the margin (>= 10 % -> 0, <= 4 % -> 1)
    context_depth    10   FULL 1, PARTIAL 0.6, LIMITED 0.3, AI_OFF 0.3, PENDING 0.2
    consensus         5   share of the other models that also see the selection above the market
    uncertainty       5   width of the model's interval, 1 at <= 4 points, 0 at >= 25
    context_risk      5   1 - the review's risk (REJECT 1, DOWNGRADE 0.6, each hard signal 0.5, each soft 0.2)
    clv_type          5   closing-line value of this kind of pick over the last 30 days, 0 at <= -5 %, 1 at >= +2 %

A missing input scores 0 for its component and says so (``detail``): an unknown never counts as good.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VERSION = "pick-score-v1"
WEIGHTS: dict[str, int] = {"ev": 15, "edge": 10, "calibration": 10, "model_history": 10, "data_quality": 10,
                           "price_freshness": 5, "market_quality": 10, "context_depth": 10, "consensus": 5,
                           "uncertainty": 5, "context_risk": 5, "clv_type": 5}
CONTEXT_DEPTH = {"FULL": 1.0, "PARTIAL": 0.6, "LIMITED": 0.3, "AI_OFF": 0.3, "PENDING": 0.2}
DATA_CLASS = {"MODEL_READY": 1.0, "PARTIAL": 0.6, "PRODUCT_ONLY": 0.2, "INSUFFICIENT": 0.0}


def lin(x: float | None, lo: float, hi: float) -> float | None:
    if x is None:
        return None
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


@dataclass(frozen=True)
class ScoreInputs:
    ev_cal: float | None = None
    edge_cal: float | None = None
    ece: float | None = None
    rule_clv: float | None = None
    data_class: str | None = None
    quarantined: bool = False
    price_age_min: float | None = None
    n_bookmakers: int | None = None
    overround: float | None = None
    context_status: str = "PENDING"
    consensus: float | None = None
    width: float | None = None
    review_decision: str | None = None
    hard_signals: int = 0
    soft_signals: int = 0
    type_clv: float | None = None


@dataclass(frozen=True)
class Score:
    total: float
    components: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "total": self.total, "components": self.components}


def score(x: ScoreInputs) -> Score:
    risk = 0.0
    if x.review_decision == "REJECT":
        risk = 1.0
    elif x.review_decision == "DOWNGRADE":
        risk = 0.6
    risk = min(1.0, risk + 0.5 * x.hard_signals + 0.2 * x.soft_signals)
    if x.data_class is None:
        dq: float | None = None
    else:
        dq = 0.0 if x.quarantined else DATA_CLASS.get(x.data_class, 0.5)
    market_q: float | None = None
    books = lin(None if x.n_bookmakers is None else float(x.n_bookmakers), 2, 8)
    margin = lin(None if x.overround is None else 0.10 - x.overround, 0.0, 0.06)
    if books is not None:
        market_q = 0.6 * books + 0.4 * (margin if margin is not None else 0.5)
    values: dict[str, tuple[float | None, str]] = {
        "ev": (lin(x.ev_cal, 0.0, 0.08), f"EV calibrado {_pct(x.ev_cal)}"),
        "edge": (lin(x.edge_cal, 0.0, 0.05), f"edge calibrado {_pct(x.edge_cal)}"),
        "calibration": (lin(None if x.ece is None else 0.05 - x.ece, 0.0, 0.04), f"ECE fuera de muestra {_pct(x.ece)}"),
        "model_history": (lin(x.rule_clv, -0.03, 0.02), f"CLV fuera de muestra del mercado {_pct(x.rule_clv)}"),
        "data_quality": (dq, f"datos {x.data_class or 'sin evaluar'}" + (" (cuarentena)" if x.quarantined else "")),
        "price_freshness": (lin(None if x.price_age_min is None else 180 - x.price_age_min, 0.0, 170.0),
                            "precio de hace " + ("?" if x.price_age_min is None else f"{x.price_age_min:.0f} min")),
        "market_quality": (market_q, f"{x.n_bookmakers or 0} casas, margen {_pct(x.overround)}"),
        "context_depth": (CONTEXT_DEPTH.get(x.context_status, 0.2), f"contexto {x.context_status}"),
        "consensus": (x.consensus, "acuerdo entre modelos " + ("?" if x.consensus is None else f"{x.consensus:.0%}")),
        "uncertainty": (lin(None if x.width is None else 0.25 - x.width, 0.0, 0.21),
                        "intervalo del modelo " + ("?" if x.width is None else f"{x.width * 100:.1f} pts")),
        "context_risk": (1.0 - risk, f"revisión {x.review_decision or 'ninguna'}, {x.hard_signals} señales duras, "
                                     f"{x.soft_signals} blandas"),
        "clv_type": (lin(x.type_clv, -0.05, 0.02), f"CLV del tipo de pick (30 d) {_pct(x.type_clv)}"),
    }
    comps: list[dict[str, Any]] = []
    total = 0.0
    for key, weight in WEIGHTS.items():
        v, detail = values[key]
        pts = 0.0 if v is None else round(weight * v, 2)
        total += pts
        comps.append({"key": key, "weight": weight, "value": None if v is None else round(v, 4), "points": pts,
                      "detail": detail + (" (sin dato: 0)" if v is None else "")})
    return Score(round(min(100.0, total), 2), comps)


def _pct(x: float | None) -> str:
    return "?" if x is None else f"{x * 100:+.1f} %"
