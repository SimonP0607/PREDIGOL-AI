"""The value engine: three different questions about one price, never merged.

    probability edge  p_model - p_market_fair          (does the model disagree with the market?)
    price edge        odds / fair_market_odds - 1      (is THIS price better than the market's fair one?)
    expected value    p_win(odds-1) - p_lose, per unit (what the model expects this bet to return)

On a line that can push, the first two are computed on probabilities CONDITIONAL
on the bet being settled - because a de-vigged two-way market cannot express a
push, so that is what the market side of the comparison is - while the third is
not, because the stake is risked whether or not the bet pushes. Mixing the two
would understate the model by exactly the push probability on 66% of the Asian
Handicap series, and it would read as disagreement with the market rather than
as a mistake.

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
    push: Probability | None = None
    """Probability the bet returns the stake, when the line can push.

    ``p_model`` and ``p_lo`` are conditional on the bet being settled, so that
    they are comparable with the de-vigged market. The expected value is not:
    it is per unit staked, computed from ``p_model * (1 - push)``, because what
    is staked is staked either way. ``model_fair_odds`` is 1/p_model, which with
    a push is ``(1 - push)/p_win`` - the price at which the bet breaks even."""


def assess(p_model: Probability, odds: DecimalOdds, fair: FairProbability | None,
           p_lo: Probability | None = None, *,
           push: Probability | None = None) -> ValueAssessment:
    """Three questions about one price, with a push handled honestly.

    ``p_model`` and ``p_lo`` are CONDITIONAL on the bet being settled, which is
    what makes them comparable with the market's de-vigged probability: two
    selections de-vigged to sum to 1 cannot express a push, so that is what the
    market side of the comparison is.

    The expected value needs the unconditional win probability instead, because
    the stake is risked whether the bet pushes or not - and that is
    ``p_model * (1 - push)``, derived here rather than passed in. An earlier
    version took it as a second argument; the point estimate and the lower bound
    then converted differently and the lower bound came out HIGHER than the
    point estimate, which is impossible. Two copies of a fact with nothing
    forcing them to agree is the defect this project keeps finding, and a
    function signature is no exception.

    With no push every number below is what it has always been.
    """
    settled = Decimal(1) - (Decimal(str(push.value)) if push is not None else Decimal(0))

    def unconditional(p: Probability) -> Probability:
        return Probability(float(Decimal(str(p.value)) * settled))

    ev = ExpectedValue.of(unconditional(p_model), odds, push)
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
        ev_at_lower_bound=(
            ev.adjusted_for_uncertainty(unconditional(p_lo), odds, push)
            if p_lo is not None else None
        ),
        model_fair_odds=(Decimal(1) / Decimal(str(p_model.value))).quantize(Decimal("0.001"), ROUND_HALF_UP)
        if p_model.value > 0 else None,
        kelly_fraction=kelly.quantize(Q, rounding=ROUND_HALF_UP),
        push=push,
    )
