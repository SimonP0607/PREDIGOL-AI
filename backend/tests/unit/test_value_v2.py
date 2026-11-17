"""value-v2 (``fbi.valuation.value``, AD-E02, IA-097): the arithmetic of the expected value on lines that push and on quarter lines, the
fair price, the interval and its properties (it contains the point, it widens with the uncertainty, the expected value rises with the
price), «una sola casa» that never confirms, no ranges of odds, a price after the moment refused - and decision-v2 carrying it as a
measurement that no stage reads."""

from __future__ import annotations

import dataclasses
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.decision import engine, replay
from fbi.forecasting import score_matrix as sm
from fbi.intel import decision
from fbi.valuation import value as v

from .test_decision_v2_engine import MODEL, cases, core, pick, world
from .test_decision_v2_engine import build as build_case

AT = datetime(2026, 11, 17, 15, tzinfo=UTC)


def quote(odds: float | None = 2.0, books: int | None = 5, age: timedelta | None = timedelta(minutes=30)) -> v.Quote:
    return v.Quote(odds, books, None if age is None else AT - age)


# -- the arithmetic -------------------------------------------------------------------------------------------------------------------

def test_the_expected_value_and_the_fair_price_of_a_plain_selection() -> None:
    r = v.assess(v.Chance(0.55, 0.0, 0.50, 0.60), quote(2.0), at=AT)
    assert r.ev == pytest.approx(0.10) and r.fair_odds == pytest.approx(1 / 0.55)
    assert r.price_age_min == pytest.approx(30.0) and r.books == 5 and not r.single_book


def test_a_whole_line_that_returns_the_stake() -> None:
    """Asian 0: win 0.40, a draw (0.27) returns the stake. EV = 0.40 * 2.2 - (1 - 0.27); the fair price is (1 - 0.27) / 0.40."""
    r = v.assess(v.Chance(0.40, 0.27, 0.35, 0.45), quote(2.2), at=AT)
    assert r.ev == pytest.approx(0.40 * 2.2 - 0.73) and r.fair_odds == pytest.approx(0.73 / 0.40)
    assert v.expected_value(0.40, 0.27, r.fair_odds or 0) == pytest.approx(0.0)


def test_the_conditional_convention_is_decision_v1s_expected_value() -> None:
    """A probability conditional on settling (``picks.picks``, decision-v1) gives decision-v1's ``ev_of`` exactly."""
    rng = random.Random(5)
    for _ in range(500):
        p, push, odds = rng.uniform(0.05, 0.95), rng.uniform(0, 0.3), rng.uniform(1.05, 8)
        c = v.Chance.conditional(p, push)
        assert v.expected_value(c.win, c.push, odds) == pytest.approx(decision.ev_of(p, odds, push), abs=1e-12)
        assert v.fair_odds(c.win, c.push) == pytest.approx(1 / p)


def _payoff(market: str, selection: str, line: Decimal, home: int, away: int, odds: float) -> float:
    """What one unit returns at a final score, leg by leg (a quarter line is half the stake on each neighbouring line)."""
    if abs(line * 4) % 2 == 1:
        lo, hi = line - Decimal("0.25"), line + Decimal("0.25")
        return 0.5 * _payoff(market, selection, lo, home, away, odds) + 0.5 * _payoff(market, selection, hi, home, away, odds)
    if market == "AH":
        x = Decimal(home - away if selection == "Home" else away - home) + line
    else:
        x = (Decimal(home + away) - line) * (1 if selection == "Over" else -1)
    return odds - 1 if x > 0 else 0.0 if x == 0 else -1.0


@pytest.mark.parametrize(("market", "selection", "line"), [
    ("AH", "Home", Decimal("0")), ("AH", "Home", Decimal("-0.25")), ("AH", "Away", Decimal("0.75")), ("AH", "Home", Decimal("-1")),
    ("OU", "Over", Decimal("2")), ("OU", "Under", Decimal("2.25")), ("OU", "Over", Decimal("2.75")), ("OU", "Under", Decimal("3"))])
