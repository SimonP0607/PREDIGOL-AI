"""The day's money per selection - ``voi-v1`` (architecture, layer 5). Pure: a day's candidates as of a moment and budget v3's figures in, each
selection's budget out. Budget v3 (``fbi.ai.budget_v3``) still allocates the month to the day; this module only shares the DAY, and never
above what budget v3 lets the day spend.

THE RAILS (budget v3's states stay hard):

    the money     limit = min(day's allocation, day's hard cap) - what the day has spent; nothing above it is ever shared. EXHAUSTED shares
                  nothing.
    the depth     a selection never gets a depth whose model the state forbids (``router.permitted_levels``): CHEAP_ONLY keeps D1 at most,
                  REDUCED D2 at most (no top model), EXHAUSTED D0.

THE SHARE at a checkpoint (``first``, ``pre``, ``final``, ``request``, the passes of ``fbi.ai.usage.PASS_SHARE``):

    pass_room        what this checkpoint may reach: min(limit, allocation x PASS_SHARE[checkpoint]) - spent. The rest of the limit is the
                     RESERVE FOR THE LATER CHECKPOINTS, the line-ups' among them (the final pass is never left without money)
    escalations      while the state lets the top model run and some selection is D3: pass_room x ``router-v1``'s Opus share of the scope
    distributable    pass_room - escalations, shared by depth weight (``TIER_WEIGHT``): D0 nothing, D1 1, D2 3, D3 6. No selection gets
                     more than ``MAX_SELECTION_SHARE`` of it, and with a LEARNED cost per selection at its depth no more than
                     ``LEARNED_HEADROOM`` times it. What no selection takes is left unallocated, never spread.

THE LEARNING. ``corrected_weights`` moves the weights by the cost of a useful signal measured per depth (``eval-bench-v1``'s definition, over
``intel.agent_attributions``): a depth whose useful signal is dearer than the median of the depths gets less weight, a cheaper one more,
within [1/``LEARN_CLAMP``, ``LEARN_CLAMP``] and never above the weight of a deeper depth. Without a measure the weight stays."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any, Final

from fbi.ai import router
from fbi.ai.usage import PASS_SHARE, Budget
from fbi.budgeting.tiers import LEVEL_OF_TIER, RANK, TIERS, VERSION, Depth, Tier, VoiInputs, depth

TIER_WEIGHT: Final[dict[Tier, Decimal]] = {"D0": Decimal(0), "D1": Decimal(1), "D2": Decimal(3), "D3": Decimal(6)}
"""A D2 selection is worth three D1 ones (specialists in parallel and the Council against one fast specialist); a D3 twice a D2."""
MAX_SELECTION_SHARE: Final = Decimal("0.25")
"""No selection takes more than a quarter of what a checkpoint shares, however few the candidates."""
LEARNED_HEADROOM: Final = Decimal("1.5")
"""With a measured cost per selection at a depth, a selection gets at most one and a half times it."""
LEARN_CLAMP: Final = Decimal("2")
CENT: Final = Decimal("0.000001")


def _down(x: Decimal) -> Decimal:
    """Money rounded DOWN to the micro-dollar: a sum of shares can never round above the whole."""
    return max(Decimal(0), x).quantize(CENT, rounding=ROUND_DOWN)


def max_tier(state: str, *, scope: router.Scope = "production") -> Tier:
    """The deepest depth budget v3's state lets run: the deepest whose model ``router.permitted_levels`` leaves."""
    levels = router.permitted_levels(state)  # type: ignore[arg-type]
    best: Tier = "D0"
    for t in TIERS:
        level = LEVEL_OF_TIER[t]
        if level is None or level in levels:
            best = t
    return best


def escalation_share(scope: router.Scope = "production") -> Decimal:
    """``router-v1``'s share of the day for the top model in the scope."""
    return Decimal(str(router.PARAMS["share"]["opus"][scope]))


def corrected_weights(cost_per_useful: Mapping[str, Decimal | None], base: Mapping[Tier, Decimal] = TIER_WEIGHT) -> dict[Tier, Decimal]:
    """The weights moved by the cost of a useful signal per depth: weight x (median cost / the depth's cost), clamped to
    [1/LEARN_CLAMP, LEARN_CLAMP] times the base, then made non-decreasing with the depth. D0 stays 0; a depth without a measure keeps its
    base weight."""
    measured = {t: c for t, c in cost_per_useful.items() if t in base and t != "D0" and c is not None and c > 0}
    out = dict(base)
    if len(measured) >= 2:
        median = Decimal(str(statistics.median(measured.values())))
        for t, c in measured.items():
            factor = min(LEARN_CLAMP, max(1 / LEARN_CLAMP, median / c))
            out[t] = base[t] * factor  # type: ignore[index]
    running = Decimal(0)
    for t in TIERS:
        running = max(running, out[t])
        out[t] = running if t != "D0" else Decimal(0)
    return out


