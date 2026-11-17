"""The single figure (AD-B05, IA-083, ``forecast-v2``): one function makes the probability of every goals market of a match.

What is held here, without a database: the page's three markets are ``forecast-v1``'s numbers exactly; an event of the result is the 1X2
figure added up (one event, one figure); every complete set wins and returns one; a line no model stored comes from the model's own matrix;
the seal follows the champion and the price; a market outside the menu has no figure and says why; and the parameters recovered from the
stored rows are the simulator's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.forecasting import score_matrix as sm
from fbi.forecasting import single_figure as sf
from fbi.forecasting.market_view import (
    BASIS_CHAMPION,
    BASIS_NEEDS_PRICE,
    BASIS_NO_CHAMPION,
    CALIBRATED,
    MARKETS,
    UNCALIBRATED,
    Row,
    Source,
    forecast_market,
)
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.models.quoted import price_quoted_lines
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from fbi.simulator import consistency

AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CUT = AT - timedelta(hours=2)
FID = 901
QUOTED = [("OU", s, Decimal(x)) for x in ("1.5", "2.25", "3.5") for s in ("Over", "Under")] + [
    ("AH", "Home", Decimal("-1")), ("AH", "Away", Decimal("1")), ("AH", "Home", Decimal("-0.5")), ("AH", "Away", Decimal("0.5")),
    ("AH", "Home", Decimal("-1.25")), ("AH", "Away", Decimal("1.25")), ("DC", "1X", Decimal(0)), ("DC", "X2", Decimal(0)),
    ("DC", "12", Decimal(0))]


def matrix(lh: float, la: float, rho: float | None) -> object:
    m = poisson_matrix(lh, la)
    return dc_tau(m, lh, la, rho) if rho is not None else m


def model_rows(model: str, lh: float, la: float, rho: float | None = None, version: int = 7) -> dict[sf.PriceKey, Source]:
    """What the model's writer stores: the seven fixed rows and every quoted line, rounded to six places (``fbi.predictions.forecast``)."""
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    out: dict[sf.PriceKey, Source] = {}
    for (mk, s, line), p in zip(MARKET_ROWS, from_matrix(m, lh, la).as_rows(), strict=True):
        out[sf.key_of(mk, s, line)] = Source(model, version, CUT, "fh", round(p, 6), round(p, 6) - 0.03, round(p, 6) + 0.03, 0.0)
    for lp in price_quoted_lines(m, QUOTED):
        out[sf.key_of(lp.market_key, lp.selection, lp.line)] = Source(model, version, CUT, "fh", round(lp.p_win, 6), None, None,
                                                                       round(lp.p_push, 6))
    return out


def nothing() -> CalibrationState:
    return CalibrationState(champions={}, best={}, wf={}, edge={})


def with_champions(*pairs: tuple[str, str], method: str = "logit2") -> CalibrationState:
    params = {"a": 0.1, "b": 0.6, "c": 0.4} if method == "logit2" else {}
    cals = {pair: Calibrator(pair[0], pair[1], method, params, id=10 + i, role="CHAMPION") for i, pair in enumerate(pairs)}
    return CalibrationState(champions=cals, best=dict(cals), wf={}, edge={})


def prices_for(numbers: dict[sf.PriceKey, Source], shift: float = 0.02, as_of: datetime = AT - timedelta(hours=30)
               ) -> dict[sf.PriceKey, tuple[float, datetime]]:
    """A consensus near the model, for every outcome it priced (the de-vigged price of each side)."""
    return {k: (min(max(s.p + (shift if k[1] in ("Home", "Over", "Yes") else -shift), 0.02), 0.98), as_of) for k, s in numbers.items()}


@pytest.fixture
def numbers() -> dict[str, dict[sf.PriceKey, Source]]:
    return {"dixon_coles": model_rows("dixon_coles", 1.55, 1.05, -0.08), "poisson": model_rows("poisson", 1.50, 1.10, version=8)}


# -- the page's three markets are forecast-v1's ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("cal", [nothing(), with_champions(("OU", "poisson"), ("1X2", "dixon_coles")),
                                 with_champions(("BTTS", "poisson"), method="identity")])
def test_the_three_markets_of_the_page_are_forecast_v1_to_six_places(numbers: dict[str, dict[sf.PriceKey, Source]],
                                                                     cal: CalibrationState) -> None:
    prices = prices_for(numbers["poisson"]) | prices_for(numbers["dixon_coles"])
    fs = sf.figure_set(FID, numbers, cal, prices)
    for (market, line), selections in MARKETS.items():
        models = {name: [Row(s, rows[sf.key_of(market, s, line)]) for s in selections] for name, rows in numbers.items()}
        v1 = forecast_market(FID, market, line, models, cal, {s: prices[sf.key_of(market, s, line)] for s in selections})
        assert v1 is not None
        for o in v1.outcomes:
            f = fs.get(market, o.selection, line)
            assert f is not None and f.source == sf.SOURCE_STORED
            assert round(f.p, 6) == round(o.p, 6) and round(f.p_model, 6) == round(o.p_model, 6), (market, o.selection)
            assert (f.model, f.calibration, f.basis, f.calibrator_id) == (v1.model, v1.calibration, v1.basis, v1.calibrator_id)
            assert f.version == sf.VERSION


