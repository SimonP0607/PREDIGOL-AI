"""The value engine on a line that can push.

The trap this guards: the market side of the comparison is a de-vigged two-way
book, which sums to 1 and therefore cannot express a push, while the model
produces P(win) and P(push) separately. Compare them directly and the model
looks like it disagrees with the market by exactly the push probability - on 66%
of the Asian Handicap series and 51% of the Over/Under series.

``assess`` therefore takes the CONDITIONAL probability, the one comparable with
the market, and derives the unconditional win probability from it and the push.
An earlier version took both as arguments; the point estimate and the lower
bound then converted differently and the lower-bound expected value came out
HIGHER than the point estimate. The last test here is that case.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.core.errors import DomainError
from fbi.domain.market_probability import DevigMethod, FairProbability
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability
from fbi.domain.value import ExpectedValue
from fbi.picks.value import assess


def fair(p: float) -> FairProbability:
    return FairProbability(Probability(p), DevigMethod.SHIN, 1.05)


TWO = DecimalOdds(Decimal("2.00"))


# --- the arithmetic ---------------------------------------------------------


def test_with_no_push_the_formula_is_unchanged() -> None:
    """Every existing caller passes no push, and must get exactly what it got."""
    p, odds = Probability(0.5), DecimalOdds(Decimal("2.10"))
    assert ExpectedValue.of(p, odds) == ExpectedValue.of(p, odds, Probability(0.0))
    assert ExpectedValue.of(p, odds).per_unit == pytest.approx(Decimal("0.05"))


def test_a_push_raises_expected_value_because_the_stake_comes_back() -> None:
    without = ExpectedValue.of(Probability(0.45), TWO)
    with_push = ExpectedValue.of(Probability(0.45), TWO, Probability(0.10))
    assert with_push.per_unit > without.per_unit
    assert without.per_unit == pytest.approx(Decimal("-0.10"))   # 0.45 - 0.55
    assert with_push.per_unit == pytest.approx(Decimal("0.00"))  # 0.45 - 0.45


def test_a_certain_push_returns_the_stake_and_nothing_else() -> None:
    ev = ExpectedValue.of(Probability(0.0), DecimalOdds(Decimal("3.00")),
                          Probability(1.0))
    assert ev.per_unit == Decimal(0)


def test_win_and_push_cannot_exceed_certainty() -> None:
    with pytest.raises(DomainError, match="cannot exceed 1 together"):
        ExpectedValue.of(Probability(0.7), TWO, Probability(0.4))


# --- what the engine compares ----------------------------------------------


def test_a_model_that_agrees_with_the_market_shows_no_edge_despite_a_push() -> None:
    """The case that was wrong before. P(win) 0.45 with a 0.10 push IS 0.50
    conditional, and the market's de-vigged 0.50 is conditional too."""
    a = assess(Probability(0.50), TWO, fair(0.50), push=Probability(0.10))
    assert a.probability_edge is not None
    assert a.probability_edge.value == Decimal(0)
    assert a.push is not None and a.push.value == pytest.approx(0.10)


def test_the_expected_value_is_per_unit_staked_not_per_unit_at_risk() -> None:
    """Comparability across markets depends on this: a pushable bet and a
    two-way bet at the same stake must be rankable against each other."""
    agreeing = assess(Probability(0.50), TWO, fair(0.50), push=Probability(0.10))
    # P(win) = 0.50 * 0.90 = 0.45; 0.45*(2-1) - (1 - 0.45 - 0.10) = 0
    assert agreeing.expected_value.per_unit == pytest.approx(Decimal(0))

    disagreeing = assess(Probability(0.55), TWO, fair(0.50), push=Probability(0.10))
    # P(win) = 0.495; 0.495 - (1 - 0.495 - 0.10) = 0.09
    assert disagreeing.expected_value.per_unit == pytest.approx(Decimal("0.09"))
    at_risk = Decimal("0.55") - Decimal("0.45")   # what it would be per unit risked
    assert disagreeing.expected_value.per_unit < at_risk


def test_the_fair_odds_shorten_with_the_push() -> None:
    """1/p_conditional is (1 - push)/p_win: the price that breaks even. Treating
    a pushable bet's fair price as 1/p_win would overstate the edge on every
    whole and quarter line quoted."""
    pushable = assess(Probability(0.50), TWO, fair(0.50), push=Probability(0.10))
    two_way = assess(Probability(0.45), TWO, fair(0.45))
    assert pushable.model_fair_odds == Decimal("2.000")
    assert two_way.model_fair_odds == Decimal("2.222")


def test_the_lower_bound_expected_value_can_never_exceed_the_point_estimate() -> None:
    """The defect the earlier signature allowed. p_win was passed in beside
    p_model, the lower bound was not, and the two converted differently - so a
    model that was LESS sure produced a HIGHER expected value."""
    a = assess(Probability(0.55), TWO, fair(0.50), Probability(0.50),
               push=Probability(0.10))
    assert a.ev_at_lower_bound is not None
    assert a.ev_at_lower_bound.per_unit < a.expected_value.per_unit
    # P(win) at the lower bound = 0.50 * 0.90 = 0.45 -> 0.45 - 0.45 = 0
    assert a.ev_at_lower_bound.per_unit == pytest.approx(Decimal("0.00"))


def test_comparing_unconditional_to_conditional_would_invent_an_edge() -> None:
    """Stated as a test: hand the engine P(win) where the conditional belongs
    and a model that agrees perfectly looks 5 points pessimistic."""
    honest = assess(Probability(0.50), TWO, fair(0.50), push=Probability(0.10))
    naive = assess(Probability(0.45), TWO, fair(0.50), push=Probability(0.10))
    assert honest.probability_edge is not None and naive.probability_edge is not None
    assert honest.probability_edge.value == Decimal(0)
    assert naive.probability_edge.value == pytest.approx(Decimal("-0.05"))


def test_an_assessment_without_a_push_behaves_exactly_as_before() -> None:
    a = assess(Probability(0.55), DecimalOdds(Decimal("2.10")), fair(0.46))
    b = assess(Probability(0.55), DecimalOdds(Decimal("2.10")), fair(0.46),
               push=Probability(0.0))
    assert a.expected_value == b.expected_value
    assert a.probability_edge == b.probability_edge
    assert a.model_fair_odds == b.model_fair_odds
    assert a.push is None and b.push is not None and b.push.value == 0.0