def test_lines_that_push_and_quarter_lines_settle_to_the_expected_value_of_their_win_and_push(market: str, selection: str,
                                                                                              line: Decimal) -> None:
    """The (win, push) of the score matrix (IA-074, averaged over the two legs of a quarter line) give the expected value of settling every
    score leg by leg: a half won or a half lost included."""
    m = sm.build(sm.Params(1.55, 1.10, -0.05, "dixon_coles"))
    home_line = line if selection == "Home" else -line
    prices = sm.derive(m, ou_lines=[line] if market == "OU" else [Decimal("2.5")], ah_lines=[home_line] if market == "AH" else [Decimal(0)])
    o = prices[(market, selection, line)]
    for odds in (1.7, 1.95, 2.6):
        direct = sum(float(m.p[h, a]) * _payoff(market, selection, line, h, a, odds) for h in range(m.p.shape[0])
                     for a in range(m.p.shape[1]))
        assert v.expected_value(o.win, o.push, odds) == pytest.approx(direct, abs=1e-9)


# -- the interval ---------------------------------------------------------------------------------------------------------------------

def _random(rng: random.Random) -> tuple[v.Chance, v.Quote]:
    push = rng.choice([0.0, 0.0, rng.uniform(0, 0.3)])
    win = rng.uniform(0.02, 1 - push - 0.02)
    lo, hi = max(0.0, win - rng.uniform(0, 0.15)), min(1 - push, win + rng.uniform(0, 0.15))
    return (v.Chance(win, push, lo, hi, rng.random() < 0.8),
            quote(rng.uniform(1.01, 15), rng.choice([None, 1, 2, 3, 4, 9]), timedelta(minutes=rng.uniform(0, 3000))))


def test_property_the_interval_contains_the_point_and_stays_within_what_a_bet_can_do() -> None:
    rng = random.Random(20261117)
    for _ in range(3000):
        c, q = _random(rng)
        r = v.assess(c, q, at=AT)
        assert r.ev is not None and r.ev_low is not None and r.ev_high is not None
        assert r.ev_low <= r.ev <= r.ev_high
        assert -(1 - c.push) - 1e-12 <= r.ev_low and r.ev_high <= (q.odds or 0) - 1 + 1e-12


def test_property_the_expected_value_rises_with_the_price() -> None:
    rng = random.Random(97)
    for _ in range(2000):
        c, q = _random(rng)
        a, b = sorted((rng.uniform(1.01, 15), rng.uniform(1.01, 15)))
        ra, rb = v.assess(c, dataclasses.replace(q, odds=a), at=AT), v.assess(c, dataclasses.replace(q, odds=b), at=AT)
        assert ra.ev is not None and rb.ev is not None and ra.ev <= rb.ev
        assert ra.ev_high is not None and rb.ev_high is not None and ra.ev_high <= rb.ev_high + 1e-12


def test_property_the_interval_widens_with_the_age_of_the_price_and_the_interval_of_the_probability() -> None:
    rng = random.Random(3)
    for _ in range(1000):
        c, q = _random(rng)
        young, old = (v.assess(c, quote(q.odds, q.books, timedelta(minutes=m)), at=AT) for m in sorted((rng.uniform(0, 600),
                                                                                                         rng.uniform(0, 600))))
        assert young.ev_low is not None and old.ev_low is not None and young.ev_high is not None and old.ev_high is not None
        assert old.ev_low <= young.ev_low + 1e-12 and old.ev_high >= young.ev_high - 1e-12
        narrow = v.assess(dataclasses.replace(c, low=c.win, high=c.win), q, at=AT)
        wide = v.assess(c, q, at=AT)
        assert narrow.ev_low is not None and wide.ev_low is not None and wide.ev_low <= narrow.ev_low + 1e-12


def test_a_ninety_per_cent_interval_of_the_probability_is_read_at_its_level() -> None:
    """The models' 90 % interval of 0.05 each side is a standard error of 0.05 / 1.645; the expected value's interval is at 95 %."""
    r = v.assess(v.Chance(0.55, 0.0, 0.50, 0.60), quote(2.0, age=timedelta(0)), at=AT)
    assert r.ev_low == pytest.approx(0.10 - 1.96 * 2.0 * 0.05 / 1.6448536, rel=1e-6)
    r95 = v.assess(v.Chance(0.55, 0.0, 0.50, 0.60, level=0.95), quote(2.0, age=timedelta(0)), at=AT)
    assert r95.ev_low == pytest.approx(0.10 - 2.0 * 0.05, abs=1e-5)  # 1.96 is z(0.975) to four places
    assert v.PROBABILITY_LEVEL == 0.9


def test_a_fresh_price_and_an_exact_probability_give_a_point() -> None:
    r = v.assess(v.Chance(0.55, 0.0, 0.55, 0.55), quote(2.0, age=timedelta(0)), at=AT)
    assert r.ev_low == pytest.approx(r.ev) and r.ev_high == pytest.approx(r.ev) and r.price_sd == 0.0


