"""Edge and expected value, with one convention each and no way around it.

Every number here is a *fraction*: 0.05 means five hundredths. Percentages
exist only at the edge of the system, through explicitly named constructors and
renderers. A function that receives an ``ExpectedValue`` never has to wonder
whether 5 means 5 % or 500 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from fbi.core.errors import DomainError
from fbi.domain.market_probability import FairProbability
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability

VALUE_QUANTUM: Final[Decimal] = Decimal("0.000001")  # NUMERIC(8,6) in the schema


@dataclass(frozen=True, slots=True)
class Edge:
    """Model probability minus fair market probability, in probability points.

    +0.027 means the model believes the outcome is 2.7 points more likely than
    the de-vigged market does. It is NOT a price comparison: for that see
    ``PriceEdge``. The legacy blurred the two and called the sum "edge".
    """

    value: Decimal

    def __post_init__(self) -> None:
        d = Decimal(self.value)
        if d < -1 or d > 1:
            raise DomainError(f"an edge is a difference of probabilities and lives in [-1, 1]; got {d}")
        object.__setattr__(self, "value", d.quantize(VALUE_QUANTUM, rounding=ROUND_HALF_UP))

    @classmethod
    def between(cls, model: Probability, fair: FairProbability) -> Edge:
        return cls(Decimal(str(model.value)) - Decimal(str(fair.probability.value)))

    def as_percentage_points(self) -> Decimal:
        """For presentation: 0.027 -> 2.7 (percentage points, "pp")."""
        return self.value * 100

    @property
    def is_positive(self) -> bool:
        return self.value > 0


@dataclass(frozen=True, slots=True)
class PriceEdge:
    """Taken odds versus fair odds: taken / fair - 1.

    +0.014 means the price obtained pays 1.4 % more than the fair price. This
    is what settles whether a bet was worth taking *at that price*, independent
    of how confident the model was.
    """

    value: Decimal

    def __post_init__(self) -> None:
        d = Decimal(self.value)
        if d <= -1:
            raise DomainError(f"price edge below -100 % is impossible; got {d}")
        object.__setattr__(self, "value", d.quantize(VALUE_QUANTUM, rounding=ROUND_HALF_UP))

    @classmethod
    def between(cls, taken: DecimalOdds, fair: FairProbability) -> PriceEdge:
        fair_odds = Decimal(1) / Decimal(str(fair.probability.value))
        return cls(taken.value / fair_odds - Decimal(1))

    def as_percentage(self) -> Decimal:
        return self.value * 100


@dataclass(frozen=True, slots=True)
class ExpectedValue:
    """Expected net return per unit staked, as a fraction.

    ``per_unit = p_win * (odds - 1) - p_lose``. +0.05 means five hundredths of
    a unit expected per unit staked. There is exactly one way to express this
    as a percentage (``as_percentage``) and exactly one way to build it from
    one (``from_percentage``), and both say what they do in their name.

    Per unit STAKED, not per unit at risk. On a line that can push the two
    differ by the push probability, and only the staked version is comparable
    across markets - which is the whole point of ranking picks by it.
    """

    per_unit: Decimal

    def __post_init__(self) -> None:
        d = Decimal(self.per_unit)
        if d < -1:
            raise DomainError(f"expected value cannot be below -1 per unit (total loss); got {d}")
        object.__setattr__(self, "per_unit", d.quantize(VALUE_QUANTUM, rounding=ROUND_HALF_UP))

    @classmethod
    def of(
        cls,
        probability: Probability,
        odds: DecimalOdds,
        push: Probability | None = None,
    ) -> ExpectedValue:
        """Expected net return per unit STAKED, pushes included.

        ``p_win(odds - 1) - p_lose``, where a push contributes nothing either
        way because the stake comes back. With no push this is the two-way
        formula unchanged, which is why every existing caller is unaffected.

        The push is not a detail that can be left out. Measured over our own
        stored prices, 66% of the Asian Handicap series and 51% of the
        Over/Under series sit on lines that can push - whole lines outright, and
        quarter lines for half the stake. Pricing those as two-way bets
        overstates the expected value of every one of them.
        """
        p = Decimal(str(probability.value))
        u = Decimal(str(push.value)) if push is not None else Decimal(0)
        if p + u > Decimal(1):
            raise DomainError(
                f"win and push probabilities cannot exceed 1 together; got {p} + {u}"
            )
        return cls(p * odds.payout_per_unit() - (Decimal(1) - p - u))

    @classmethod
    def from_percentage(cls, percent: Decimal | str | int) -> ExpectedValue:
        """The ONLY way a percentage becomes an ExpectedValue."""
        return cls(Decimal(percent) / Decimal(100))

    def as_percentage(self) -> Decimal:
        return self.per_unit * 100

    @property
    def is_positive(self) -> bool:
        return self.per_unit > 0

    def adjusted_for_uncertainty(
        self,
        lower_bound: Probability,
        odds: DecimalOdds,
        push: Probability | None = None,
    ) -> ExpectedValue:
        """EV recomputed at the LOWER end of the probability interval.

        This is the number a decision should use: a model that is not sure
        gets less credit, not more. The push probability is not part of the
        model's uncertainty - it is a property of the line - so it is carried
        through unchanged.
        """
        return ExpectedValue.of(lower_bound, odds, push)
