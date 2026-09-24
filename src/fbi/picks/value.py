"""The value engine: three different questions about one price, never merged.

    probability edge  p_model - p_market_fair          (does the model disagree with the market?)
    price edge        odds / fair_market_odds - 1      (is THIS price better than the market's fair one?)
    expected value    p_model * odds - 1, per unit      (what the model expects this bet to return)

None of them is a confidence. A model's probability is a probability; how much
to trust the model is a separate question answered by its backtest against
the market (see ``fbi.picks.rules.qualify``), not by a number shown next to
the pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fbi.domain.market_probability import FairProbability
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability
from fbi.domain.value import Edge, ExpectedValue, PriceEdge

Q = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class ValueAssessment:
    p_model: Probability
    p_lo: Probability | None
    odds: DecimalOdds
    fair: FairProbability | None
    probability_edge: Edge | None
    price_edge: PriceEdge | None
    expected_value: ExpectedValue
    ev_at_lower_bound: ExpectedValue | None
    model_fair_odds: Decimal | None
    kelly_fraction: Decimal
    """Kelly fraction implied by p_model and the price; information only - the
    stake policy is flat, because a Kelly stake on an unvalidated probability
    is a bet on the model, not on the match."""


def assess(p_model: Probability, odds: DecimalOdds, fair: FairProbability | None,
           p_lo: Probability | None = None) -> ValueAssessment:
    ev = ExpectedValue.of(p_model, odds)
    b = odds.payout_per_unit()
    kelly = max(Decimal(0), ev.per_unit / b) if b > 0 else Decimal(0)
    return ValueAssessment(
        p_model=p_model,
        p_lo=p_lo,
        odds=odds,
        fair=fair,
        probability_edge=Edge.between(p_model, fair) if fair is not None else None,
        price_edge=PriceEdge.between(odds, fair) if fair is not None and fair.probability.value > 0 else None,
        expected_value=ev,
        ev_at_lower_bound=ev.adjusted_for_uncertainty(p_lo, odds) if p_lo is not None else None,
        model_fair_odds=(Decimal(1) / Decimal(str(p_model.value))).quantize(Decimal("0.001"), ROUND_HALF_UP)
        if p_model.value > 0 else None,
        kelly_fraction=kelly.quantize(Q, rounding=ROUND_HALF_UP),
    )