def test_the_price_drift_is_the_measured_envelope() -> None:
    assert v.price_sd(0) == 0.0 and v.price_sd(60) == pytest.approx(v.PRICE_DRIFT_PER_SQRT_HOUR)
    assert v.price_sd(177) == pytest.approx(0.0243 * (177 / 60) ** 0.5)  # 2.95 h: the band it was measured from (rms 0.042)
    assert v.price_sd(10_000) == v.PRICE_DRIFT_CAP
    ages = [0, 5, 45, 75, 195, 600, 3000]
    assert [v.price_sd(a) for a in ages] == sorted(v.price_sd(a) for a in ages)


def test_an_interval_of_a_raw_number_is_carried_to_its_calibrated_number_by_width() -> None:
    assert v.transported(0.50, 0.56, 0.51, 0.61) == pytest.approx((0.45, 0.55))
    assert v.transported(0.98, 0.90, 0.80, 0.97) == pytest.approx((0.88, 1.0))
    assert v.transported(0.5, 0.5, None, 0.6) == (None, None)


# -- the verdict ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("books", [None, 0, 1, 2])
def test_una_sola_casa_never_confirms_however_large_the_value(books: int | None) -> None:
    r = v.assess(v.Chance(0.80, 0.0, 0.79, 0.81), quote(3.0, books), at=AT)
    assert r.ev_low is not None and r.ev_low > 1.0
    assert r.single_book and not r.confirms and r.verdict == v.SINGLE_BOOK
    assert v.assess(v.Chance(0.80, 0.0, 0.79, 0.81), quote(3.0, 3), at=AT).confirms


def test_property_no_range_of_odds_the_verdict_reads_the_interval_the_books_the_seal_and_the_age_only() -> None:
    """The same verdict whatever the size of the price: confirmed exactly when it has books, a calibrated number and an interval above zero."""
    rng = random.Random(11)
    for _ in range(3000):
        c, q = _random(rng)
        r = v.assess(c, q, at=AT)
        assert r.ev_low is not None
        want = (v.SINGLE_BOOK if q.books is None or q.books < 3 else v.UNCALIBRATED if not c.calibrated
                else v.NOT_POSITIVE if r.ev_low <= 0 else v.CONFIRMED)
        assert r.verdict == want
    long_shot = v.assess(v.Chance(0.25, 0.0, 0.24, 0.26), quote(6.0), at=AT)
    favourite = v.assess(v.Chance(0.75, 0.0, 0.74, 0.76), quote(1.6), at=AT)
    assert long_shot.confirms and favourite.confirms


def test_a_price_after_the_moment_is_a_leak_and_nothing_is_computed_from_it() -> None:
    r = v.assess(v.Chance(0.6, 0.0, 0.55, 0.65), v.Quote(2.0, 6, AT + timedelta(seconds=1)), at=AT)
    assert r.verdict == v.FUTURE_PRICE and r.ev is None and r.ev_low is None and not r.confirms


@pytest.mark.parametrize(("chance", "q", "verdict"), [
    (v.Chance(0.6), quote(2.0), v.NO_INTERVAL),
    (v.Chance(0.6, 0.0, 0.55, 0.65), quote(2.0, age=None), v.NO_AGE),
    (v.Chance(0.6, 0.0, 0.55, 0.65), quote(None), v.NO_PRICE),
    (v.Chance(0.6, 0.0, 0.55, 0.65), quote(1.0), v.NO_PRICE),
    (None, quote(2.0), v.NO_PROBABILITY),
    (v.Chance(0.6, 0.0, 0.55, 0.65, calibrated=False), quote(2.0), v.UNCALIBRATED),
    (v.Chance(0.5, 0.0, 0.40, 0.60), quote(2.1), v.NOT_POSITIVE)])
def test_each_verdict_and_its_words(chance: v.Chance | None, q: v.Quote, verdict: str) -> None:
    r = v.assess(chance, q, at=AT)
    assert r.verdict == verdict and not r.confirms and r.why == v.WHY[verdict]
    assert r.as_json()["verdict"] == verdict and r.as_json()["version"] == "value-v2"


def test_a_chance_that_is_not_a_probability_is_refused() -> None:
    for win, push in ((1.2, 0.0), (-0.1, 0.0), (0.8, 0.3), (float("nan"), 0.0)):
        with pytest.raises(ValueError):
            v.Chance(win, push)


