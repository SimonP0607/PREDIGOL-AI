"""C-17, the units of each published pick and parlay (plan de correcciones UX/UI, AP-K07; decision D3): the contract and its example
ONLY. No route serves it and no builder fills it: ``FBI_STAKES`` stays off until the models are calibrated and the owner signs the rule
(DM-14). It is written now so that the web can build against it; nothing here changes a pick, a stake, a probability or a model.

* Each line (``StakeLine``): a published pick or a parlay, its ``stake_units`` - one of 0.25, 0.5, 0.75 or 1, a parlay at most 0.5 -,
  the ``stake_rule_version`` that gave it and ``stake_reason`` as a code.
* ``results`` (for «Transparencia»): the settled lines counted twice, with the variable units and with one fixed unit each, so a reader
  sees what the units changed and nothing is hidden behind them.

The public projection carries what a reader may see; the private one adds what the rule read (``inputs``: the fraction and the cap that
bound it). The closed list of reason codes belongs to the signed rule; until then a code is any ``CODE_PATTERN`` word and the example
uses those of today's ``stake-v1`` (``fbi.intel.stake``): ``kelly_cuarto`` (a quarter of Kelly, rounded down), ``tope_estado`` (capped
by the decision's state), ``tope_parlay`` (capped as a parlay). Owner's question: the closed list and the rule of the units.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    private,
)

STAKE_UNITS: Final[tuple[float, ...]] = (0.25, 0.5, 0.75, 1.0)
"""The units a line may carry (plan, AP-K07)."""
PARLAY_MAX_UNITS: Final = 0.5
"""A parlay never carries more than half a unit."""
RULE_PATTERN: Final = r"^stake-v\d+(\.\d+)?$"

StakeKind = Literal["pick", "parlay"]


class StakeInputs(IntelligenceModel):
    """What the rule read to give the units (private): the fraction of Kelly, the full-Kelly figure and the cap that bound it."""

    kelly_fraction: float = Field(gt=0, le=1)
    kelly_full: float
    cap_units: float = Field(ge=0)
    capped: bool


class StakeLine(IntelligenceModel):
    """The units of one published pick or parlay."""

    kind: StakeKind
    id: int = Field(ge=1, description="The pick's id (picks.picks.id) or the parlay's (picks.parlays.id).")
    stake_units: float = Field(description="0.25, 0.5, 0.75 or 1; a parlay at most 0.5.")
    stake_rule_version: str = Field(pattern=RULE_PATTERN)
    stake_reason: str = Field(pattern=CODE_PATTERN, description="Why these units, as a code of the signed rule.")
    decided_at: UtcDatetime

    @model_validator(mode="after")
    def _units(self) -> StakeLine:
        if self.stake_units not in STAKE_UNITS:
            raise ValueError(f"stake_units {self.stake_units} is not one of {STAKE_UNITS}")
        if self.kind == "parlay" and self.stake_units > PARLAY_MAX_UNITS:
            raise ValueError(f"a parlay carries at most {PARLAY_MAX_UNITS} units, not {self.stake_units}")
        return self


class StakeLinePrivate(StakeLine):
    inputs: StakeInputs | Missing = private(description="What the rule read; sin_datos for a line written before the rule kept it.")


class UnitResult(IntelligenceModel):
    """The settled lines under one way of staking."""

    staked_units: float = Field(ge=0)
    profit_units: float
    roi_pct: float | Missing = Field(description="profit / staked, in percent; sin_datos with nothing staked.")


class StakeResults(IntelligenceModel):
    """«Transparencia»: the same settled lines with the variable units and with one fixed unit each."""

    since: UtcDatetime
    settled: int = Field(ge=0)
    variable: UnitResult
    fixed: UnitResult


class Stakes(IntelligenceContract):
    """C-17, public projection."""

    CONTRACT_ID: ClassVar[str] = "C-17"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    stake_rule_version: str = Field(pattern=RULE_PATTERN, description="The rule in force for the lines of this answer.")
    lines: ItemList[StakeLine]
    results: StakeResults | Missing


class StakesPrivate(Stakes):
    """C-17, private projection: each line with what the rule read."""

    lines: ItemList[StakeLinePrivate]  # type: ignore[assignment]  # the private variant of each line
