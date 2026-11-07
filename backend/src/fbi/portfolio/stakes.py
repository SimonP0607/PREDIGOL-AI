"""The portfolio's stakes (``portfolio-stake-v1``): three steps, each of which can only lower the one before.

    1 individual  stake-v1 itself (``fbi.intel.stake.stake_for``: a quarter of Kelly on the CALIBRATED probability, rounded
                  down to a quarter unit, capped by the state) - imported, never re-derived. The cap is the one
                  select_day would use: PICK_PREMIUM for a premium approval, the row's own decision-v1 state otherwise.
    2 scaled      a selection that shares a budget with others (``correlation.groups``) is scaled by
                  1 / (1 + the sum of its budget correlations with the others staked), rounded down: two selections of
                  one match (0.60) keep 1/1.6 of their stakes each, an unrelated selection keeps all of its own.
    3 final       held to the room the exposure limits leave (``exposure.Book``), taken in the day's order.

NEVER a stake for a selection that is not RECOMMENDED: the only exception is the explicitly HYPOTHETICAL what-if, where a
CAUTION selection is measured at stake-v1's own CAUTELA cap and every such stake is labelled ``hypothetical``. Never above
stake-v1: ``final <= scaled <= individual <= stake-v1's cap`` holds by construction and is checked (``InvariantError``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from fbi.intel import stake as staking
from fbi.portfolio import exposure
from fbi.portfolio.correlation import Correlation, groups
from fbi.portfolio.selection import Selection

VERSION: Final = "portfolio-stake-v1"
HYPOTHETICAL_STATES: Final = frozenset({"CAUTION"})
"""What the what-if lets in, and only for measurement."""


class InvariantError(AssertionError):
    """A portfolio stake above the stake-v1 stake it came from: a bug, never a result."""


def cap_state(s: Selection, *, hypothetical: bool = False) -> str | None:
    """The stake-v1 state whose cap a selection is staked under, or ``None`` when it gets no stake."""
    if s.state_v2 == "RECOMMENDED":
        return "PICK_PREMIUM" if s.premium else s.state_v1
    if hypothetical and s.state_v2 in HYPOTHETICAL_STATES:
        return "CAUTELA"
    return None


def individual(s: Selection, *, hypothetical: bool = False) -> staking.Stake | None:
    state = cap_state(s, hypothetical=hypothetical)
    if state is None:
        return None
    return staking.stake_for(state, s.p_cal, s.odds, s.p_push)


def scale_factors(staked: Sequence[int], correlations: Sequence[Correlation]) -> dict[int, float]:
    """1 / (1 + sum of budget correlations with the OTHER staked selections), for each staked selection."""
    ids = set(staked)
    load = dict.fromkeys(staked, 0.0)
    for c in correlations:
        if c.a in ids and c.b in ids and c.budget_rho > 0:
            load[c.a] += c.budget_rho
            load[c.b] += c.budget_rho
    return {i: 1.0 / (1.0 + x) for i, x in load.items()}


@dataclass(frozen=True, slots=True)
class PortfolioStake:
    decision_id: int
    cap_state: str | None
    individual: staking.Stake | None
    scale: float
    scaled: float
    final: float
    binding: exposure.Limit | None
    hypothetical: bool
    why: str

    def as_json(self) -> dict[str, Any]:
        return {"decision_id": self.decision_id, "stake_v1_state": self.cap_state,
                "individual": None if self.individual is None else self.individual.as_json(),
                "correlation_scale": round(self.scale, 6), "scaled_units": self.scaled, "final_units": self.final,
                "binding_limit": self.binding, "hypothetical": self.hypothetical, "why": self.why}


def allocate(ordered: Sequence[Selection], correlations: Sequence[Correlation], *, hypothetical: bool = False,
             book: exposure.Book | None = None) -> tuple[list[PortfolioStake], exposure.Book]:
    """The stakes of the selections, in the order given (the day's order: the first take the room first)."""
    book = book or exposure.Book()
    firsts = {s.decision_id: individual(s, hypothetical=hypothetical) for s in ordered}
    staked = [i for i, st in firsts.items() if st is not None and st.units > 0]
    factors = scale_factors(staked, correlations)
    grouped = {i for g in groups(staked, correlations) for i in g}
    out: list[PortfolioStake] = []
    for s in ordered:
        first = firsts[s.decision_id]
        state = cap_state(s, hypothetical=hypothetical)
        hypo = state is not None and s.state_v2 != "RECOMMENDED"
        if first is None:
            out.append(PortfolioStake(s.decision_id, None, None, 1.0, 0.0, 0.0, None, False,
                                      f"{s.state_v2}: no stake (only RECOMMENDED is staked)"))
            continue
        if first.units <= 0:
            out.append(PortfolioStake(s.decision_id, state, first, 1.0, 0.0, 0.0, None, hypo,
                                      "stake-v1 gives nothing (Kelly at or below zero, or below a quarter unit)"))
            continue
        factor = factors.get(s.decision_id, 1.0)
        scaled = exposure.floor_step(first.units * factor)
        check = book.check(s, scaled)
        final = check.allowed
        if not (final <= scaled <= first.units <= first.cap + 1e-9):
            raise InvariantError(f"decision {s.decision_id}: {final} / {scaled} / {first.units} above stake-v1 ({first.cap})")
        book.add(s, final)
        why = "stake-v1"
        if s.decision_id in grouped:
            why += f", scaled x{factor:.3f} for a shared budget"
        if check.binding is not None:
            why += f", held by the {check.binding} limit"
        out.append(PortfolioStake(s.decision_id, state, first, factor, scaled, final, check.binding, hypo, why))
    return out, book
