"""The interface of a market family as a plug-in (``family-plugin-v1``): ONE entry every layer reads, made of the protocols the layers
already have.

WHAT IS REUSED, NOT REINVENTED.

    decision-v2     ``MarketFamily``, ``FamilyParams``, ``SettlementRule``, ``GateStatus``, ``Candidate`` and ``gate_of`` of
                    ``fbi.decision.families``: the author writes an ordinary decision-v2 adapter
    calibration     the (market, model) slots and the CHAMPION role of ``fbi.intel.calibration``, read through ``gate_of``
    edge gate       ``edge-gate-v1`` (``fbi.intel.calibration.EDGE_GATE_VERSION``), read as ``GateStatus.edge_validated``
    portfolio       the ``JointProvider`` shape of ``fbi.portfolio.correlation`` (``correlation(a, b) -> float | None``), satisfied
                    structurally: this package does not import the portfolio
    taxonomy        the bet ids and statuses of ``fbi.odds.quote_taxonomy`` (checked by ``registry``)

WHAT THE PLUG-IN ADDS: the status of the FAMILY and the rule that moves it. A family is NOT_MODELABLE, CANDIDATE or RESEARCH (the
taxonomy's words), SHADOW (its model computes and decision-v2 judges it, held at ABSTAIN) or ACTIVE. ACTIVE exists only through
``promote``: for EVERY market of the family a CHAMPION calibrator in its (market, model) slot and the edge validated by the family's
gate, on a family whose author allowed promotion (``activatable``). An entry that says ACTIVE without that record cannot be built.

THE GOVERNED VIEW. decision-v2 does not see the author's adapter: it sees ``PluginFamily``, which takes the adapter's candidates and
gives them the plug-in's params - its own decision version, and ``promoted`` true only when ACTIVE - and the gate of the plug-in's own
calibrator slots. However the adapter was written, a family in SHADOW is never more than ABSTAIN.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

import psycopg

from fbi.decision.families import (
    Candidate,
    FamilyParams,
    GateStatus,
    MarketFamily,
    SettlementRule,
    gate_of,
)
from fbi.intel import decision
from fbi.intel.calibration import EDGE_GATE_VERSION

NOT_MODELABLE: Final = "NOT_MODELABLE"
CANDIDATE: Final = "CANDIDATE"
RESEARCH: Final = "RESEARCH"
SHADOW: Final = "SHADOW"
ACTIVE: Final = "ACTIVE"
STATUSES: Final = (NOT_MODELABLE, CANDIDATE, RESEARCH, SHADOW, ACTIVE)
"""In order. The first three are the taxonomy's (``fbi.odds.quote_taxonomy.STATUSES``); SHADOW and ACTIVE are a family's only."""
DECIDED: Final = frozenset({SHADOW, ACTIVE})
"""The statuses decision-v2 judges a family in (a family below SHADOW has no model to judge)."""


class SelectionLike(Protocol):
    """What a correlation provider reads of a selection: the fields ``fbi.portfolio.selection.Selection`` has."""

    @property
    def fixture_id(self) -> int: ...

    @property
    def market_key(self) -> str: ...

    @property
    def selection(self) -> str: ...

    @property
    def line(self) -> Decimal: ...


@runtime_checkable
class DistributionProvider(Protocol):
    """A family's model as of one moment: the probability of one of its selections and the dependence of two selections of one match.
    ``correlation`` has the shape of the portfolio's ``JointProvider``, so a provider is one: None when it cannot say."""

    def price(self, fixture_id: int, market_key: str, selection: str, line: Decimal) -> tuple[float, float] | None:
        """(P(win), P(push)) of the selection, or None when the model has nothing for it."""
        ...

    def correlation(self, a: SelectionLike, b: SelectionLike) -> float | None: ...


class DistributionSource(Protocol):
    """How a family's model is read as of ``at`` (nothing known after it), for some matches."""

    def __call__(self, conn: psycopg.Connection[Any] | None, *, at: datetime, fixtures: Sequence[int]) -> DistributionProvider: ...