# -- one event, one figure -------------------------------------------------------------------------------------------------------------

def test_every_event_of_the_result_is_the_1x2_figure_added_up(numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    cal = with_champions(("1X2", "dixon_coles"), ("AH", "dixon_coles"), ("AH", "poisson"))
    prices = prices_for(numbers["dixon_coles"]) | prices_for(numbers["poisson"])
    fs = sf.figure_set(FID, numbers, cal, prices)
    h, d, a = (fs.get("1X2", s, 0) for s in ("Home", "Draw", "Away"))
    assert h and d and a and h.calibration == CALIBRATED
    expected = {("DC", "1X", 0): (h.p + d.p, 0), ("DC", "X2", 0): (d.p + a.p, 0), ("DC", "12", 0): (h.p + a.p, 0),
                ("DNB", "Home", 0): (h.p, d.p), ("DNB", "Away", 0): (a.p, d.p), ("AH", "Home", 0): (h.p, d.p),
                ("AH", "Home", "-0.5"): (h.p, 0), ("AH", "Away", "0.5"): (d.p + a.p, 0), ("AH", "Home", "-0.25"): (h.p, d.p / 2),
                ("AH", "Away", "0.25"): (a.p + d.p / 2, d.p / 2)}
    for (m, s, line), (win, push) in expected.items():
        f = fs.get(m, s, str(line))
        assert f is not None and f.source == sf.SOURCE_RESULT, (m, s, line)
        assert f.p == pytest.approx(win, abs=1e-12) and f.push == pytest.approx(push, abs=1e-12)
        assert (f.model, f.calibration, f.basis, f.calibrator_id) == (h.model, h.calibration, h.basis, h.calibrator_id), (m, s, line)
    # the Asian champion is not applied to an event of the result, though the model stored that line and it has a price
    assert sf.key_of("AH", "Home", "-0.5") in numbers["dixon_coles"]
    assert not sm.coherence({k: v for k, v in fs.prices().items() if k[0] in ("1X2", "DC", "DNB")}, tol=1e-12)


def test_every_complete_set_wins_and_returns_one_calibrated_or_not(numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    cal = with_champions(("OU", "poisson"), ("OU", "dixon_coles"), ("AH", "poisson"), ("AH", "dixon_coles"))
    fs = sf.figure_set(FID, numbers, cal, prices_for(numbers["dixon_coles"]) | prices_for(numbers["poisson"]))
    lines = {(f.market_key, f.line if f.market_key != "AH" or f.selection == "Home" else -f.line) for f in fs.figures.values()
             if f.market_key in ("OU", "AH", "OU_HOME", "OU_AWAY", "EH")}
    assert ("OU", Decimal("2.25")) in lines and ("AH", Decimal("-1.25")) in lines and ("OU_HOME", Decimal("1.5")) in lines
    for market, line in lines:
        sides = [f for f in fs.figures.values() if f.market_key == market and (
            f.line == line if market != "AH" else (f.line == line if f.selection == "Home" else f.line == -line))]
        total = sum(f.p for f in sides) + (sides[0].push if market != "EH" else 0.0)
        assert total == pytest.approx(1.0, abs=2e-6), (market, line, total)
        assert len({(f.model, f.calibration, f.basis) for f in sides}) == 1, "one model and one seal per set"
    assert {f.calibration for f in fs.figures.values() if f.market_key == "OU" and f.line == Decimal("3.5")} == {CALIBRATED}
    assert {(f.calibration, f.basis) for f in fs.figures.values() if f.market_key in ("OU_HOME", "OU_AWAY", "EH")} == {
        (UNCALIBRATED, BASIS_NO_CHAMPION)}, "no champion exists for the goals of one side nor the European handicap"


def test_a_line_no_model_stored_comes_from_its_own_matrix_and_matches_the_models_arithmetic(
        numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    fs = sf.figure_set(FID, numbers, nothing(), {}, extra=[("OU", "Over", Decimal("4.75")), ("AH", "Away", Decimal("2"))])
    over = fs.get("OU", "Over", "4.75")
    assert over is not None and over.source == sf.SOURCE_MATRIX
    inv = fs.matrices[over.model]
    assert inv is not None and inv.residual < 1e-5
    exact = sm.derive(sm.build(inv.params), ou_lines=[Decimal("4.75")], ah_lines=[Decimal("-2")])
    assert over.p == pytest.approx(exact[("OU", "Over", Decimal("4.75"))].win, abs=1e-12)
    away = fs.get("AH", "Away", 2)
    assert away is not None and away.p == pytest.approx(exact[("AH", "Away", Decimal("2"))].win, abs=1e-12)
    stored = fs.get("OU", "Over", "1.5")
    assert stored is not None and stored.source == sf.SOURCE_STORED and stored.p == numbers[stored.model][sf.key_of("OU", "Over", "1.5")].p


def test_the_seal_follows_the_champion_and_the_price_never_the_hour(numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    cal = with_champions(("OU", "poisson"), ("OU", "dixon_coles"))
    without = sf.figure_set(FID, numbers, cal, {})
    assert {(f.calibration, f.basis) for f in without.figures.values() if f.market_key == "OU"} == {(UNCALIBRATED, BASIS_NEEDS_PRICE)}
    priced = sf.figure_set(FID, numbers, cal, prices_for(numbers["poisson"]) | prices_for(numbers["dixon_coles"]))
    ou = [f for f in priced.figures.values() if f.market_key == "OU"]
    assert {(f.calibration, f.basis) for f in ou} == {(CALIBRATED, BASIS_CHAMPION)}
    assert all(f.price_as_of == AT - timedelta(hours=30) for f in ou), "the price used is kept with its moment"
    assert all(f.p_model != f.p for f in ou) and all(f.lo is None or f.lo <= f.p <= (f.hi or 1) for f in ou)


def test_a_market_outside_the_menu_has_no_figure_and_says_why(numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    fs = sf.figure_set(FID, numbers, nothing(), {})
    assert fs.get("CORNERS_OU", "Over", "9.5") is None and fs.why_none("CORNERS_OU", "Over", "9.5") == sf.NOT_IN_VIEW
    assert fs.why_none("OU", "Over", "9.25") == sf.NO_READING
    assert fs.why_none("OU", "Over", "2.5") is None
    empty = sf.figure_set(FID, {}, nothing(), {})
    assert not empty.figures and empty.why_none("1X2", "Home", 0) == sf.NO_READING


def test_without_a_goal_model_the_result_still_has_its_events(numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    elo = {sf.key_of("1X2", s, 0): Source("elo_ologit", 3, CUT, "fe", p, None, None, 0.0)
           for s, p in (("Home", 0.5), ("Draw", 0.3), ("Away", 0.2))}
    fs = sf.figure_set(FID, {"elo_ologit": elo}, nothing(), {})
    dc = fs.get("DC", "1X", 0)
    assert dc is not None and dc.p == pytest.approx(0.8) and dc.model == "elo_ologit"
    assert fs.get("OU", "Over", "2.5") is None and fs.matrices == {}


def test_reading_ids_name_the_version_the_selection_and_the_inputs(numbers: dict[str, dict[sf.PriceKey, Source]]) -> None:
    a = sf.figure_set(FID, numbers, nothing(), {})
    b = sf.figure_set(FID, numbers, nothing(), {})
    assert {k: f.reading_id for k, f in a.figures.items()} == {k: f.reading_id for k, f in b.figures.items()}, "deterministic"
    assert len(a.by_reading()) == len(a.figures), "one id per selection"
    moved = dict(numbers)
    moved["poisson"] = model_rows("poisson", 1.60, 1.10, version=9)
    c = sf.figure_set(FID, moved, nothing(), {})
    f = a.get("OU", "Over", "1.5")
    g = c.get("OU", "Over", "1.5")
    assert f is not None and g is not None and f.model == g.model == "dixon_coles" and f.reading_id == g.reading_id, "same inputs, same id"
    h, i = a.get("BTTS", "Yes", 0), c.get("BTTS", "Yes", 0)
    assert h is not None and i is not None
    other = sf.reading_id("forecast-v1", FID, h.key, h.set_hash)
    assert other != h.reading_id and len(h.reading_id) == 12


@pytest.mark.parametrize(("lh", "la", "rho"), [(1.4, 1.1, None), (0.6, 2.4, None), (1.8, 0.9, -0.12), (1.2, 1.2, 0.05)])
def test_the_parameters_recovered_are_the_simulators(lh: float, la: float, rho: float | None) -> None:
    kind = "dixon_coles" if rho is not None else "poisson"
    rows = model_rows(kind, lh, la, rho)
    ours = sm.invert({k: v.p for k, v in rows.items()}, kind)
    theirs = consistency.invert([consistency.StoredRow(k[0], k[1], float(k[2]), v.p, v.push) for k, v in rows.items()], kind)
    assert ours is not None and theirs is not None
    assert (ours.params.lam_home, ours.params.lam_away, ours.params.rho) == pytest.approx(
        (theirs.lam_home, theirs.lam_away, theirs.rho), abs=1e-9)
    assert ours.params.lam_home == pytest.approx(lh, abs=1e-4) and ours.residual < 1e-5
    assert sm.invert({}, kind) is None and sm.invert({k: v.p for k, v in rows.items()}, "elo_ologit") is None
