"""The contradictions of the Council v2 (``council-contra-v1``, part of ``council-protocol-v1``): pure, total and deterministic.

``contra-v1`` (``fbi.ai.contra``) finds the contradictions IN THE PACKAGE before the agents speak - a key absence, a rotation, a gap
between the model and the market, evidence in conflict, two assessments at odds. This module finds the ones BETWEEN THE VOICES once they
have spoken, one selection at a time, and the check that keeps a fact from being counted twice:

    kind             code  fires when                                                                         material when
    agent_vs_agent   AA1   one specialist SUPPORTs the selection and another is against it (CONCERN or       both sides have weight
                           REJECT_SIGNAL)
    agent_vs_model   AM1   a specialist is against a selection the model sees value in (edge > 0)             weight > 0 and the
                     AM2   a specialist SUPPORTs a selection the model sees no value in (edge <= 0)          agent brings what the
                                                                                                              model did not read
    agent_vs_market  AK1   a specialist SUPPORTs a selection the market moved away from (its fair            weight > 0 and a price
                           probability fell by MARKET_MOVE_POINTS or more since opening, or steam down)      that is not stale
                     AK2   a specialist is against a selection the market moved toward (it rose by as
                           much, or steam up)
    already_known    KN1   every signal that drove the stance is one the model already reads (MODEL_KNOWS)  never: it discounts
                     KN2   the market already moved the way the stance points, by MARKET_MOVE_POINTS or     never: the price
                           more                                                                               already has it

"Against" and "in favour" are the attribution's (``fbi.ai.agents.attribution.polarity_of``): one vocabulary, not two. A NEUTRAL stance
takes no side and fires nothing. A finding names its candidate (``c<n>``), the agent versions it involves, the ids of their runs
(``ai.agent_runs``) and the references (``E:``/``P:``) their stances rested on; ``detail`` holds codes and numbers computed here, never a
text that came from outside.

THE MODEL ALREADY KNEW (KN1). The model of goals and result reads the features of ``fbi.features.engine`` (``fv2.1.0``): ratings, form,
home and away splits, rest days, strength of schedule, league context. It reads NO absence, NO line-up, no stakes, no head-to-head, no
referee and no news - so an absence is never "already in the model" in this version, and a stance driven by one is new information. The
model of the counts (``family-v1``, ``fbi.families.forecast``) reads the teams' rates and, for the cards, the referee's multiplier. A
stance whose every driver is one of those adds nothing the model's probability did not already price: counting it would count the same
fact twice. Its weight is scaled by its NOVELTY (the share of its drivers the model does not read; a stance with no driver is wholly
novel) - and a wholly known stance weighs nothing in the baseline. The gap between the model and the market (``MODEL_MARKET_GAP``) is the
model's own output: never news about it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal, get_args

from fbi.ai.agents.attribution import polarity_of
from fbi.ai.contracts.base import GOALS_RESULT
from fbi.market import signals as market_signals

VERSION: Final = "council-contra-v1"

Kind = Literal["agent_vs_agent", "agent_vs_model", "agent_vs_market", "already_known"]
KINDS: Final = get_args(Kind)
Code = Literal["AA1", "AM1", "AM2", "AK1", "AK2", "KN1", "KN2"]
CODES: Final = get_args(Code)
KIND_OF: Final[Mapping[str, Kind]] = {"AA1": "agent_vs_agent", "AM1": "agent_vs_model", "AM2": "agent_vs_model", "AK1": "agent_vs_market",
                                      "AK2": "agent_vs_market", "KN1": "already_known", "KN2": "already_known"}

MARKET_MOVE_POINTS: Final = market_signals.STEAM_MIN_POINTS
"""How far the market's fair probability must have moved since opening, in points (0.01 of probability), to be a move a stance can
contradict or that already holds it: the same three points ``market-signals-v1`` calls a move no ordinary re-quote explains."""

_GOALS_RESULT_KNOWS: Final = frozenset({"FORM", "VENUE", "SCHEDULE", "MODEL_MARKET_GAP"})
MODEL_KNOWS: Final[Mapping[str, frozenset[str]]] = {
    **dict.fromkeys(GOALS_RESULT, _GOALS_RESULT_KNOWS),
    "CORNERS": frozenset({"RATE", "MODEL_MARKET_GAP"}),
    "CARDS": frozenset({"RATE", "REFEREE", "MODEL_MARKET_GAP"}),
}
"""The signal codes (``aa-v1``) each family's model already reads, so that a stance driven only by them is not new information.

    goals and result  FORM (``*_ppg5``, ``*_gf_avg5``, ``*_elo_resid10``), VENUE (``*_gf_home5``..., ``is_neutral``), SCHEDULE
                      (``*_rest_days``, ``*_sos5``: rest and the strength of the schedule; the NEXT match is not a feature, a documented
                      limit of this table), MODEL_MARKET_GAP (the model's own output)
    corners           RATE (the teams' rates, ``family-v1``), MODEL_MARKET_GAP
    cards             RATE, REFEREE (the referee's multiplier, ``fbi.families.referee``), MODEL_MARKET_GAP

Not here, by construction of the features: ABSENCES, LINEUP, STAKES, H2H, TACTICS, NEWS, MARKET_MOVE, DATA_QUALITY. A new feature set is
a new version of this table (a test holds its keys to the families of the contracts)."""

NOVELTY_Q: Final = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Position:
    """One specialist's stance on one selection, as its stored ``aa-v1`` evaluation says it, with the weight the book gives it."""

    agent: str
    version: str
    label: str
    """The label the Council cites it by (``match_evaluation``)."""
    candidate: str
    stance: str
    drivers: tuple[str, ...]
    risks: tuple[str, ...]
    refs: tuple[str, ...]
    run_id: int
    weight: Decimal

    @property
    def polarity(self) -> str:
        return polarity_of(self.stance)

    @property
    def who(self) -> str:
        return f"{self.agent}@{self.version}"


@dataclass(frozen=True, slots=True)
class Selection:
    """A candidate of the pass with the model's numbers the shadow stored for it (``ai.match_runs.candidates``): read, never changed."""

    key: str
    family: str
    market_key: str
    selection: str
    line: Decimal
    p_model: Decimal | None = None
    p_market: Decimal | None = None
    edge: Decimal | None = None
    ev: Decimal | None = None
    contra: tuple[str, ...] = ()
    """The ``contra-v1`` codes (C01..C08) the pass recorded touching this candidate."""

    @property
    def value_edge(self) -> Decimal | None:
        """The model's edge: the stored one, or the model's probability less the market's when only those are stored."""
        if self.edge is not None:
            return self.edge
        if self.p_model is not None and self.p_market is not None:
            return self.p_model - self.p_market
        return None


@dataclass(frozen=True, slots=True)
class Market:
    """What the market did with the selection as of the moment (``market-signals-v1``): only what the rules below read."""

    status: str
    movement_points: float | None = None
    steam_up: bool = False
    steam_down: bool = False
    stale: bool | None = None

    @classmethod
    def unknown(cls) -> Market:
        return cls(market_signals.NO_PRICES)

    @classmethod
    def of(cls, s: market_signals.MarketSignals) -> Market:
        directions = {e.direction for e in s.steam_events}
        return cls(s.status, s.movement_points, market_signals.UP in directions, market_signals.DOWN in directions, s.stale)

    @property
    def readable(self) -> bool:
        return self.status == market_signals.OK and self.movement_points is not None

    @property
    def fell(self) -> bool:
        return self.readable and (self.steam_down or (self.movement_points or 0.0) <= -MARKET_MOVE_POINTS)

    @property
    def rose(self) -> bool:
        return self.readable and (self.steam_up or (self.movement_points or 0.0) >= MARKET_MOVE_POINTS)


@dataclass(frozen=True, slots=True)
class Finding:
    kind: Kind
    code: Code
    candidate: str
    agents: tuple[str, ...]
    run_ids: tuple[int, ...]
    refs: tuple[str, ...]
    material: bool
    detail: tuple[tuple[str, str], ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "code": self.code, "candidate": self.candidate, "agents": list(self.agents), "run_ids": list(self.run_ids),
                "refs": list(self.refs), "material": self.material, "detail": dict(self.detail)}


def novelty(p: Position, family: str) -> Decimal:
    """The share of the stance's drivers the family's model does not already read (1 for a stance with no driver)."""
    if not p.drivers:
        return Decimal(1)
    known = MODEL_KNOWS.get(family, frozenset())
    fresh = sum(1 for d in p.drivers if d not in known)
    return (Decimal(fresh) / Decimal(len(p.drivers))).quantize(NOVELTY_Q)


def _finding(code: Code, candidate: str, positions: Iterable[Position], *, material: bool, **detail: str) -> Finding:
    ps = sorted(positions, key=lambda p: (p.agent, p.version, p.run_id))
    return Finding(KIND_OF[code], code, candidate, tuple(dict.fromkeys(p.who for p in ps)), tuple(sorted({p.run_id for p in ps})),
                   tuple(sorted({r for p in ps for r in p.refs})), material, tuple(sorted(detail.items())))


def agent_vs_agent(candidate: str, positions: Sequence[Position]) -> list[Finding]:
    """AA1: a supporter and an objector among DIFFERENT agents on the same selection."""
    supporters = [p for p in positions if p.polarity == "FOR"]
    objectors = [p for p in positions if p.polarity == "AGAINST"]
    if not any(s.agent != o.agent for s in supporters for o in objectors):
        return []
    w_for, w_against = sum((p.weight for p in supporters), Decimal(0)), sum((p.weight for p in objectors), Decimal(0))
    strongest = "REJECT_SIGNAL" if any(p.stance == "REJECT_SIGNAL" for p in objectors) else "CONCERN"
    return [_finding("AA1", candidate, [*supporters, *objectors], material=w_for > 0 and w_against > 0,
                     support_by="+".join(sorted({p.who for p in supporters})), against_by="+".join(sorted({p.who for p in objectors})),
                     against_stance=strongest, weight_for=str(w_for), weight_against=str(w_against))]


def agent_vs_model(sel: Selection, p: Position) -> list[Finding]:
    """AM1 / AM2: the stance against the model's own reading of value. Not evaluated without an edge."""
    edge = sel.value_edge
    if edge is None or p.polarity == "NONE":
        return []
    fresh = novelty(p, sel.family)
    if p.polarity == "AGAINST" and edge > 0:
        code: Code = "AM1"
    elif p.polarity == "FOR" and edge <= 0:
        code = "AM2"
    else:
        return []
    return [_finding(code, sel.key, [p], material=p.weight > 0 and fresh > 0, edge=str(edge), novelty=str(fresh), stance=p.stance)]


def agent_vs_market(sel: Selection, p: Position, market: Market) -> list[Finding]:
    """AK1 / AK2: the stance against the way the market moved."""
    if p.polarity == "FOR" and market.fell:
        code: Code = "AK1"
    elif p.polarity == "AGAINST" and market.rose:
        code = "AK2"
    else:
        return []
    return [_finding(code, sel.key, [p], material=p.weight > 0 and market.stale is False, stance=p.stance,
                     movement_points=f"{market.movement_points:.3f}", steam="down" if market.steam_down else "up" if market.steam_up else "none",
                     stale=str(market.stale).lower())]


def already_known(sel: Selection, p: Position, market: Market) -> list[Finding]:
    """KN1: the model already reads every driver of the stance. KN2: the market already moved the way the stance points."""
    out: list[Finding] = []
    if p.polarity == "NONE":
        return out
    if p.drivers and novelty(p, sel.family) == 0:
        out.append(_finding("KN1", sel.key, [p], material=False, drivers="+".join(p.drivers), family=sel.family))
    if (p.polarity == "FOR" and market.rose) or (p.polarity == "AGAINST" and market.fell):
        out.append(_finding("KN2", sel.key, [p], material=False, movement_points=f"{market.movement_points:.3f}", stance=p.stance))
    return out


def detect(sel: Selection, positions: Sequence[Position], market: Market) -> tuple[Finding, ...]:
    """Every finding of one selection, sorted by (code, agents, runs). Pure: the same inputs give the same tuple whatever their order."""
    mine = sorted((p for p in positions if p.candidate == sel.key), key=lambda p: (p.agent, p.version, p.run_id))
    found = [*agent_vs_agent(sel.key, mine)]
    for p in mine:
        found += [*agent_vs_model(sel, p), *agent_vs_market(sel, p, market), *already_known(sel, p, market)]
    return tuple(sorted(found, key=lambda f: (f.code, f.agents, f.run_ids)))


__all__ = ["CODES", "KINDS", "MARKET_MOVE_POINTS", "MODEL_KNOWS", "VERSION", "Finding", "Market", "Position", "Selection", "agent_vs_agent",
           "agent_vs_market", "agent_vs_model", "already_known", "detect", "novelty"]