class PromotionRefused(ValueError):  # noqa: N818 - a refusal, the name the owner reads
    """``promote`` refused: the reasons, every one."""

    def __init__(self, family: str, reasons: Sequence[str]) -> None:
        self.family = family
        self.reasons = tuple(reasons)
        super().__init__(f"{family} cannot be ACTIVE: " + "; ".join(self.reasons))


@dataclass(frozen=True, slots=True)
class Promotion:
    """The record that makes a family ACTIVE: per market, the CHAMPION calibrator of its slot and the edge validated by ``edge_gate``."""

    calibrators: tuple[tuple[str, int], ...]
    """(market key, calibrator id) of the champion of each market's (market, model) slot."""
    edge_validated: frozenset[str]
    edge_gate: str
    by: str
    at: datetime

    @property
    def markets(self) -> frozenset[str]:
        return frozenset(m for m, _ in self.calibrators)


@dataclass(frozen=True)
class FamilyPlugin:
    """A market family as a plug-in: what each layer reads of it (see the package docstring). ``registry.check`` holds every reference
    against its layer; the dataclass itself holds only what needs no other layer."""

    name: str
    """Upper case, unique: how decision-v2's replay reports it (``MarketFamily.name``)."""
    label: str
    status: str
    bets: tuple[int, ...]
    """The provider's bet ids (``fbi.odds.quote_taxonomy``) the family is priced on."""
    market_keys: tuple[str, ...]
    """The catalogue keys of those bets (``fbi.market.catalogue.market_key_for``): the markets it owns."""
    rule: str
    """The settlement rule of ``fbi.market.rules`` its markets are graded on (``measure@vN``)."""
    model: str
    """The model name of its probabilities: the calibrator slots are (market key, model)."""
    model_version: str
    decision_version: str
    """The version its decision-v2 rows would be written under. Never a decision-v1-era version."""
    settlement: SettlementRule
    adapter: MarketFamily = field(compare=False)
    """The decision-v2 adapter the author wrote: its candidates, as of a moment."""
    distribution: DistributionSource | None = field(default=None, compare=False)
    """The model as a distribution provider (and the portfolio's correlation provider), when it has one."""
    edge_gate: str = EDGE_GATE_VERSION
    activatable: bool = True
    """False: the author forbids promotion (an example, a family kept for research). ``promote`` refuses it whatever the evidence."""
    promotion: Promotion | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"{self.name}: status {self.status!r} is not one of {STATUSES}")
        if self.status == ACTIVE:
            problems = activation_problems(self)
            if problems:
                raise PromotionRefused(self.name, problems)
        elif self.promotion is not None:
            raise ValueError(f"{self.name}: a promotion record belongs to an ACTIVE family only")

    @property
    def calibrators(self) -> tuple[tuple[str, str], ...]:
        """The (market, model) slots of ``intel.calibrators`` / ``intel.promotions`` this family's probabilities are calibrated in."""
        return tuple((m, self.model) for m in self.market_keys)

    def decision_family(self) -> PluginFamily:
        """The family as decision-v2 sees it (governed by this entry)."""
        if self.status not in DECIDED:
            raise ValueError(f"{self.name} is {self.status}: decision-v2 judges SHADOW and ACTIVE families only")
        return PluginFamily(self)


def activation_problems(plugin: FamilyPlugin) -> list[str]:
    """Why an ACTIVE entry is not backed by its promotion record (empty: it is)."""
    out: list[str] = []
    if not plugin.activatable:
        out.append("the family's author forbids promotion (activatable=False)")
    p = plugin.promotion
    if p is None:
        return [*out, "no promotion record: a CHAMPION calibrator and a validated edge for every market"]
    missing_cal = sorted(set(plugin.market_keys) - p.markets)
    if missing_cal:
        out.append(f"no champion calibrator for {missing_cal}")
    missing_edge = sorted(set(plugin.market_keys) - p.edge_validated)
    if missing_edge:
        out.append(f"edge not validated for {missing_edge}")
    if p.edge_gate != plugin.edge_gate:
        out.append(f"promoted by {p.edge_gate}, the family's gate is {plugin.edge_gate}")
    return out


