"""The depth of a selection by the value of its information - ``voi-v1`` (architecture, layer 5). Pure: no clock, no database, no network.

    D0   no candidate with value: no AI at all, only the forecast
    D1   a marginal candidate: the evidence in cache and one fast specialist
    D2   a publishable candidate: research if needed, the specialists in parallel and the Council
    D3   a material contradiction or a highlighted pick: one more targeted round and the escalation to the top model

THE SCORE (one number, the expected money the information can move, in units of 1 % of the bankroll):

    value        = max(ev, 0) x potential stake                 the expected profit at stake (ev per unit, stake in stake-v1 units)
    uncertainty  = 1 + WIDTH_WEIGHT x min(width, WIDTH_CAP) / WIDTH_CAP     the model's interval (p_high - p_low); unknown -> 1, no bonus
    disputes     = 1 + CONTRA_WEIGHT x min(open contradictions, CONTRA_CAP)
    timing       = 0 when fewer minutes than ``router-v1``'s ``research_min_minutes`` are left (nothing can arrive in time),
                   1 up to ``router-v1``'s ``e2_hours_to_kickoff``, TIMING_DAY up to DAY_HOURS, TIMING_FAR beyond (the information will
                   still change: a later checkpoint buys it cheaper)
    voi          = value x p_publish x uncertainty x disputes x timing

    D0  ev missing or <= 0, p_publish <= 0, or timing 0
    D3  voi >= D3_AT, or voi >= D2_AT with a material contradiction or a highlighted pick
    D2  voi >= D2_AT
    D1  any other candidate with value

The score is non-decreasing in every input but the hours to the kick-off, so the depth is monotone in value: more expected value, more stake,
more chance of being published, a wider interval or more contradictions never LOWER it. The constants are engineering choices of this
version, not measured frequencies; a change to any of them is a new version, never an edit."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

from fbi.ai import router
from fbi.intel import decision, stake

VERSION: Final = "voi-v1"

Tier = Literal["D0", "D1", "D2", "D3"]
TIERS: Final[tuple[Tier, ...]] = ("D0", "D1", "D2", "D3")
RANK: Final[dict[Tier, int]] = {t: i for i, t in enumerate(TIERS)}

LEVEL_OF_TIER: Final[dict[Tier, str | None]] = {"D0": None, "D1": "simple", "D2": "complex", "D3": "critical"}
"""The ``router-v1`` level a depth needs at the top: D1 a fast model, D2 the Council's, D3 the escalation's. D0 needs none."""

D2_AT: Final = Decimal("0.02")
"""The score from which a selection is publishable enough for the specialists and the Council (2 % of a unit of expected profit at stake)."""
D3_AT: Final = Decimal("0.10")
"""The score from which a selection is worth the extra round and the top model by itself."""

WIDTH_CAP: Final = Decimal("0.20")
"""An interval of 20 points of probability or more counts as the widest."""
WIDTH_WEIGHT: Final = Decimal("1")
"""The widest interval doubles the score: the information is worth more where the model knows less."""
CONTRA_CAP: Final = 2
CONTRA_WEIGHT: Final = Decimal("0.5")
"""Each open contradiction on the selection adds half, at most two of them (the score at most doubles)."""

LATE_MINUTES: Final = int(router.PARAMS["research_min_minutes"])
"""Fewer minutes than these to the kick-off: no research can be served (``router-v1``, rule 7), so nothing is bought - D0."""
NEAR_HOURS: Final = Decimal(str(router.PARAMS["e2_hours_to_kickoff"]))
"""Up to these hours to the kick-off the information is worth all it can be (``router-v1``'s E2 horizon)."""
DAY_HOURS: Final = Decimal("24")
TIMING_DAY: Final = Decimal("0.75")
TIMING_FAR: Final = Decimal("0.5")

P_MARGINAL: Final = Decimal("0.10")
P_CLEAR: Final = Decimal("0.60")
P_ROBUST: Final = Decimal("0.90")
"""The PROXY of the probability of being published (``publish_proxy``): a rule over the decision layer's own thresholds, not a measured
frequency - no table yet says how often a selection of a given value ends published."""

POTENTIAL_STATE: Final = "APROBADO"
"""The state whose ``stake-v1`` cap bounds the potential stake: what an ordinary approval would stake."""


@dataclass(frozen=True, slots=True)
class VoiInputs:
    """What the depth of one selection reads, as known at one moment."""

    ev: Decimal | None
    """Expected value per unit staked (p_model x odds - 1); None when there is no price."""
    stake_units: Decimal = Decimal(0)
    """The potential stake, in ``stake-v1`` units (1 % of the bankroll)."""
    p_publish: Decimal = Decimal(0)
    """The probability of being published, in [0, 1]."""
    interval_width: Decimal | None = None
    """The model's interval (p_high - p_low), in probability; None when the model gave none."""
    hours_to_kickoff: Decimal | None = None
    """None: unknown, counted as far."""
    open_contradictions: int = 0
    material_contradiction: bool = False
    highlighted: bool = False
    """The pick of the day, a premium pick or the main leg of a parlay."""


@dataclass(frozen=True, slots=True)
class Depth:
    tier: Tier
    score: Decimal
    reason: str
    """``no_value``, ``no_publication``, ``too_late``, ``score``, ``material_contradiction`` or ``highlighted``."""

    def as_json(self) -> dict[str, Any]:
        return {"tier": self.tier, "score": str(self.score.quantize(Decimal("0.000001"))), "reason": self.reason}


def _clip01(x: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), x))