def test_the_books_rule_is_decision_v1s_imported() -> None:
    assert v.MIN_BOOKS_TO_CONFIRM == decision.MIN_BOOKS == 3


# -- decision-v2 carries it, and no stage reads it ------------------------------------------------------------------------------------

def test_decision_v2_carries_value_v2_from_the_number_and_the_price_it_judged() -> None:
    w, p = world(), pick(width=0.06)
    d = engine.decide(w, core({MODEL: p}))
    r = d.value_v2
    assert r is not None and r.verdict == v.CONFIRMED and r.calibrated and r.books == 6 and r.price_age_min == pytest.approx(20.0)
    assert r.ev == pytest.approx(d.value.ev_cal or 0) and r.fair_odds == pytest.approx(1 / 0.56)
    assert r.interval_basis == "own"  # identity calibrator: the calibrated number is the model's
    js = d.as_json()["value_v2"]
    assert js["ev_low"] < js["ev"] < js["ev_high"] and js["single_book"] is False


def test_decision_v2_says_single_book_and_never_confirms_it() -> None:
    d = engine.decide(world(), core({MODEL: pick(books=2)}))
    assert d.state != "RECOMMENDED" and d.value_v2 is not None and d.value_v2.single_book and not d.value_v2.confirms


def test_on_two_thousand_decisions_no_stage_reads_value_v2_and_none_is_confirmed_with_a_single_book(monkeypatch: pytest.MonkeyPatch) -> None:
    worlds = [build_case(c) for c in cases(2000, seed=97)]
    before = [engine.decide(w, core({MODEL: p})) for w, p in worlds]
    absurd = v.ValueReading(v.CONFIRMED, 99.0, 98.0, 100.0, 1.01, 9.0, 0.99, 0.0, 0.0, 0.0, 1, True, "own", "consensus")
    monkeypatch.setattr(engine, "value_reading", lambda *a, **k: absurd)
    after = [engine.decide(w, core({MODEL: p})) for w, p in worlds]
    for x, y in zip(before, after, strict=True):
        assert (x.state, x.reason, x.codes, x.label, x.verdicts, x.value) == (y.state, y.reason, y.codes, y.label, y.verdicts, y.value)
    readings = [d.value_v2 for d in before]
    assert all(r is not None for r in readings)
    priced = [r for r in readings if r is not None and r.odds is not None]
    assert priced and all(r.ev_low is not None for r in priced if r.verdict not in (v.NO_INTERVAL,))
    assert not [r for r in readings if r is not None and r.confirms and r.single_book]
    assert not [d for d in before if d.state == "RECOMMENDED" and d.value_v2 is not None and d.value_v2.single_book]


def test_the_common_number_is_unconditional_and_the_own_number_conditional() -> None:
    at = AT
    pred: dict[str, Any] = {"model": MODEL, "model_version_id": 1, "p_model": 0.40, "p_push": 0.27, "interval": (0.35, 0.45),
                            "p_cal": 0.40, "calibrator_id": 1, "calibrator_role": "CHAMPION"}
    price = engine.Price(2.2, 0.38, 6, at - timedelta(minutes=10), 10.0)
    own = engine.value_reading(at, engine.Prediction(**pred), price)
    common = engine.value_reading(at, engine.Prediction(**pred, source=engine.COMMON), price)
    assert own.ev == pytest.approx(decision.ev_of(0.40, 2.2, 0.27))  # (1 - push)(p * odds - 1)
    assert common.ev == pytest.approx(0.40 * 2.2 - 0.73)  # p * odds - (1 - push): the figure's p already excludes the push
    assert common.ev is not None and own.ev is not None and common.ev - own.ev == pytest.approx(0.27 * 0.40 * 2.2)


def test_the_replay_reports_value_v2() -> None:
    w, p = world(), pick(width=0.06)
    d = engine.decide(w, core({MODEL: p}))
    single = engine.decide(w, core({MODEL: pick(books=2)}))
    out = replay.value_summary([({}, "core", d), ({}, "core", single), ({}, "core", None)])
    assert out["decisions"] == 2 and out["with_interval"] == 2 and out["interval_rate"] == 1.0
    assert out["confirmed"] == 1 and out["single_book"] == 1 and out["confirmed_single_book"] == 0
    assert out["ev_gap_vs_stages"]["over_1e-6"] == 0
