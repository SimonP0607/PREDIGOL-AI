"""The registry of plug-in families (``family-plugin-v1``): an entry is checked against EVERY layer before it is accepted, and each
consumer is handed its view of the registered families - nothing in the core is edited to add one.

THE CHECKS (``check``; every problem is reported, none is fixed):

    identity      an upper-case name no other family (the families of today, ``fbi.decision.families.FAMILIES``, or a registered
                  plug-in) has; a decision version of its own (never decision-v1's or decision-fam-v1's)
    taxonomy      every bet is known to ``fbi.odds.quote_taxonomy``; above NOT_MODELABLE, none is NOT_MODELABLE there and every one is
                  EXTRACTED (its prices are structured - a family cannot be judged against prices that are only in RAW)
    catalogue     the keys the catalogue derives from the bets (``market_key_for``) are exactly the family's ``market_keys``
    ownership     no market belongs to two families (``MarketFamily.owns`` of the others)
    settlement    every bet is graded by the family's rule (``fbi.market.rules.rule_for``), which can grade (liquidable); the
                  settlement function exists
    model         from SHADOW up, a model name and version; the adapter is a ``MarketFamily`` that owns the family's markets
    edge gate     the gate is one the calibration knows (``edge-gate-v1``)
    status        an ACTIVE entry carries its promotion (``family.activation_problems``; the dataclass already refuses one without)

THE VIEWS.

    ``decision_families()``  the families of today followed by the SHADOW and ACTIVE plug-ins, governed (``family.PluginFamily``):
                             what ``fbi.decision.engine.decide_all`` and ``fbi.decision.replay.replay_day(families=...)`` take
    ``joint_provider(...)``  one correlation provider over the plug-ins' distribution providers (the first that can say): what
                             ``fbi.portfolio.correlation.estimate(joint=...)`` and ``pairs`` take
    ``describe()``           every layer's view of every entry, in words and references (the command and the owner's review)

``INSTALLED`` is the tuple of plug-ins the platform would register: EMPTY. The example (``fbi.plugins._template``) is registered only
by a test, at run time.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg

from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.decision.families import FAMILIES, MarketFamily
from fbi.intel.calibration import EDGE_GATE_VERSION
from fbi.market.catalogue import market_key_for
from fbi.market.rules import RULES_BY_KEY, rule_for
from fbi.odds.quote_taxonomy import known_bet_ids, spec_for
from fbi.plugins.family import (
    DECIDED,
    NOT_MODELABLE,
    STATUSES,
    DistributionProvider,
    FamilyPlugin,
    SelectionLike,
    activation_problems,
)

GATES: Final = frozenset({EDGE_GATE_VERSION})
"""The edge gates the calibration knows."""
RESERVED_VERSIONS: Final = frozenset({DECISION_CORE, DECISION_FAMILIES})


class RegistryError(ValueError):
    def __init__(self, family: str, problems: Sequence[str]) -> None:
        self.family = family
        self.problems = tuple(problems)
        super().__init__(f"{family} is not registered: " + "; ".join(self.problems))


def _settlement_exists(module: str, function: str) -> bool:
    try:
        return callable(getattr(importlib.import_module(module), function, None))
    except ImportError:
        return False


def check(plugin: FamilyPlugin, *, others: Sequence[MarketFamily | FamilyPlugin] = FAMILIES) -> list[str]:
    """Every problem of the entry against every layer (see the module's docstring). Empty: it can be registered."""
    out: list[str] = []
    names = {o.name for o in others}
    if not plugin.name or plugin.name != plugin.name.upper():
        out.append(f"name {plugin.name!r} must be upper case")
    if plugin.name in names:
        out.append(f"another family is called {plugin.name}")
    if plugin.decision_version in RESERVED_VERSIONS:
        out.append(f"decision version {plugin.decision_version} belongs to a layer being replaced; a plug-in has its own")
    if any(isinstance(o, FamilyPlugin) and o.decision_version == plugin.decision_version for o in others):
        out.append(f"decision version {plugin.decision_version} is another plug-in's")

    # taxonomy and catalogue
    if not plugin.bets:
        out.append("no bet of the taxonomy")
    known = known_bet_ids()
    derived: set[str] = set()
    for bet in plugin.bets:
        if bet not in known:
            out.append(f"bet {bet} is not in the taxonomy")
            continue
        spec = spec_for(bet)
        if plugin.status != NOT_MODELABLE:
            if spec.status == NOT_MODELABLE:
                out.append(f"bet {bet} ({spec.name}) is NOT_MODELABLE in the taxonomy")
            if not spec.extract:
                out.append(f"bet {bet} ({spec.name}) is not extracted: its prices are only in RAW")
        key = market_key_for(spec)
        if key is None:
            out.append(f"bet {bet} ({spec.name}) has no catalogue key (it cannot be graded)")
        else:
            derived.add(key)
        rule = rule_for(spec)
        if rule is None or rule.key != plugin.rule:
            out.append(f"bet {bet} ({spec.name}) is graded by {None if rule is None else rule.key}, not by {plugin.rule}")
    if derived and derived != set(plugin.market_keys):
        out.append(f"the catalogue derives {sorted(derived)} from the bets, the family says {sorted(plugin.market_keys)}")
    if len(set(plugin.market_keys)) != len(plugin.market_keys):
        out.append("a market key is listed twice")

    # ownership
    for key in plugin.market_keys:
        for o in others:
            owned = key in o.market_keys if isinstance(o, FamilyPlugin) else o.owns(key)
            if owned:
                out.append(f"{key} already belongs to {o.name}")

    # settlement
    rule_ = RULES_BY_KEY.get(plugin.rule)
    if rule_ is None:
        out.append(f"no settlement rule {plugin.rule}")
    elif not rule_.liquidable:
        out.append(f"the rule {plugin.rule} cannot grade ({rule_.reason})")
    s = plugin.settlement
    if not _settlement_exists(s.module, s.function):
        out.append(f"the settlement function {s.ref} does not exist")

    # model, adapter, gate, status
    if plugin.status in DECIDED and not (plugin.model and plugin.model_version):
        out.append("a family in SHADOW or ACTIVE needs a model name and version (its calibrator slots)")
    if not isinstance(plugin.adapter, MarketFamily):
        out.append("the adapter is not a decision-v2 MarketFamily")
    else:
        stray = [k for k in plugin.market_keys if not plugin.adapter.owns(k)]
        if stray:
            out.append(f"the adapter does not own {stray}")
    if plugin.edge_gate not in GATES:
        out.append(f"edge gate {plugin.edge_gate} is not one the calibration knows ({sorted(GATES)})")
    if plugin.status not in STATUSES:
        out.append(f"status {plugin.status} is not one of {STATUSES}")
    elif plugin.status == "ACTIVE":
        out += activation_problems(plugin)
    return out


@dataclass(frozen=True)
class JointChain:
    """The plug-ins' distribution providers as ONE correlation provider: the first that can say, else None (the portfolio then falls
    back to its own sources). The shape of ``fbi.portfolio.correlation.JointProvider``."""

    providers: tuple[DistributionProvider, ...]

    def correlation(self, a: SelectionLike, b: SelectionLike) -> float | None:
        for p in self.providers:
            rho = p.correlation(a, b)
            if rho is not None:
                return rho
        return None


class Registry:
    """The plug-in families accepted, on top of the families of today (``base``)."""

    def __init__(self, base: Sequence[MarketFamily] = FAMILIES) -> None:
        self._base = tuple(base)
        self._plugins: dict[str, FamilyPlugin] = {}

    def register(self, plugin: FamilyPlugin) -> FamilyPlugin:
        problems = check(plugin, others=(*self._base, *self._plugins.values()))
        if problems:
            raise RegistryError(plugin.name, problems)
        self._plugins[plugin.name] = plugin
        return plugin

    def plugins(self) -> tuple[FamilyPlugin, ...]:
        return tuple(self._plugins[n] for n in sorted(self._plugins))

    def get(self, name: str) -> FamilyPlugin:
        return self._plugins[name]

    def decision_families(self) -> tuple[MarketFamily, ...]:
        """The families decision-v2 and its replay take: today's, then the plug-ins it judges (SHADOW and ACTIVE), governed."""
        return (*self._base, *(p.decision_family() for p in self.plugins() if p.status in DECIDED))

    def joint_provider(self, conn: psycopg.Connection[Any] | None, *, at: datetime, fixtures: Sequence[int]) -> JointChain:
        """The portfolio's correlation provider over the plug-ins in SHADOW or ACTIVE that have a distribution, as of ``at``."""
        return JointChain(tuple(p.distribution(conn, at=at, fixtures=fixtures) for p in self.plugins()
                                if p.status in DECIDED and p.distribution is not None))

    def describe(self) -> list[dict[str, Any]]:
        """Every layer's view of every entry."""
        out: list[dict[str, Any]] = []
        for p in self.plugins():
            out.append({
                "name": p.name, "label": p.label, "status": p.status, "activatable": p.activatable,
                "taxonomy": [{"bet_id": b, "name": spec_for(b).name, "status": spec_for(b).status, "extract": spec_for(b).extract}
                             for b in p.bets],
                "markets": list(p.market_keys),
                "model": {"name": p.model, "version": p.model_version, "distribution": p.distribution is not None},
                "calibrators": [list(slot) for slot in p.calibrators],
                "settlement": {"rule": p.rule, "function": p.settlement.ref, "outcome_version": p.settlement.outcome_version},
                "edge_gate": p.edge_gate,
                "decision": {"version": p.decision_version, "judged": p.status in DECIDED, "promoted": p.status == "ACTIVE"},
                "promotion": None if p.promotion is None else {"by": p.promotion.by, "at": p.promotion.at.isoformat(),
                                                               "calibrators": dict(p.promotion.calibrators)},
            })
        return out


INSTALLED: Final[tuple[FamilyPlugin, ...]] = ()
"""The plug-ins the platform registers. None: a family enters here only after its checklist (``docs/owner/IA_018_FAMILIA_PLUGIN.md``),
and nothing that decides reads the registry yet."""


def installed() -> Registry:
    reg = Registry()
    for p in INSTALLED:
        reg.register(p)
    return reg

