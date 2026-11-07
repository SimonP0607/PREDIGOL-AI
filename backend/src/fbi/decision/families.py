"""The market families of ``decision-v2`` as plug-ins: what each one brings to the one engine (``fbi.decision.engine``).

A family is the part of a decision that differs by market: WHICH selections are candidates and how its predictions are read
as of a moment, the calibrator and edge gate that say whether its probability can be believed, and the rule that settles it.
Everything else - the stages, the thresholds, the states - is shared. A family is a ``MarketFamily``; adding one is adding
an adapter that satisfies the protocol, with no change to the engine (``tests/unit/test_decision_v2_families.py`` plugs in a
toy one).

THE FAMILIES OF TODAY, read exactly as the layers they will replace read them:

    core         the selections a shadow rule flagged in ``picks.picks`` (1X2, OU, BTTS, AH, DC: ``fbi.picks.rules``), the
                 newest pick of each model and the newest Shin consensus - ``decision.load_candidates`` (decision-v1)
    GOALS_HALF   the forecasts of F10 in the forecast table of F5 (``family-v1``) that see value at the books' price -
    CORNERS      ``fbi.familydecisions.decide.load_forecasts`` / ``read_prices`` / ``candidates`` (decision-fam-v1)
    CARDS
    YELLOW

WHERE THEY DIFFER (``FamilyParams``, each field documented): the core layer judges the age of the forecast, asks for an
interval, keeps one selection per match and may recommend; a family of F10 states no interval and no fresh age, is not
correlated and, in shadow, is never more than ABSTAIN. These are the differences decision-fam-v1 carries today, written
down as parameters of one engine instead of a second layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Protocol, runtime_checkable

import psycopg

from fbi.core.decision_versions import (
    DECISION_CORE,
    DECISION_FAMILIES,
    OUTCOME_CORE,
    OUTCOME_FAMILIES,
)
from fbi.families.score import measure_of
from fbi.familydecisions import decide as fd
from fbi.intel import decision
from fbi.intel.calibration import Calibrator
from fbi.intel.decision import Key
from fbi.picks.rules import CURRENT_RULE

CAP_CODE: Final = fd.REASON_CAPPED
"""The reason a family that is not promoted is held below what its stages said (decision-fam-v1's own code)."""
INFO_CODES: Final = frozenset({fd.REASON_RESEARCH})
"""Reasons decision-fam-v1 writes that move no state (the family's request for research): never compared."""


@dataclass(frozen=True, slots=True)
class FamilyParams:
    """What a family changes in the shared stages. Every difference between decision-v1 and decision-fam-v1 is one field here."""

    decision_version: str
    """The decision-v1-era version this family's rows are written under, and whose previous rows say whether a selection was approved
    before (its checkpoint) - ``decision.read_world(version=...)``."""
    forecast_max_age: timedelta | None
    """The oldest forecast that is still a basis (stage data). decision-v1: ``decision.FORECAST_MAX_AGE`` (72 h: the pipeline writes a pick
    at every run). decision-fam-v1: None - the forecast table stores a forecast again only when it moves by half a point, so the age of the
    row is the time since the last MOVE, not since the model last looked (``fd.Candidate.row``)."""
    interval_required: bool
    """Whether a probability without an interval is refused (stage model). decision-v1: True. decision-fam-v1: False - no family stores an
    interval yet; the width is judged only where there is one (``interval_optional``)."""
    correlate: bool
    """Whether the family's RECOMMENDED compete for one selection per match (stage correlation). decision-v1: True. decision-fam-v1: False -
    a family never passes INVESTIGACION, so it never competes for the match."""
    promoted: bool
    """Whether the family may be more than ABSTAIN. decision-v1: True. decision-fam-v1: False - capped at INVESTIGACION (``fd.finalise``),
    which in state-v2 is ABSTAIN (``CAP_CODE``): a family in shadow is a structural lack, not a wait. A promotion is the owner's."""
    candidate_rule: str
    """What makes a selection a candidate, in words (the adapter applies it)."""
    price_source: str
    """Where the price comes from, in words (the adapter reads it)."""


@dataclass(frozen=True, slots=True)
class SettlementRule:
    """The rule that settles a family's decisions: ``module:function`` and the version of the outcomes it writes."""

    module: str
    function: str
    outcome_version: str

    @property
    def ref(self) -> str:
        return f"{self.module}:{self.function}"


@dataclass(frozen=True, slots=True)
class GateStatus:
    """What the calibration says of (market, model) at the moment: the champion (believed), the best fit (shown, never approving), its
    walk-forward record, and whether the market's edge is validated out of sample (edge-gate-v1)."""

    champion: Calibrator | None
    best: Calibrator | None
    wf: Mapping[str, Any]
    edge_validated: bool

    @property
    def calibrator(self) -> Calibrator | None:
        return self.champion or self.best


@runtime_checkable
class MarketFamily(Protocol):
    """A market family: the one thing the engine asks of a market."""

    @property
    def name(self) -> str:
        """The family's name (``core``, ``CORNERS``...): how the replay reports it."""
        ...

    @property
    def params(self) -> FamilyParams: ...

    @property
    def settlement(self) -> SettlementRule: ...

    def markets(self) -> tuple[str, ...]:
        """The market keys (or key families) it owns, in words a reader can check."""
        ...

    def owns(self, market_key: str) -> bool: ...

    def candidates(self, conn: psycopg.Connection[Any], *, at: datetime, fixtures: Sequence[int] | None = None,
                   horizon: timedelta = decision.HORIZON) -> list[Candidate]:
        """Its candidate predictions as known at ``at`` (nothing created, priced or captured after it is read)."""
        ...

    def gate(self, world: decision.World, market: str, model: str) -> GateStatus:
        """Its calibrator and edge-gate status for (market, model) in the world read at the moment."""
        ...

    def claims(self, row: Mapping[str, Any]) -> bool:
        """Whether a row of ``intel.decisions`` was decided as this family (the replay sorts the day's rows with it)."""
        ...


@dataclass(frozen=True, slots=True)
class Candidate:
    """One selection a family puts before the engine: its key, the rows of its models as decision-v1 reads a pick (model name -> row),
    and - for a family that judges each model on its own - the model it is about."""

    family: MarketFamily = field(compare=False, hash=False)
    key: Key
    models: Mapping[str, Mapping[str, Any]] = field(compare=False, hash=False)
    model_hint: str | None = None

    @property
    def ident(self) -> tuple[str, Key, str | None]:
        """How the replay matches a decision with the row decision-v1 or decision-fam-v1 wrote of it."""
        return self.family.name, self.key, self.model_hint


def gate_of(world: decision.World, market: str, model: str) -> GateStatus:
    """The calibration as decision-v1 reads it (``world.cal``), for any family: the slots are (market, model)."""
    cal = world.cal
    return GateStatus(cal.champions.get((market, model)), cal.best.get((market, model)), cal.wf.get((market, model)) or {},
                      bool(cal.edge.get((market, model))))


# -- core: the pipeline's picks ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CoreFamily:
    """The pipeline's markets, read as decision-v1 reads them: every selection a shadow rule flagged (``picks.picks``)."""

    name: str = "core"
    params: FamilyParams = FamilyParams(
        decision_version=DECISION_CORE, forecast_max_age=decision.FORECAST_MAX_AGE, interval_required=True, correlate=True, promoted=True,
        candidate_rule="the newest pick of each model a shadow rule flagged (picks.picks), kick-off within the horizon",
        price_source="the newest Shin consensus of market.market_consensus within decision.CONSENSUS_LOOKBACK")
    settlement: SettlementRule = SettlementRule("fbi.intel.outcomes", "settle_decisions", OUTCOME_CORE)
    """Settled through its pick (``picks.pick_results``, ``fbi.picks.settlement.market_outcome``)."""

    def markets(self) -> tuple[str, ...]:
        return tuple(sorted(CURRENT_RULE.markets))

    def owns(self, market_key: str) -> bool:
        return market_key in CURRENT_RULE.markets

    def candidates(self, conn: psycopg.Connection[Any], *, at: datetime, fixtures: Sequence[int] | None = None,
                   horizon: timedelta = decision.HORIZON) -> list[Candidate]:
        found = decision.load_candidates(conn, at=at, horizon=horizon, only=None if fixtures is None else list(fixtures))
        return self.from_picks(found)

    def from_picks(self, found: Mapping[Key, Mapping[str, Mapping[str, Any]]]) -> list[Candidate]:
        """The candidates of ``decision.load_candidates``'s answer, in key order."""
        return [Candidate(self, key, dict(models)) for key, models in sorted(found.items())]

    def gate(self, world: decision.World, market: str, model: str) -> GateStatus:
        return gate_of(world, market, model)

    def claims(self, row: Mapping[str, Any]) -> bool:
        return row.get("decision_version") == self.params.decision_version


# -- the families of F10: the forecasts of the counts and the halves -------------------------------------------------------------------

FAMILY_MEASURES: Final[Mapping[str, frozenset[str]]] = {
    "GOALS_HALF": frozenset({"goals_halves", "goals_1h", "goals_2h"}), "CORNERS": frozenset({"corners_ft"}),
    "CARDS": frozenset({"cards_lines_ft"}), "YELLOW": frozenset({"yellow_ft"})}
"""The settlement measures (``fbi.families.score.measure_of``) of the market keys of each family."""


@dataclass(frozen=True, slots=True)
class ForecastFamily:
    """A family of F10 read as decision-fam-v1 reads it: the last forecast of each selection, priced by the books that quoted it by then,
    a candidate when it sees value (``fd.candidates`` with this family's ``fd.FamilySpec``)."""

    spec: fd.FamilySpec
    params: FamilyParams = FamilyParams(
        decision_version=DECISION_FAMILIES, forecast_max_age=None, interval_required=False, correlate=False, promoted=False,
        candidate_rule="the last forecast of F10 seeing at least fd.MIN_EV at the best price, a line that cannot push, "
                       "at least spec.min_books complete books, the best line of each market of each match and model",
        price_source="the quotes in force (market.odds_quotes) of the complete books, de-vigged by their own margin; the age is when the "
                     "match's odds were last read")
    settlement: SettlementRule = SettlementRule("fbi.familydecisions.outcomes", "grade", OUTCOME_FAMILIES)
    """Graded on the counts of the match by the settlement rules (``fbi.market.rules``)."""

    @property
    def name(self) -> str:
        return self.spec.family

    def markets(self) -> tuple[str, ...]:
        return tuple(sorted(FAMILY_MEASURES[self.spec.family]))

    def owns(self, market_key: str) -> bool:
        try:
            return measure_of(market_key) in FAMILY_MEASURES[self.spec.family]
        except ValueError:
            return False

    def candidates(self, conn: psycopg.Connection[Any], *, at: datetime, fixtures: Sequence[int] | None = None,
                   horizon: timedelta = decision.HORIZON) -> list[Candidate]:
        forecasts = [f for f in fd.load_forecasts(conn, at=at, horizon=horizon, only=fixtures) if f.family == self.spec.family]
        if not forecasts:
            return []
        priced = fd.read_prices(conn, forecasts, at=at)
        seen = fd.observed(conn, sorted({f.fixture_id for f in forecasts}), at=at)
        return self.from_forecasts(forecasts, priced, seen)

    def from_forecasts(self, forecasts: Sequence[fd.Forecast], priced: Mapping[fd.PriceKey, fd.Priced],
                       observed: Mapping[int, datetime]) -> list[Candidate]:
        """The candidates decision-fam-v1 would judge, from what it read (pure)."""
        found = fd.candidates([f for f in forecasts if f.family == self.spec.family], priced, observed, specs={self.spec.family: self.spec})
        return [self.from_found(c) for c in found]

    def from_found(self, c: fd.Candidate) -> Candidate:
        return Candidate(self, c.key, {c.forecast.model: c.row()}, model_hint=c.forecast.model)

    def gate(self, world: decision.World, market: str, model: str) -> GateStatus:
        return gate_of(world, market, model)

    def claims(self, row: Mapping[str, Any]) -> bool:
        if row.get("decision_version") != self.params.decision_version:
            return False
        for flt in row.get("filters") or []:
            if isinstance(flt, Mapping) and flt.get("key") == "family":
                return (flt.get("data") or {}).get("family") == self.spec.family
        return self.owns(str(row.get("market_key")))


CORE: Final = CoreFamily()
FORECAST_FAMILIES: Final = tuple(ForecastFamily(spec) for _, spec in sorted(fd.SPECS.items()))
FAMILIES: Final[tuple[MarketFamily, ...]] = (CORE, *FORECAST_FAMILIES)
"""The families of today, core first. A replay or a pass takes this tuple, or any other: the engine knows no family by name."""


def family_of(row: Mapping[str, Any], families: Sequence[MarketFamily] = FAMILIES) -> MarketFamily | None:
    """The family that decided a row of ``intel.decisions``, or None when none claims it."""
    return next((f for f in families if f.claims(row)), None)
