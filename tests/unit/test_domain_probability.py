"""Probability is a type. A float that happens to be small is not one."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.core.errors import InvalidDistributionError, InvalidProbabilityError
from fbi.domain import Probability, ProbabilityDistribution, three_way


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 0.000001, 0.999999])
def test_values_in_the_unit_interval_are_accepted(value: float) -> None:
    assert Probability(value).value == value


def test_a_percentage_is_refused_with_a_hint() -> None:
    """83 is not 83 %. It is an error, and the message says why."""
    with pytest.raises(InvalidProbabilityError, match="from_percentage"):
        Probability(83)


@pytest.mark.parametrize("value", [-0.01, 1.000001, 150, float("nan"), float("inf")])
def test_values_outside_the_interval_are_refused(value: float) -> None:
    with pytest.raises(InvalidProbabilityError):
        Probability(value)


def test_a_boolean_is_not_a_probability() -> None:
    with pytest.raises(InvalidProbabilityError):
        Probability(True)  # type: ignore[arg-type]


def test_from_percentage_is_the_only_bridge_from_percent() -> None:
    p = Probability.from_percentage(83)
    assert p.value == pytest.approx(0.83)
    assert p.as_percentage() == pytest.approx(83.0)


def test_storage_form_is_exact_decimal_for_the_schema() -> None:
    assert Probability(0.4923456789).as_decimal() == Decimal("0.492346")


def test_probabilities_are_immutable() -> None:
    p = Probability(0.4)
    with pytest.raises(AttributeError):
        p.value = 0.5  # type: ignore[misc]


def test_complement() -> None:
    assert Probability(0.3).complement().value == pytest.approx(0.7)


def test_a_valid_three_way_distribution_is_accepted() -> None:
    d = three_way(Probability(0.49), Probability(0.26), Probability(0.25))
    assert d.most_likely() == "Home"
    assert len(d) == 3


def test_a_distribution_that_does_not_sum_to_one_is_rejected_loudly() -> None:
    """The legacy broke this invariant silently (E-055). Here it cannot."""
    with pytest.raises(InvalidDistributionError, match=r"sum to 0\.900000"):
        three_way(Probability(0.40), Probability(0.25), Probability(0.25))


def test_the_tolerance_is_explicit_and_tight() -> None:
    three_way(Probability(0.5), Probability(0.25), Probability(0.2500005))  # within 1e-6
    with pytest.raises(InvalidDistributionError):
        three_way(Probability(0.5), Probability(0.25), Probability(0.25001))  # 1e-5 off


def test_normalisation_only_happens_when_asked_for_by_name() -> None:
    d = ProbabilityDistribution.normalize({"Home": 2.0, "Draw": 1.0, "Away": 1.0})
    assert d["Home"].value == pytest.approx(0.5)
    assert d["Draw"].value == pytest.approx(0.25)


@pytest.mark.parametrize("raw", [{}, {"Home": -1.0, "Away": 2.0}, {"Home": 0.0, "Away": 0.0}])
def test_normalisation_refuses_garbage(raw: dict[str, float]) -> None:
    with pytest.raises(InvalidDistributionError):
        ProbabilityDistribution.normalize(raw)


def test_an_empty_distribution_is_rejected() -> None:
    with pytest.raises(InvalidDistributionError):
        ProbabilityDistribution({})
