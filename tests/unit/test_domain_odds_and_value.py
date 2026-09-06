"""Odds, fair probability, edge and expected value - each with one meaning."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.core.errors import DomainError, InvalidOddsError, InvalidUnitsError
from fbi.domain import (
    DecimalOdds,
    DevigMethod,
    Edge,
    ExpectedValue,
    FairProbability,
    PriceEdge,
    Probability,
    ProfitUnits,
    RawImpliedProbability,
    StakeUnits,
    devig,
    fair_distribution,
    overround,
    roi,
)

# ── DecimalOdds ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["2.10", "1.001", "999.999", 2, "3"])
def test_plausible_odds_are_accepted(text: str | int) -> None:
    assert DecimalOdds.parse(text).value >= Decimal("1.001")


@pytest.mark.parametrize("text", ["1.0", "1", "0.5", "-2", "1000", "abc", "nan"])
def test_implausible_odds_are_refused(text: str) -> None:
    with pytest.raises(InvalidOddsError):
        DecimalOdds.parse(text)


def test_a_float_cannot_be_passed_directly() -> None:
    """2.1 as a float is not 2.100. The parse path goes through str for that reason."""
    with pytest.raises(InvalidOddsError, match="Decimal"):
        DecimalOdds(2.1)  # type: ignore[arg-type]
    assert DecimalOdds.parse(2.1).value == Decimal("2.100")


def test_odds_are_quantised_to_the_schema_precision() -> None:
    assert DecimalOdds.parse("2.12345").value == Decimal("2.123")


def test_raw_implied_probability_is_called_raw_and_includes_the_margin() -> None:
    raw = RawImpliedProbability.from_odds(DecimalOdds.parse("2.00"))
    assert raw.probability.value == pytest.approx(0.5)
    # Three "even" outcomes at 2.80 sum well above 1: that excess is the margin.
    assert overround([DecimalOdds.parse("2.80")] * 3) > Decimal(1)


def test_overround_needs_a_market_not_a_single_price() -> None:
    with pytest.raises(InvalidOddsError):
        overround([DecimalOdds.parse("2.0")])


# ── de-vigging ──────────────────────────────────────────────────────────────

BOOK = {"Home": DecimalOdds.parse("2.10"), "Draw": DecimalOdds.parse("3.40"), "Away": DecimalOdds.parse("3.60")}


@pytest.mark.parametrize("method", [DevigMethod.PROPORTIONAL, DevigMethod.SHIN, DevigMethod.POWER])
def test_devigged_probabilities_form_a_valid_distribution(method: DevigMethod) -> None:
    fair = devig(BOOK, method)
    dist = fair_distribution(fair)  # raises if it does not sum to 1
    assert set(dist) == {"Home", "Draw", "Away"}
    for f in fair.values():
        assert f.method is method
        assert f.overround == pytest.approx(1 / 2.10 + 1 / 3.40 + 1 / 3.60)


def test_fair_probability_is_below_raw_implied_for_every_outcome() -> None:
    fair = devig(BOOK, DevigMethod.PROPORTIONAL)
    for name, odds in BOOK.items():
        assert fair[name].probability < odds.raw_implied_probability()


def test_shin_shrinks_the_longshot_more_than_the_favourite() -> None:
    """The favourite-longshot bias is the reason Shin exists."""
    prop = devig(BOOK, DevigMethod.PROPORTIONAL)
    shin = devig(BOOK, DevigMethod.SHIN)
    assert shin["Home"].probability > prop["Home"].probability
    assert shin["Away"].probability < prop["Away"].probability


def test_a_fair_book_cannot_be_devigged() -> None:
    fair_book = {"A": DecimalOdds.parse("2.0"), "B": DecimalOdds.parse("2.0")}
    with pytest.raises(InvalidOddsError, match="no margin"):
        devig(fair_book, DevigMethod.PROPORTIONAL)


def test_the_unimplemented_method_says_so_instead_of_pretending() -> None:
    with pytest.raises(NotImplementedError, match="LOGARITHMIC"):
        devig(BOOK, DevigMethod.LOGARITHMIC)


def test_raw_and_fair_are_different_types() -> None:
    """A function typed to take FairProbability cannot be handed a raw one.
    mypy enforces it statically; this pins it at runtime too."""
    raw = RawImpliedProbability.from_odds(DecimalOdds.parse("2.0"))
    assert not isinstance(raw, FairProbability)


# ── edge / price edge / EV ──────────────────────────────────────────────────


def fair(p: float) -> FairProbability:
    return FairProbability(Probability(p), DevigMethod.SHIN, 1.05)


def test_edge_is_a_difference_in_probability_points() -> None:
    e = Edge.between(Probability(0.492), fair(0.465))
    assert e.value == Decimal("0.027000")
    assert e.as_percentage_points() == Decimal("2.700000")
    assert e.is_positive


def test_price_edge_compares_the_price_taken_to_the_fair_price() -> None:
    pe = PriceEdge.between(DecimalOdds.parse("2.15"), fair(0.465))
    # fair odds = 1/0.465 = 2.1505; 2.15/2.1505 - 1 ~ -0.0002
    assert abs(pe.value) < Decimal("0.001")


def test_edge_and_price_edge_can_disagree() -> None:
    """A model edge with a bad price: positive edge, negative price edge.
    The legacy could not express this; it had one number called edge."""
    e = Edge.between(Probability(0.514), fair(0.502))
    pe = PriceEdge.between(DecimalOdds.parse("1.95"), fair(0.502))
    assert e.is_positive
    assert pe.value < 0


def test_expected_value_convention_is_a_fraction_per_unit() -> None:
    ev = ExpectedValue.of(Probability(0.5), DecimalOdds.parse("2.20"))
    assert ev.per_unit == Decimal("0.100000")
    assert ev.as_percentage() == Decimal("10.000000")


def test_five_percent_and_five_are_not_confusable() -> None:
    assert ExpectedValue.from_percentage(5).per_unit == Decimal("0.050000")
    assert ExpectedValue(Decimal("5")).per_unit == Decimal("5.000000")  # +500 %: legal, and obviously not 5 %


def test_ev_below_total_loss_is_impossible() -> None:
    with pytest.raises(DomainError):
        ExpectedValue(Decimal("-1.5"))


def test_ev_at_the_lower_bound_is_never_higher_than_at_the_point_estimate() -> None:
    odds = DecimalOdds.parse("2.10")
    ev = ExpectedValue.of(Probability(0.49), odds)
    adjusted = ev.adjusted_for_uncertainty(Probability(0.44), odds)
    assert adjusted.per_unit < ev.per_unit


# ── units ───────────────────────────────────────────────────────────────────


def test_a_stake_is_strictly_positive() -> None:
    for bad in ("0", "-1"):
        with pytest.raises(InvalidUnitsError):
            StakeUnits(Decimal(bad))


def test_profit_may_be_negative_and_adds_up() -> None:
    total = ProfitUnits(Decimal("1.1")) + ProfitUnits(Decimal("-0.5"))
    assert total.value == Decimal("0.6000")


def test_roi_cannot_be_computed_without_a_stake() -> None:
    """There is no roi() overload that takes None or zero. That is the design."""
    assert roi(ProfitUnits(Decimal("0.55")), StakeUnits(Decimal("1"))) == Decimal("0.5500")
    with pytest.raises(InvalidUnitsError):
        roi(ProfitUnits(Decimal("0.55")), StakeUnits(Decimal("0")))


def test_floats_are_not_accepted_as_units() -> None:
    with pytest.raises(InvalidUnitsError):
        StakeUnits(0.5)  # type: ignore[arg-type]