def promote(plugin: FamilyPlugin, gates: Mapping[str, GateStatus], *, by: str, at: datetime) -> FamilyPlugin:
    """The family ACTIVE, from the gate of each of its markets as decision-v2 reads it (``gate_of`` of its (market, model) slot):
    every market needs a CHAMPION calibrator (the best fit is shown, never promotes) and its edge validated. Only a family in SHADOW is
    promoted: it must have been judged before it decides. Refused with every reason otherwise. A promotion is the owner's act; this is
    the check, not the policy that decides when to ask for it."""
    reasons: list[str] = []
    if plugin.status != SHADOW:
        reasons.append(f"it is {plugin.status}: only a family in SHADOW is promoted")
    if not plugin.activatable:
        reasons.append("the family's author forbids promotion (activatable=False)")
    calibrators: list[tuple[str, int]] = []
    validated: set[str] = set()
    for market in plugin.market_keys:
        g = gates.get(market)
        champ = None if g is None else g.champion
        if champ is None or champ.id is None or champ.role != "CHAMPION":
            reasons.append(f"{market}: no CHAMPION calibrator in ({market}, {plugin.model})")
        elif (champ.market_key, champ.model_name) != (market, plugin.model):
            reasons.append(f"{market}: the champion is of ({champ.market_key}, {champ.model_name}), not of the family's slot")
        else:
            calibrators.append((market, champ.id))
        if g is None or not g.edge_validated:
            reasons.append(f"{market}: edge not validated ({plugin.edge_gate})")
        else:
            validated.add(market)
    if reasons:
        raise PromotionRefused(plugin.name, reasons)
    record = Promotion(tuple(calibrators), frozenset(validated), plugin.edge_gate, by, at)
    return dataclasses.replace(plugin, status=ACTIVE, promotion=record)


# -- the governed view decision-v2 reads ---------------------------------------------------------------------------------------------

NO_GATE: Final = GateStatus(None, None, {}, False)


@dataclass(frozen=True)
class PluginFamily:
    """A plug-in as a ``MarketFamily``: the adapter's candidates under the entry's params, settlement and calibrator slots."""

    plugin: FamilyPlugin

    @property
    def name(self) -> str:
        return self.plugin.name

    @property
    def params(self) -> FamilyParams:
        own = self.plugin.adapter.params
        return dataclasses.replace(own, decision_version=self.plugin.decision_version, promoted=self.plugin.status == ACTIVE)

    @property
    def settlement(self) -> SettlementRule:
        return self.plugin.settlement

    def markets(self) -> tuple[str, ...]:
        return tuple(sorted(self.plugin.market_keys))

    def owns(self, market_key: str) -> bool:
        return market_key in self.plugin.market_keys

    def candidates(self, conn: psycopg.Connection[Any], *, at: datetime, fixtures: Sequence[int] | None = None,
                   horizon: timedelta = decision.HORIZON) -> list[Candidate]:
        """The adapter's candidates of the family's own markets, handed to the engine as this family's."""
        if self.plugin.status not in DECIDED:
            return []
        found = self.plugin.adapter.candidates(conn, at=at, fixtures=fixtures, horizon=horizon)
        return [dataclasses.replace(c, family=self) for c in found if self.owns(c.key[1])]

    def gate(self, world: decision.World, market: str, model: str) -> GateStatus:
        """The calibrator and edge gate of the family's own slot; any other (market, model) has none."""
        if model != self.plugin.model or not self.owns(market):
            return NO_GATE
        return gate_of(world, market, model)

    def claims(self, row: Mapping[str, Any]) -> bool:
        return row.get("decision_version") == self.plugin.decision_version and self.owns(str(row.get("market_key")))