def timing(hours: Decimal | None) -> Decimal:
    """How much of its worth the information keeps at this distance from the kick-off."""
    if hours is None:
        return TIMING_FAR
    if hours * 60 < LATE_MINUTES:
        return Decimal(0)
    if hours <= NEAR_HOURS:
        return Decimal(1)
    if hours <= DAY_HOURS:
        return TIMING_DAY
    return TIMING_FAR


def score(x: VoiInputs) -> Decimal:
    """The value of the information of one selection (see the module's docstring). Never negative."""
    if x.ev is None or x.ev <= 0:
        return Decimal(0)
    value = x.ev * max(Decimal(0), x.stake_units)
    width = Decimal(0) if x.interval_width is None else min(WIDTH_CAP, max(Decimal(0), x.interval_width))
    uncertainty = 1 + WIDTH_WEIGHT * width / WIDTH_CAP
    disputes = 1 + CONTRA_WEIGHT * min(CONTRA_CAP, max(0, x.open_contradictions))
    return value * _clip01(x.p_publish) * uncertainty * disputes * timing(x.hours_to_kickoff)


def depth(x: VoiInputs) -> Depth:
    """The depth of one selection, before budget v3's rails (``allocation`` applies them)."""
    if x.ev is None or x.ev <= 0:
        return Depth("D0", Decimal(0), "no_value")
    if x.p_publish <= 0:
        return Depth("D0", Decimal(0), "no_publication")
    if timing(x.hours_to_kickoff) == 0:
        return Depth("D0", Decimal(0), "too_late")
    s = score(x)
    if s >= D3_AT:
        return Depth("D3", s, "score")
    if s >= D2_AT:
        if x.material_contradiction:
            return Depth("D3", s, "material_contradiction")
        if x.highlighted:
            return Depth("D3", s, "highlighted")
        return Depth("D2", s, "score")
    return Depth("D1", s, "score")


# ── the inputs from stored numbers ─────────────────────────────────────────────────────────────────────────────


def expected_value(p: Decimal | None, odds: Decimal | None) -> Decimal | None:
    return None if p is None or odds is None or odds <= 1 else p * odds - 1


def potential_stake(p_model: Decimal | None, odds: Decimal | None) -> Decimal:
    """What ``stake-v1`` would stake on the selection as an ordinary approval (quarter Kelly, rounded down, capped)."""
    if p_model is None or odds is None:
        return Decimal(0)
    return Decimal(str(stake.stake_for(POTENTIAL_STATE, float(p_model), float(odds)).units))


def publish_proxy(*, ev: Decimal | None, edge: Decimal | None, ev_low: Decimal | None) -> Decimal:
    """The proxy of the probability of being published, over the decision layer's thresholds (``fbi.intel.decision.EV_MIN`` and
    ``EDGE_MIN``): 0 without value; ``P_MARGINAL`` below either minimum (it could still cross with research); ``P_ROBUST`` when even the
    pessimistic probability (p_low) earns the minimum; ``P_CLEAR`` otherwise. Non-decreasing in each input."""
    if ev is None or ev <= 0:
        return Decimal(0)
    if ev < Decimal(str(decision.EV_MIN)) or (edge is not None and edge < Decimal(str(decision.EDGE_MIN))):
        return P_MARGINAL
    if ev_low is not None and ev_low >= Decimal(str(decision.EV_MIN)):
        return P_ROBUST
    return P_CLEAR


def interval_width(p_model: Decimal | None, p_low: Decimal | None, p_high: Decimal | None = None) -> Decimal | None:
    """p_high - p_low; with p_low only, twice the distance to it (a symmetric interval); None without p_low."""
    if p_low is None:
        return None
    if p_high is not None:
        return max(Decimal(0), p_high - p_low)
    if p_model is None:
        return None
    return max(Decimal(0), 2 * (p_model - p_low))


PARAMS: Final[dict[str, str]] = {
    "d2_at": str(D2_AT), "d3_at": str(D3_AT), "width_cap": str(WIDTH_CAP), "width_weight": str(WIDTH_WEIGHT),
    "contra_cap": str(CONTRA_CAP), "contra_weight": str(CONTRA_WEIGHT), "late_minutes": str(LATE_MINUTES),
    "near_hours": str(NEAR_HOURS), "day_hours": str(DAY_HOURS), "timing_day": str(TIMING_DAY), "timing_far": str(TIMING_FAR),
    "p_marginal": str(P_MARGINAL), "p_clear": str(P_CLEAR), "p_robust": str(P_ROBUST), "potential_state": POTENTIAL_STATE}
"""Every constant of this version, as the reports print it."""