@dataclass(frozen=True, slots=True)
class Candidate:
    key: str
    """The selection: ``<fixture>:<market>:<selection>:<line>``."""
    inputs: VoiInputs


@dataclass(frozen=True, slots=True)
class Share:
    key: str
    natural: Depth
    """The depth the value of the information asks for."""
    tier: Tier
    """The depth after budget v3's rails."""
    budget_usd: Decimal
    capped_by: str | None = None
    """``rail`` (the state lowered the depth), else the tightest cut of the money - ``learned_cost`` or ``selection_share`` - or None."""

    def as_json(self) -> dict[str, Any]:
        return {"key": self.key, "natural": self.natural.as_json(), "tier": self.tier, "budget_usd": str(self.budget_usd),
                "capped_by": self.capped_by}


@dataclass(frozen=True, slots=True)
class Allocation:
    version: str
    state: str
    checkpoint: str
    max_tier: Tier
    limit_usd: Decimal
    """min(allocation, hard cap) - spent today: the most budget v3 lets the rest of the day spend."""
    pass_room_usd: Decimal
    reserve_later_usd: Decimal
    """Kept for the later checkpoints, the line-ups' among them."""
    reserve_escalations_usd: Decimal
    distributable_usd: Decimal
    shares: tuple[Share, ...]
    weights: Mapping[Tier, Decimal] = field(default_factory=dict)

    @property
    def allocated_usd(self) -> Decimal:
        return sum((s.budget_usd for s in self.shares), Decimal(0))

    @property
    def unallocated_usd(self) -> Decimal:
        return self.distributable_usd - self.allocated_usd

    def by_tier(self) -> dict[Tier, int]:
        out: dict[Tier, int] = dict.fromkeys(TIERS, 0)
        for s in self.shares:
            out[s.tier] += 1
        return out

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "state": self.state, "checkpoint": self.checkpoint, "max_tier": self.max_tier,
                "limit_usd": str(self.limit_usd), "pass_room_usd": str(self.pass_room_usd),
                "reserve_later_usd": str(self.reserve_later_usd), "reserve_escalations_usd": str(self.reserve_escalations_usd),
                "distributable_usd": str(self.distributable_usd), "allocated_usd": str(self.allocated_usd),
                "unallocated_usd": str(self.unallocated_usd), "by_tier": self.by_tier(),
                "weights": {t: str(w) for t, w in self.weights.items()}, "shares": [s.as_json() for s in self.shares]}


def allocate(candidates: Sequence[Candidate], budget: Budget, *, checkpoint: str = "pre", scope: router.Scope = "production",
             learned_cost: Mapping[str, Decimal] | None = None, weights: Mapping[Tier, Decimal] | None = None) -> Allocation:
    """Each candidate's budget at a checkpoint (see the module's docstring). ``budget`` is budget v3's figures of the day as of the moment
    (``fbi.ai.budget_v3.budget``); ``learned_cost`` the measured cost of a selection at each depth, when there is one."""
    if checkpoint not in PASS_SHARE:
        raise ValueError(f"unknown checkpoint {checkpoint!r}: one of {sorted(PASS_SHARE)}")
    w = dict(TIER_WEIGHT if weights is None else weights)
    top = max_tier(budget.state, scope=scope)
    exhausted = budget.state == "EXHAUSTED"
    limit = Decimal(0) if exhausted else _down(min(budget.daily, budget.cap) - budget.spent_today)
    reach = min(budget.daily * PASS_SHARE[checkpoint], budget.daily, budget.cap)
    pass_room = Decimal(0) if exhausted else min(limit, _down(reach - budget.spent_today))
    later = limit - pass_room

    natural = [(c, depth(c.inputs)) for c in candidates]
    tiers: list[tuple[Candidate, Depth, Tier]] = []
    for c, d in natural:
        tier = d.tier if RANK[d.tier] <= RANK[top] else top
        tiers.append((c, d, tier))
    escalations = _down(pass_room * escalation_share(scope)) if any(t == "D3" for _, _, t in tiers) else Decimal(0)
    distributable = pass_room - escalations

    total_weight = sum((w[t] for _, _, t in tiers), Decimal(0))
    ceiling = _down(distributable * MAX_SELECTION_SHARE)
    shares: list[Share] = []
    for c, d, tier in tiers:
        capped: str | None = "rail" if tier != d.tier else None
        amount = Decimal(0) if total_weight <= 0 or w[tier] <= 0 else _down(distributable * w[tier] / total_weight)
        if amount > ceiling:
            amount, capped = ceiling, capped or "selection_share"
        known = None if learned_cost is None else learned_cost.get(tier)
        if known is not None and amount > _down(known * LEARNED_HEADROOM):
            amount, capped = _down(known * LEARNED_HEADROOM), "rail" if capped == "rail" else "learned_cost"
        shares.append(Share(c.key, d, tier, amount, capped))
    return Allocation(VERSION, budget.state, checkpoint, top, limit, pass_room, later, escalations, distributable, tuple(shares), w)
