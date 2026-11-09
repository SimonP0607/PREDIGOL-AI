"""BE-017. Propiedades (Hypothesis) del codigo puro que convierte cuotas en probabilidades y en unidades de stake.

Un test de ejemplos comprueba los casos que alguien penso; una propiedad comprueba una regla contra miles de casos que nadie penso y, si la
rompe, reduce el contraejemplo al mas pequeno. Aqui: el reparto del margen de una casa (`devig`), la cuota (`DecimalOdds`), Kelly y el stake.

Hypothesis no es una libreria de la imagen (constraints.txt y pyproject.toml no cambian): el CI la instala junto a pytest-xdist y, donde no esta,
este archivo se salta entero. Corrida determinista (`derandomize`), sin plazo por ejemplo y sin base de ejemplos en disco."""

from __future__ import annotations

import itertools
import math
from decimal import Decimal

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, assume, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from fbi.core.errors import InvalidOddsError  # noqa: E402
from fbi.domain.market_probability import DevigMethod, devig  # noqa: E402
from fbi.domain.odds import DecimalOdds, overround  # noqa: E402
from fbi.intel.stake import CAPS, KELLY_FRACTION, STEP, kelly, stake_for  # noqa: E402

PROPERTY = settings(max_examples=300, derandomize=True, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])

METHODS = [DevigMethod.PROPORTIONAL, DevigMethod.SHIN, DevigMethod.POWER]

prices = st.decimals(min_value=Decimal("1.01"), max_value=Decimal("60"), places=3, allow_nan=False, allow_infinity=False)


@st.composite
def markets(draw: st.DrawFn) -> dict[str, DecimalOdds]:
    """An exclusive market of two to five outcomes priced with a margin, the way a bookmaker prices one (1.5 % to 25 %)."""
    n = draw(st.integers(min_value=2, max_value=5))
    weights = draw(st.lists(st.floats(min_value=0.02, max_value=1.0), min_size=n, max_size=n))
    margin = draw(st.floats(min_value=1.015, max_value=1.25))
    total = sum(weights)
    odds: dict[str, DecimalOdds] = {}
    for i, w in enumerate(weights):
        fair = w / total
        price = max(1.01, 1.0 / (fair * margin))
        assume(price <= 60)
        odds[f"o{i}"] = DecimalOdds.parse(f"{price:.3f}")
    assume(sum(1.0 / float(o.value) for o in odds.values()) > 1.0)
    return odds


# ── DecimalOdds ─────────────────────────────────────────────────────────────────────────────────────────────────────

@PROPERTY
@given(prices)
def test_a_price_is_kept_to_three_decimals_and_parsing_it_again_changes_nothing(price: Decimal) -> None:
    once = DecimalOdds.parse(price)
    twice = DecimalOdds.parse(str(once))
    assert once == twice and once.value == once.value.quantize(Decimal("0.001"))
    assert 0.0 < float(once.raw_implied_probability().value) < 1.0 and once.payout_per_unit() > 0


@PROPERTY
@given(st.one_of(st.floats(allow_nan=True, allow_infinity=True), st.text(max_size=12), st.integers()))
def test_anything_that_is_not_a_plausible_price_is_refused_with_the_odds_error_and_never_another(raw: object) -> None:
    try:
        parsed = DecimalOdds.parse(raw)  # type: ignore[arg-type]
    except InvalidOddsError:
        return
    assert Decimal(1) < parsed.value


# ── devig ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@PROPERTY
@given(markets(), st.sampled_from(METHODS))
def test_the_fair_probabilities_of_a_market_are_proper_and_add_up_to_one(odds: dict[str, DecimalOdds], method: DevigMethod) -> None:
    fair = devig(odds, method)
    assert set(fair) == set(odds)
    values = [f.probability.value for f in fair.values()]
    assert all(0.0 < v < 1.0 for v in values)
    assert math.isclose(sum(values), 1.0, abs_tol=1e-9)


@PROPERTY
@given(markets(), st.sampled_from(METHODS))
def test_removing_the_margin_never_raises_a_probability_and_keeps_the_order_of_the_prices(
        odds: dict[str, DecimalOdds], method: DevigMethod) -> None:
    fair = devig(odds, method)
    for name, o in odds.items():
        assert fair[name].probability.value <= float(o.raw_implied_probability().value) + 1e-9
    ordered = sorted(odds, key=lambda n: odds[n].value)
    probs = [fair[n].probability.value for n in ordered]
    assert all(a >= b - 1e-9 for a, b in itertools.pairwise(probs)), "a shorter price is never less likely than a longer one"


@PROPERTY
@given(markets(), st.sampled_from(METHODS))
def test_the_margin_a_fair_probability_reports_is_the_overround_of_the_market(odds: dict[str, DecimalOdds], method: DevigMethod) -> None:
    fair = devig(odds, method)
    book = float(overround(list(odds.values())))
    assert all(math.isclose(f.overround, book, abs_tol=2e-5) for f in fair.values())
    assert all(f.method is method for f in fair.values())


@PROPERTY
@given(markets())
def test_a_market_priced_without_margin_is_refused_by_every_method(odds: dict[str, DecimalOdds]) -> None:
    fair_odds = {name: DecimalOdds.parse(str(len(odds))) for name in odds}  # n equal prices of n: the raw probabilities add up to exactly 1
    for method in METHODS:
        with pytest.raises(InvalidOddsError):
            devig(fair_odds, method)


# ── Kelly y stake ───────────────────────────────────────────────────────────────────────────────────────────────────

probabilities = st.floats(min_value=0.001, max_value=0.999)
quotes = st.floats(min_value=1.01, max_value=60.0)


@PROPERTY
@given(probabilities, quotes)
def test_kelly_is_positive_exactly_when_the_bet_has_an_edge_and_never_asks_for_the_whole_bankroll(p: float, odds: float) -> None:
    f = kelly(p, odds)
    assert f < 1.0
    edge = p * odds - 1.0
    if edge > 1e-9:
        assert f > 0.0
    if edge < -1e-9:
        assert f < 0.0


@PROPERTY
@given(probabilities, probabilities, quotes)
def test_a_surer_bet_at_the_same_price_never_asks_for_less(p1: float, p2: float, odds: float) -> None:
    lo, hi = sorted((p1, p2))
    assert kelly(lo, odds) <= kelly(hi, odds) + 1e-12


@PROPERTY
@given(probabilities, quotes, st.floats(min_value=0.0, max_value=0.5))
def test_a_chance_that_the_bet_is_returned_never_makes_the_stake_bigger(p: float, odds: float, p_push: float) -> None:
    assert kelly(p, odds, p_push) <= max(kelly(p, odds), 0.0) + 1e-12


@PROPERTY
@given(st.sampled_from(sorted(CAPS)), st.one_of(st.none(), probabilities), st.one_of(st.none(), quotes), st.floats(min_value=0.0, max_value=0.5))
def test_a_stake_is_a_whole_number_of_steps_inside_its_cap_and_zero_without_an_edge(
        state: str, p: float | None, odds: float | None, p_push: float) -> None:
    stake = stake_for(state, p, odds, p_push)
    cap = CAPS[state]
    assert 0.0 <= stake.units <= cap + 1e-12
    assert math.isclose(stake.units / STEP, round(stake.units / STEP), abs_tol=1e-9)
    if p is None or odds is None or cap <= 0 or stake.kelly <= 0:
        assert stake.units == 0.0
    else:
        assert stake.units <= KELLY_FRACTION * stake.kelly * 100.0 + 1e-9
