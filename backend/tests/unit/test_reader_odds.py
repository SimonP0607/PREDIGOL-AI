"""RP-10.2: the comparison of the odds a reader finds with the market's fair reference (``fbi.market.reader_odds``). A hundred cases are computed here by hand
formulas, not by the module's; the module never says a bet is worth making, never reads state and says which house the reader has."""

from __future__ import annotations

import inspect
import math

import pytest

from fbi.market import reader_odds as ro

PROVIDER = {1: "Betplay", 2: "Bet365", 3: "Betano"}


def expected(odds: float, p: float) -> tuple[float, float, float, float]:
    """The four figures from the definitions: 1/odds, 1/p, odds*p - 1 in percent, and (1/odds - p) in points."""
    return 1 / odds, 1 / p, (odds * p - 1) * 100, (1 / odds - p) * 100


def test_a_hundred_cases_agree_with_the_definitions() -> None:
    n = 0
    for k in range(10):
        odds = 1.2 + 0.43 * k
        for j in range(10):
            p = 0.05 + 0.09 * j
            got = ro.compare(odds, p, books=5)
            imp, fair, dist, margin = expected(odds, p)
            assert got.status == "ok" and got.reference == "suficiente"
            assert got.implied_probability == pytest.approx(imp, abs=5e-5) and got.fair_odds == pytest.approx(fair, abs=5e-4)
            assert got.distance_pct == pytest.approx(dist, abs=0.006) and got.margin_points == pytest.approx(margin, abs=0.006)
            n += 1
    assert n == 100


def test_a_selection_priced_at_the_fair_odds_pays_no_margin_and_has_no_distance() -> None:
    got = ro.compare(2.5, 0.4, books=4)
    assert got.distance_pct == 0.0 and got.margin_points == 0.0 and got.fair_odds == 2.5


def test_odds_above_the_fair_ones_have_a_positive_distance_and_a_negative_margin_point() -> None:
    above = ro.compare(2.6, 0.4, books=4)
    assert above.distance_pct is not None and above.distance_pct > 0 and above.margin_points is not None and above.margin_points < 0
    below = ro.compare(2.3, 0.4, books=4)
    assert below.distance_pct is not None and below.distance_pct < 0 and below.margin_points is not None and below.margin_points > 0


def test_fewer_than_three_houses_give_no_fair_odds_and_no_reference_gives_none() -> None:
    few = ro.compare(2.0, 0.45, books=2)
    assert few.reference == "insuficiente" and few.fair_odds is None and few.distance_pct is None and few.margin_points is None
    assert few.implied_probability == 0.5, "the implied probability of the reader's own odds needs no reference"
    none = ro.compare(2.0, None, books=7)
    assert none.reference == "sin_dato" and none.fair_odds is None
    assert ro.compare(2.0, 0.0, books=7).reference == "sin_dato" and ro.compare(2.0, 1.0, books=7).reference == "sin_dato"


def test_the_odds_must_be_a_price() -> None:
    for bad in (0.0, 1.0, -2.0, 1001.0, math.inf):
        got = ro.compare(bad, 0.5, books=5)
        assert got.status == "cuota_invalida" and got.implied_probability is None and got.fair_odds is None
    assert ro.compare(1.01, 0.5, books=5).status == "ok" and ro.compare(1000.0, 0.5, books=5).status == "ok"


def test_the_house_is_one_the_provider_quotes_one_it_does_not_or_not_licensed() -> None:
    assert ro.house_state("Betplay", PROVIDER) == "cotizada" and ro.house_state(" betplay ", PROVIDER) == "cotizada"
    assert ro.house_state("Wplay", PROVIDER) == "no_cotizada", "licensed in Colombia, not priced by the provider"
    assert ro.house_state("Bet365", PROVIDER) == "no_licenciada", "the provider prices it but it is not on the list of licensed houses"
    assert ro.house_state(None, PROVIDER) == "sin_casa" and ro.house_state("  ", PROVIDER) == "sin_casa"
    assert ro.compare(2.0, 0.45, books=5, brand="Rush Bet", provider_names={9: "Rushbet"}).house == "cotizada"


def test_no_note_recommends_and_the_module_keeps_no_state() -> None:
    notes = " ".join(n for pair in ro._NOTES.values() for n in pair).lower()
    for word in ("conviene", "apuesta segura", "valor", "recomend", "deberías", "should bet", "worth"):
        assert word not in notes.replace("no es una recomendación", "").replace("it is not a recommendation", ""), word
    source = inspect.getsource(ro)
    for forbidden in ("import psycopg", "datetime", "os.environ", "open(", "INSERT", "requests"):
        assert forbidden not in source, forbidden
    assert ro.compare(2.0, 0.45, books=5).as_json()["version"] == "reader-odds-v1"
