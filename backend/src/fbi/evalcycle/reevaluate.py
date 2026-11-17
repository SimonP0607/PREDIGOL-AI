"""E3 by code: the official line-up against the selection (IA-106, plan piece AD-D07, ``eval-verdict-v1``). Pure.

When the official line-up arrives, each selection the cycle holds is judged again, by code and in this order:

1. **The line-up.** The starters of each side read (``reading`` of E3) against the players the selection depends on (E1's table,
   ``fbi.evalcycle.dependency``): the shift of every listed player whose side is known is added to the figure (``dependency.apply``).
2. **The decision.** decision-v2 decides again at the moment of E3 when there is still time (at least decision-v1's floor before
   kick-off): its state and reason, the figure it judged and the price of the odds book in force with its age (``Decided``). Closer to
   kick-off decision-v2 rejects everything by rule, so the last decision stands and only the price is read again (``Priced``).
3. **The value at that price.** The figure with the line-up against the price read: the expected value and the edge, held to
   decision-v1's own minimums (``EV_MIN``, ``EDGE_MIN``, imported - never lowered).

Then:

* a selection waiting for its line-up or confirmed in the shadow is **confirmed** (``confirmada``: it was waiting; ``sigue_igual``: it
  was confirmed and nothing moved; ``modificada``: confirmed with a new figure or price) or **withdrawn** (``retirada``) with ONE cause:
  the new decision against it (its blocker), the price old or gone, the line-up against it (a player it depends on is out and the value
  is gone: ``alineacion_en_contra``), or the value gone at the new price;
* a selection that still waits for what it depends on (its side's line-up is not known) stays **pendiente** - a failed or missing E3
  never confirms a selection;
* a selection that was not confirmed can be confirmed only by a new decision that approves it and keeps its value with the line-up;
  otherwise it keeps the decision's state (``sigue_igual`` or ``modificada``).

Everything here is code and data with its ``known_at``; no text read from the internet decides and no model of language takes a
selection up or down. The same function judges E4 (with the match read again: ``fbi.evalcycle.conditions``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from fbi.evalcycle import dependency as dep_mod
from fbi.evalcycle.dependency import Dependency
from fbi.intel.decision import EDGE_MIN, EV_MIN, ev_of
from fbi.lifecycle import machine

VERSION: Final = "eval-verdict-v1"

WAITING: Final = frozenset({"pendiente_alineaciones", "confirmada_sombra"})
"""The states E3 can confirm or withdraw (the machine's moves to ``retirada`` start from these)."""
CONFIRMED: Final = "confirmada_sombra"
PENDING: Final = "pendiente_alineaciones"
WAITS_REASON: Final = "depende_de_alineacion"
MOVED_P: Final = 0.005
MOVED_ODDS: Final = 0.01
"""A confirmed selection whose figure moves by half a point or whose price moves by a hundredth is ``modificada``."""

VERDICTS: Final = ("lectura", "confirmada", "sigue_igual", "modificada", "retirada", "pendiente", "descartada")


@dataclass(frozen=True, slots=True)
class Standing:
    """The selection as the cycle holds it before this evaluation: its newest verdict."""

    state: str
    reason: str
    p: float | None
    odds: float | None
    verdict_id: int | None = None
    p_push: float = 0.0


@dataclass(frozen=True, slots=True)
class Decided:
    """decision-v2 at this evaluation, read as the cycle reads it (``derive.map_decision``), with what it judged."""

    decision_id: int
    state: str
    reason: str
    p: float | None
    """The figure it judged: the calibrated one when there is one, the model's otherwise."""
    odds: float | None
    p_market: float | None
    price_state: str | None
    p_push: float = 0.0


@dataclass(frozen=True, slots=True)
class Priced:
    """The price read again when decision-v2 can no longer decide (closer to kick-off than its floor)."""

    odds: float | None
    p_market: float | None
    state: str
    age_minutes: float | None = None


@dataclass(frozen=True, slots=True)
class Reading:
    state: str
    reason: str
    cause: str


def reading(state: str, reason: str, dep: Dependency | None) -> Reading:
    """E1 and E2: the decision's state, except that a selection the line-up decides is waiting for it, never confirmed blind."""
    if state == CONFIRMED and dep is not None and (dep.group == dep_mod.ALWAYS or dep.waits):
        return Reading(PENDING, WAITS_REASON, "espera_alineacion")
    return Reading(state, reason, "decision")


def reread(standing: Standing | None, state: str, reason: str, dep: Dependency | None) -> Reading:
    """E2: the new decision read like E1's (``reading``), against what the cycle held - a selection that was waiting or confirmed and
    that the new decision no longer holds is withdrawn (its blocker), and a withdrawn one stays withdrawn until it comes back."""
    rd = reading(state, reason, dep)
    if standing is None:
        return rd
    if standing.state in WAITING and rd.state not in WAITING:
        return Reading("retirada", _withdraw_reason(rd.reason), "decision_en_contra")
    if standing.state == "retirada" and rd.state in ("en_evaluacion", "en_investigacion"):
        return Reading("retirada", standing.reason, "sigue_retirada")
    return rd


@dataclass(frozen=True, slots=True)
class Outcome:
    verdict: str
    state: str
    reason: str
    cause: str
    p_before: float | None
    p_after: float | None
    odds_before: float | None
    odds_after: float | None
    price_state: str | None
    ev_after: float | None
    edge_after: float | None
    lineup: Mapping[str, Any] = field(default_factory=dict)

    @property
    def withdrawn(self) -> bool:
        return self.verdict == "retirada"


def _withdraw_reason(reason: str) -> str:
    return reason if reason in machine.REASONS["retirada"] else "sin_motivo_conocido"


def _moved(p0: float | None, p1: float | None, o0: float | None, o1: float | None) -> bool:
    if (p0 is None) != (p1 is None) or (o0 is None) != (o1 is None):
        return True
    return (p0 is not None and p1 is not None and abs(p1 - p0) >= MOVED_P) or (
        o0 is not None and o1 is not None and abs(o1 - o0) >= MOVED_ODDS)


def reassess(standing: Standing, dep: Dependency | None, starters: Mapping[str, frozenset[int]], decided: Decided | None,
             priced: Priced | None) -> Outcome:
    """E3 (and E4) of one selection. ``starters``: the official starters of each side read by the moment (a side absent: not known yet).
    ``decided``: decision-v2 at this moment, or None when it can no longer decide (then ``priced`` is the price read again)."""
    applied = dep_mod.apply(dep, starters) if dep is not None and dep.status == dep_mod.COMPUTED else None
    shift = 0.0
    if applied is not None and applied.p is not None and dep is not None and dep.p_base is not None:
        shift = applied.p - dep.p_base
    base_p = decided.p if decided is not None and decided.p is not None else standing.p
    p_after = None if base_p is None else min(1.0, max(0.0, base_p + shift))
    if decided is not None:
        odds, p_market, price_state, p_push = decided.odds, decided.p_market, decided.price_state, decided.p_push
    elif priced is not None:
        odds, p_market, price_state, p_push = priced.odds, priced.p_market, priced.state, standing.p_push
    else:
        odds, p_market, price_state, p_push = None, None, "sin_precio", standing.p_push
    ev = None if p_after is None or odds is None else ev_of(p_after, odds, p_push)
    edge = None if p_after is None or p_market is None else p_after - p_market
    value_ok = ev is not None and ev >= EV_MIN and edge is not None and edge >= EDGE_MIN
    lineup: dict[str, Any] = {"sides": sorted(starters), "shift": round(shift, 6)}
    if applied is not None:
        lineup.update(missing=list(applied.missing), starting=list(applied.starting), unseen=list(applied.unseen))
    needs_line_up = dep is not None and (dep.group == dep_mod.ALWAYS or dep.waits)
    doubtful = {p.provider_player_id for p in (dep.players if dep is not None else ()) if p.doubtful}
    still_waiting = needs_line_up and (not starters or bool(doubtful & set(applied.unseen if applied else ())))

    def out(verdict: str, state: str, reason: str, cause: str) -> Outcome:
        return Outcome(verdict, state, reason, cause, standing.p, p_after, standing.odds, odds, price_state, ev, edge, lineup)

    cur = standing.state
    if cur in WAITING:
        if decided is not None and decided.state not in WAITING:
            return out("retirada", "retirada", _withdraw_reason(decided.reason), "decision_en_contra")
        if price_state != "vigente":
            return out("retirada", "retirada", "precio_antiguo" if price_state == "antiguo" else "sin_precio", "precio")
        if still_waiting and cur == PENDING:
            return out("pendiente", PENDING, WAITS_REASON, "sin_alineacion")
        if not value_ok:
            against = applied is not None and bool(applied.missing) and shift < 0
            return out("retirada", "retirada", "alineacion_en_contra" if against else "valor_insuficiente",
                       "alineacion" if against else "valor")
        reason = decided.reason if decided is not None and decided.state == CONFIRMED else (
            standing.reason if cur == CONFIRMED else "cumple_todo")
        if reason not in machine.REASONS[CONFIRMED]:
            reason = "cumple_todo"
        if cur == PENDING:
            return out("confirmada", CONFIRMED, reason, "alineacion_confirma")
        return out("modificada" if _moved(standing.p, p_after, standing.odds, odds) else "sigue_igual", CONFIRMED, reason, "confirmada")
    if decided is None:
        return out("sigue_igual", cur, standing.reason, "sin_decision")
    if decided.state == CONFIRMED:
        if value_ok and price_state == "vigente" and not still_waiting:
            return out("confirmada", CONFIRMED, decided.reason, "decision")
        reason = "valor_insuficiente" if not value_ok else ("precio_antiguo" if price_state != "vigente" else "en_curso")
        state, why = "en_evaluacion", reason
    else:
        state, why = decided.state, decided.reason
    if cur == "retirada" and state in ("en_evaluacion", "en_investigacion"):
        state, why = cur, standing.reason  # withdrawn it stays, until it comes back or closes
    moved = _moved(standing.p, p_after, standing.odds, odds)
    return out("modificada" if moved else "sigue_igual", state, why, "decision")
