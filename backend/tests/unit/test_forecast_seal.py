"""AD-B03 (IA-073): the calibration seal is stable - it changes only when its cause does (``seal-v1``).

The test of repetition of the plan: passes of the pipeline every 15 minutes over two days, the consensus captured once a day at 16:30 UTC
as production captures it; the seal of each pass is computed with ``forecast-v1``'s rule (a price of six hours or less) and with
``seal-v1``'s (a price within the forecast's horizon), and set against the cause it is owed to (the champion in force and whether there is
a price at all). ``forecast-v1`` changes its seal without a change of cause; ``seal-v1`` never does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.forecasting import market_view as mv
from fbi.forecasting import seal
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.predictions.forecast import HORIZON

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
CUT = T0 - timedelta(hours=1)
CHAMPION = Calibrator("1X2", "elo_ologit", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5}, 652, "CHAMPION")
WITH_CHAMPION = CalibrationState({("1X2", "elo_ologit"): CHAMPION}, {}, {("1X2", "elo_ologit"): {"logloss_cal": 0.58}}, {})
NO_CHAMPION = CalibrationState({}, {}, {}, {})


def rows(p: tuple[float, float, float] = (0.78, 0.13, 0.09)) -> dict[str, list[mv.Row]]:
    return {"elo_ologit": [mv.Row(s, mv.Source("elo_ologit", 7, CUT, "h", x, None, None, 0.0))
                           for s, x in zip(("Home", "Draw", "Away"), p, strict=True)]}


def price(as_of: datetime) -> dict[str, tuple[float, datetime]]:
    return {"Home": (0.58, as_of), "Draw": (0.24, as_of), "Away": (0.18, as_of)}


def forecast(cal: CalibrationState, market: dict[str, tuple[float, datetime]], *, version: str = mv.VERSION) -> mv.MarketForecast:
    f = mv.forecast_market(170072, "1X2", Decimal(0), rows(), cal, market, version=version)
    assert f is not None
    return f


def test_the_window_is_the_forecast_horizon() -> None:
    assert seal.STABLE_MARKET_AGE == HORIZON
    assert seal.STABLE_MARKET_AGE > mv.MAX_MARKET_AGE


def test_the_switch_is_shadow_unless_it_says_off() -> None:
    assert seal.mode({}) == "shadow"
    assert seal.mode({seal.SWITCH: " OFF "}) == "off"
    assert seal.mode({seal.SWITCH: "on"}) == "shadow", "an unknown value is the default, never something new"


def test_the_seal_says_calibrada_only_with_a_champion_and_a_price() -> None:
    at = T0
    calibrated = seal.seal_of(forecast(WITH_CHAMPION, price(at - timedelta(hours=20))))
    assert (calibrated.label, calibrated.basis, calibrated.calibrator_id) == (seal.CALIBRADA, mv.BASIS_CHAMPION, 652)
    assert calibrated.price_age(at) == timedelta(hours=20)
    assert calibrated.reason == "calibrador campeón vigente"
    no_price = seal.seal_of(forecast(WITH_CHAMPION, {}))
    assert (no_price.label, no_price.basis, no_price.price_as_of) == (seal.SIN_CALIBRAR, mv.BASIS_NEEDS_PRICE, None)
    nobody = seal.seal_of(forecast(NO_CHAMPION, price(at)))
    assert (nobody.label, nobody.basis) == (seal.SIN_CALIBRAR, mv.BASIS_NO_CHAMPION)
    assert seal.label_of(mv.CALIBRATED) == seal.CALIBRADA and seal.label_of(mv.UNCALIBRATED) == seal.SIN_CALIBRAR


def test_every_reason_is_told_in_words() -> None:
    assert set(seal.REASONS) == {mv.BASIS_CHAMPION, mv.BASIS_NO_CHAMPION, mv.BASIS_NEEDS_PRICE, mv.BASIS_NOT_APPLICABLE}


def test_the_labels_are_the_contracts() -> None:
    from typing import get_args

    from fbi.api.contracts.intelligence.vocab import CalibrationSeal

    assert set(get_args(CalibrationSeal)) == {seal.CALIBRADA, seal.SIN_CALIBRAR}


def test_the_version_is_part_of_the_fingerprint_and_forecast_v1_is_unchanged() -> None:
    market = price(T0 - timedelta(hours=1))
    default = mv.forecast_market(170072, "1X2", Decimal(0), rows(), WITH_CHAMPION, market)
    explicit = forecast(WITH_CHAMPION, market, version=mv.VERSION)
    shadow = forecast(WITH_CHAMPION, market, version=seal.SHADOW_VERSION)
    assert default == explicit, "forecast-v1 computes exactly what it computed before"
    assert shadow.input_hash != explicit.input_hash and shadow.outcomes == explicit.outcomes


# -- the test of repetition ------------------------------------------------------------------------------------------------------------------

CAPTURES = [T0 - timedelta(hours=19, minutes=30) + timedelta(days=d) for d in range(3)]  # 16:30 UTC each day, as production


def newest(at: datetime, window: timedelta) -> datetime | None:
    seen = [c for c in CAPTURES if at - window < c <= at]
    return max(seen) if seen else None


def readings(window: timedelta, cal: CalibrationState) -> list[seal.Reading]:
    out = []
    at = T0
    while at < T0 + timedelta(hours=48):
        captured = newest(at, window)
        f = forecast(cal, {} if captured is None else price(captured))
        champion = None if not cal.champions else CHAMPION.id
        cause = (champion, newest(at, seal.STABLE_MARKET_AGE) is not None)  # the state of the world, not the seal
        out.append(seal.Reading(at, seal.seal_of(f).label, cause))
        at += timedelta(minutes=15)
    return out


def test_forecast_v1_changes_its_seal_without_a_change_of_cause() -> None:
    v1 = readings(mv.MAX_MARKET_AGE, WITH_CHAMPION)
    assert seal.unexplained(v1) >= 3, "six hours after each capture it goes UNCALIBRATED, and back at the next one"


def test_seal_v1_never_changes_without_a_change_of_cause() -> None:
    stable = readings(seal.STABLE_MARKET_AGE, WITH_CHAMPION)
    assert seal.changes(stable) == [] and seal.unexplained(stable) == 0
    assert {r.label for r in stable} == {seal.CALIBRADA}


def test_a_seal_change_with_its_cause_is_explained() -> None:
    at = T0
    history = [seal.Reading(at, seal.SIN_CALIBRAR, (652, False)), seal.Reading(at + timedelta(minutes=15), seal.CALIBRADA, (652, True)),
               seal.Reading(at + timedelta(minutes=30), seal.CALIBRADA, (653, True)),
               seal.Reading(at + timedelta(minutes=45), seal.SIN_CALIBRAR, (None, True))]
    found = seal.changes(list(reversed(history)))  # the order given does not matter: time does
    assert [(c.before, c.after, c.cause_changed) for c in found] == [(seal.SIN_CALIBRAR, seal.CALIBRADA, True),
                                                                     (seal.CALIBRADA, seal.SIN_CALIBRAR, True)]
    assert seal.unexplained(history) == 0


@pytest.mark.parametrize("cal", [NO_CHAMPION, WITH_CHAMPION])
def test_without_any_price_the_seal_never_moves(cal: CalibrationState) -> None:
    f = [seal.seal_of(forecast(cal, {})).label for _ in range(3)]
    assert f == [seal.SIN_CALIBRAR] * 3
