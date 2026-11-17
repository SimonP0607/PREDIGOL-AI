"""C-00, the reference contract: every base type and both projections in one small answer (AD-J01, IA-057).

It has no route and no consumer. It exists so that the conventions are exercised by the same tests every real contract
goes through (examples, no leak, versions), and so that the web can test its pieces (``ProbabilityLine``,
``LifecycleChip``, the empty states with their reason) against a fixed example before C-01 arrives. Its teams are
fictitious (``tests/fixtures/contracts/intelligence/C-00``).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CitedFact,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.vocab import (
    AbstentionCode,
    Availability,
    CapabilityState,
    LifecycleState,
    LineupDependency,
    MarketState,
    PublicState,
    public_state_of,
)


class SampleOutcome(IntelligenceModel):
    """One outcome of the match and its one figure."""

    outcome: Literal["home", "draw", "away"]
    probability: Probability


class SampleSelection(IntelligenceModel):
    """A selection as a reader sees it: only published ones, with their public state."""

    selection_id: int
    market: str
    outcome: str
    public_state: PublicState
    probability: Probability


class SampleSelectionPrivate(SampleSelection):
    """The same selection as the owner sees it: its state in the cycle, whether he authorised it, and the model's own
    number with its seal. ``public_state`` is derived from the cycle; null means it never reaches a reader."""

    # A private class may narrow a field of its public one (here: null for what never reaches a reader); the type
    # checker sees an override, the projection tests see that the public answer is still the public class's.
    public_state: PublicState | None = Field(  # type: ignore[assignment]
        description="Derived from lifecycle_state and authorised; null: private.")
    lifecycle_state: LifecycleState = private(description="Where the selection is in its cycle (AD-D02).")
    authorised: bool = private(description="The owner authorised its publication.")
    raw_probability: Probability = private(description="The model's own number, with its seal (sin_calibrar).")
    lineup_dependency: LineupDependency = private(description="How much it depends on the official line-up.")

    @model_validator(mode="after")
    def _derived(self) -> SampleSelectionPrivate:
        if self.public_state != public_state_of(self.lifecycle_state, authorised=self.authorised):
            raise ValueError(f"public_state {self.public_state} is not the one {self.lifecycle_state} gives")
        return self

    def shown_in_public(self) -> bool:
        return self.public_state is not None


class SampleAbsence(IntelligenceModel):
    """An absence: the state, its source and its date - nothing medical."""

    player: str
    availability: Availability
    source: str
    known_at: UtcDatetime


class ConventionsSample(IntelligenceContract):
    """C-00, public projection."""

    CONTRACT_ID: ClassVar[str] = "C-00"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    fixture_id: int
    home: str
    away: str
    kickoff_at: UtcDatetime
    outcomes: list[SampleOutcome] = Field(description="One figure per outcome, the same the decision uses.")
    selections: ItemList[SampleSelection]
    facts: ItemList[CitedFact]
    absences: ItemList[SampleAbsence]
    chronicle: str | Missing = Field(description="The one chronicle, or why there is none yet.")
    official_lineup: str | Missing = Field(description="The official line-up, or when it is expected.")
    home_goals_per_90: float | Missing = Field(description="A rate per 90 minutes, or the sample it lacks.")
    market_state: MarketState
    market_validation: MarketValidation

    @model_validator(mode="after")
    def _one_figure_per_outcome(self) -> ConventionsSample:
        names = [o.outcome for o in self.outcomes]
        if sorted(names) != sorted(set(names)):
            raise ValueError("one figure per outcome")
        return self


class ConventionsSamplePrivate(ConventionsSample):
    """C-00, private projection: the public one and what only the owner sees."""

    selections: ItemList[SampleSelectionPrivate]  # type: ignore[assignment]  # the private variant of each item
    abstentions: list[AbstentionCode] = private(description="Why the system did not produce something.")
    capability_state: CapabilityState = private(description="How far the capability behind this answer has gone.")
