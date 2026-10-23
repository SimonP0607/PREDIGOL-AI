"""PrediGol's forecast of a match (plan F5, ``forecast-v1``): the pure part - which model, calibrated or not and why, what is worth
a new row. The database part (reading, writing, the pipeline, the API) is in tests/integration/test_match_forecast.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.intel import decision
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.models.scoring import MARKET_ROWS
from fbi.predictions import match_forecast as mf

CUT = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
LINE_1X2 = Decimal("0")
LINE_OU = Decimal("2.5")

# a sheet of numbers a goal model could have produced for one match (each market adds up to one)
NUMBERS = {
    ("1X2", "Home"): (0.50, 0.44, 0.56), ("1X2", "Draw"): (0.26, 0.21, 0.31), ("1X2", "Away"): (0.24, 0.19, 0.29),
    ("OU", "Over"): (0.62, 0.55, 0.69), ("OU", "Under"): (0.38, 0.31, 0.45),
    ("BTTS", "Yes"): (0.57, 0.50, 0.64), ("BTTS", "No"): (0.43, 0.36, 0.50),
}


def rows(model: str, market: str, *, version: int = 7, cutoff: datetime = CUT, scale: float = 1.0
         ) -> list[mf.Row]:
    out = []
    for (m, sel), (p, lo, hi) in NUMBERS.items():
        if m != market:
            continue
        out.append(mf.Row(sel, mf.Source(model, version, cutoff, f"hash-{model}", p * scale, lo, hi, 0.0)))
    return out


def state(champions: dict[tuple[str, str], Calibrator] | None = None,
          best: dict[tuple[str, str], Calibrator] | None = None,
          wf: dict[tuple[str, str], dict[str, float]] | None = None) -> CalibrationState:
    return CalibrationState(champions or {}, best or {}, wf or {}, {})


def platt(market: str, model: str, *, a: float = -0.1, b: float = 0.8, ident: int = 11) -> Calibrator:
    return Calibrator(market, model, "platt", {"a": a, "b": b}, ident, "CHAMPION")


def logit2(market: str, model: str, *, ident: int = 12) -> Calibrator:
    return Calibrator(market, model, "logit2", {"a": 0.0, "b": 0.5, "c": 0.5}, ident, "CHAMPION")


# ── what is forecast ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_markets_forecast_are_the_ones_the_goal_models_price() -> None:
    assert set(mf.MARKETS) == {("1X2", LINE_1X2), ("OU", LINE_OU), ("BTTS", LINE_1X2)}
    assert mf.MARKETS[("1X2", LINE_1X2)] == ("Home", "Draw", "Away")
    assert mf.MARKETS[("OU", LINE_OU)] == ("Over", "Under")
    assert mf.MARKETS[("BTTS", LINE_1X2)] == ("Yes", "No")
    # every row a goal model writes is part of exactly one forecast market
    assert sorted((m, s, Decimal(str(line))) for m, s, line in MARKET_ROWS) == sorted(
        (m, s, line) for (m, line), sels in mf.MARKETS.items() for s in sels)
    assert {m: mf.FAMILIES[m] for m, _ in mf.MARKETS} == {"1X2": "RESULT", "OU": "TOTAL_GOALS", "BTTS": "BOTH_TEAMS_SCORE"}


def test_the_data_gate_is_the_decision_layers() -> None:
    """A match the decision layer would not look at (data not fit for a model) is not forecast either."""
    assert mf.NOT_FIT == decision.NOT_FIT


# ── calibrated or not, and why ──────────────────────────────────────────────────────────────────────────────────

def test_without_a_champion_the_model_is_stated_as_it_is_and_marked_uncalibrated() -> None:
    f = mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": rows("elo_ologit", "1X2")}, state(), {})
    assert f is not None
    assert (f.calibration, f.basis, f.calibrator_id) == (mf.UNCALIBRATED, mf.BASIS_NO_CHAMPION, None)
    assert [o.selection for o in f.outcomes] == ["Home", "Draw", "Away"]
    assert [o.p for o in f.outcomes] == [0.50, 0.26, 0.24] == [o.p_model for o in f.outcomes]
    assert f.family == "RESULT"
    assert all(o.p_market is None for o in f.outcomes)


def test_a_champion_that_needs_the_market_and_has_none_leaves_the_forecast_uncalibrated() -> None:
    cal = state(champions={("OU", "poisson"): logit2("OU", "poisson")})
    f = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, cal, {})
    assert f is not None
    assert (f.calibration, f.basis) == (mf.UNCALIBRATED, mf.BASIS_NEEDS_PRICE)
    assert [o.p for o in f.outcomes] == [0.62, 0.38], "the raw model, not a calibration against a missing price"
    # one outcome priced and the other not is still no price: the market is calibrated as a whole or not at all
    half = {"Over": (0.55, CUT)}
    g = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, cal, half)
    assert g is not None and g.basis == mf.BASIS_NEEDS_PRICE


def test_a_champion_with_the_market_calibrates_and_the_market_adds_up_to_one() -> None:
    cal = state(champions={("OU", "poisson"): logit2("OU", "poisson", ident=42)})
    market = {"Over": (0.52, CUT - timedelta(minutes=30)), "Under": (0.48, CUT - timedelta(minutes=30))}
    f = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, cal, market)
    assert f is not None
    assert (f.calibration, f.basis, f.calibrator_id) == (mf.CALIBRATED, mf.BASIS_CHAMPION, 42)
    assert sum(o.p for o in f.outcomes) == pytest.approx(1.0, abs=1e-9)
    over, under = f.outcomes
    # a calibrator that leans on the market pulls a confident model towards it
    assert 0.52 < over.p < 0.62 and 0.38 < under.p < 0.48
    assert over.p_market == 0.52 and over.market_as_of == CUT - timedelta(minutes=30)
    for o in f.outcomes:
        assert o.lo is not None and o.hi is not None and o.lo <= o.p <= o.hi


def test_a_champion_that_does_not_need_the_market_calibrates_without_one() -> None:
    cal = state(champions={("BTTS", "poisson"): platt("BTTS", "poisson")})
    f = mf.forecast_market(1, "BTTS", LINE_1X2, {"poisson": rows("poisson", "BTTS")}, cal, {})
    assert f is not None and (f.calibration, f.basis) == (mf.CALIBRATED, mf.BASIS_CHAMPION)
    assert sum(o.p for o in f.outcomes) == pytest.approx(1.0, abs=1e-9)
    assert all(o.p_market is None for o in f.outcomes), "no market was used, none is recorded"
    yes, no = f.outcomes
    assert yes.p > no.p and yes.p != yes.p_model


def test_a_calibrator_that_cannot_be_applied_is_not_dressed_up() -> None:
    cal = state(champions={("BTTS", "poisson"): platt("BTTS", "poisson")})
    broken = rows("poisson", "BTTS")
    broken[0] = mf.Row("Yes", mf.Source("poisson", 7, CUT, "h", 1.0, 0.9, 1.0, 0.0))  # p = 1: the logit does not exist
    f = mf.forecast_market(1, "BTTS", LINE_1X2, {"poisson": broken}, cal, {})
    assert f is not None and (f.calibration, f.basis) == (mf.UNCALIBRATED, mf.BASIS_NOT_APPLICABLE)


def test_an_inverted_calibrator_still_gives_an_interval_that_holds_the_probability() -> None:
    cal = state(champions={("BTTS", "poisson"): platt("BTTS", "poisson", a=0.1, b=-0.6)})
    f = mf.forecast_market(1, "BTTS", LINE_1X2, {"poisson": rows("poisson", "BTTS")}, cal, {})
    assert f is not None and f.calibration == mf.CALIBRATED
    for o in f.outcomes:
        assert o.lo is not None and o.hi is not None and 0 < o.lo <= o.p <= o.hi < 1


def test_a_model_without_an_interval_is_stated_without_one() -> None:
    bare = [mf.Row(r.selection, mf.Source(r.source.model, 7, CUT, "h", r.source.p, None, None, 0.0))
            for r in rows("elo_ologit", "1X2")]
    f = mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": bare}, state(), {})
    assert f is not None and all(o.lo is None and o.hi is None for o in f.outcomes)


# ── which model ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_market_takes_the_model_the_decision_layer_would() -> None:
    best = {("1X2", "poisson"): platt("1X2", "poisson"), ("1X2", "elo_ologit"): platt("1X2", "elo_ologit"),
            ("1X2", "dixon_coles"): platt("1X2", "dixon_coles")}
    wf = {("1X2", "poisson"): {"logloss_cal": 0.6005}, ("1X2", "elo_ologit"): {"logloss_cal": 0.5794},
          ("1X2", "dixon_coles"): {"logloss_cal": 0.6012}}
    models = {m: rows(m, "1X2") for m in ("poisson", "elo_ologit", "dixon_coles")}
    f = mf.forecast_market(1, "1X2", LINE_1X2, models, state(best=best, wf=wf), {})
    assert f is not None and f.model == "elo_ologit"
    # a champion wins over a better-looking fit
    champs = {("1X2", "poisson"): platt("1X2", "poisson")}
    g = mf.forecast_market(1, "1X2", LINE_1X2, models, state(champions=champs, best=best, wf=wf), {})
    assert g is not None and g.model == "poisson"
    # without any calibration information, the first by name
    h = mf.forecast_market(1, "1X2", LINE_1X2, models, state(), {})
    assert h is not None and h.model == "dixon_coles"


def test_a_model_that_did_not_price_every_outcome_is_not_used() -> None:
    partial = rows("elo_ologit", "1X2")[:2]
    full = rows("poisson", "1X2")
    f = mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": partial, "poisson": full}, state(), {})
    assert f is not None and f.model == "poisson"
    assert mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": partial}, state(), {}) is None
    assert mf.forecast_market(1, "1X2", LINE_1X2, {}, state(), {}) is None


def test_the_outcomes_of_a_market_never_mix_cutoffs_or_versions() -> None:
    mixed = rows("poisson", "1X2")
    mixed[1] = mf.Row("Draw", mf.Source("poisson", 8, CUT - timedelta(hours=1), "h", 0.26, 0.2, 0.3, 0.0))
    assert mf.forecast_market(1, "1X2", LINE_1X2, {"poisson": mixed}, state(), {}) is None


# ── what is worth a row ──────────────────────────────────────────────────────────────────────────────────────────

def stored_of(f: mf.MarketForecast) -> mf.Stored:
    return mf.Stored(f.model, f.model_version_id, f.calibration, f.calibrator_id,
                     {o.selection: Decimal(str(round(o.p, 6))) for o in f.outcomes})


def test_a_forecast_that_says_nothing_new_is_not_written_again() -> None:
    f = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, state(), {})
    assert f is not None
    assert mf.says_something_new(None, f)
    assert not mf.says_something_new(stored_of(f), f)
    moved_a_little = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU", scale=1.004)}, state(), {})
    assert moved_a_little is not None and not mf.says_something_new(stored_of(f), moved_a_little)


def test_a_forecast_that_moved_half_a_point_or_changed_provenance_is_written() -> None:
    f = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, state(), {})
    assert f is not None
    moved = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU", scale=1.01)}, state(), {})
    assert moved is not None and mf.says_something_new(stored_of(f), moved)
    new_version = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU", version=8)}, state(), {})
    assert new_version is not None and mf.says_something_new(stored_of(f), new_version)
    other_model = mf.forecast_market(1, "OU", LINE_OU, {"dixon_coles": rows("dixon_coles", "OU")}, state(), {})
    assert other_model is not None and mf.says_something_new(stored_of(f), other_model)
    cal = state(champions={("OU", "poisson"): platt("OU", "poisson")})
    calibrated = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, cal, {})
    assert calibrated is not None and mf.says_something_new(stored_of(f), calibrated)


def test_the_digest_follows_the_inputs() -> None:
    a = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, state(), {})
    b = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, state(), {})
    c = mf.forecast_market(2, "OU", LINE_OU, {"poisson": rows("poisson", "OU")}, state(), {})
    d = mf.forecast_market(1, "OU", LINE_OU, {"poisson": rows("poisson", "OU", cutoff=CUT + timedelta(hours=1))}, state(), {})
    assert a is not None and b is not None and c is not None and d is not None
    assert a.input_hash == b.input_hash
    assert len({a.input_hash, c.input_hash, d.input_hash}) == 3


def test_the_most_likely_outcome() -> None:
    f = mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": rows("elo_ologit", "1X2")}, state(), {})
    assert f is not None
    assert mf.most_likely(f.outcomes) == "Home"
    assert mf.most_likely([]) is None
    tie = [mf.Outcome("Over", 0.5, 0.5, None, None, 0.0), mf.Outcome("Under", 0.5, 0.5, None, None, 0.0)]
    assert mf.most_likely(tie) == "Over", "a tie goes to the first outcome in the models' order"
