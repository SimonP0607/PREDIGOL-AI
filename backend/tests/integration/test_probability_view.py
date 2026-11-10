"""The common probability view in a real database (plan PICKS, F3, option B): what the Match Center stored at a moment and what decision-v2
would measure against at that same moment are THE SAME NUMBERS - not close, the same - because they come from one function over one reading of
the database; and the view as of an earlier moment does not see what was known later (so a replay of a past decision reads what it read)."""

# ruff: noqa: F811  (pytest fixtures imported from test_match_forecast are used by name as parameters)
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.decision import view as common
from fbi.forecasting.market_reader import view_at
from fbi.intel.calibration import calibration_state
from tests.integration.test_match_forecast import AT, World, world  # noqa: F401

pytestmark = pytest.mark.integration


def stored_p(world: World, fid: int) -> dict[tuple[str, str], Decimal]:
    return {(r["market_key"], r["selection"]): r["p"] for r in world.stored(fid)}


def view_p(db: psycopg.Connection[Any], fid: int, at: Any) -> dict[tuple[str, str], Decimal]:
    found = view_at(db, [fid], at=at, cal=calibration_state(db, at=at))
    return {(m, o.selection): Decimal(str(round(o.p, 6))) for (_, m, _), f in found.items() for o in f.outcomes}


def test_the_stored_forecast_and_the_view_of_the_same_moment_are_the_same_numbers(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles")
    world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(minutes=40))
    world.write(fid)
    seen = stored_p(world, fid)
    assert len(seen) == 7  # 1X2 (3), total goals (2), both teams to score (2): every outcome of every market
    assert view_p(db, fid, AT) == seen


def test_the_view_of_a_stale_price_is_the_models_own_number_and_both_agree_on_that(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(hours=7))
    world.write(fid)
    found = view_at(db, [fid], at=AT, cal=calibration_state(db, at=AT))
    (market,) = found.values()
    assert (market.calibration, market.basis) == ("UNCALIBRATED", "needs_price")
    assert view_p(db, fid, AT) == stored_p(world, fid)


def test_the_view_as_of_an_earlier_moment_does_not_see_what_was_known_later(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",), cutoff=AT - timedelta(hours=30))
    world.predict_all(fid, "dixon_coles", only=("OU",), cutoff=AT - timedelta(hours=1), shift=0.04)
    before = view_p(db, fid, AT - timedelta(hours=10))
    after = view_p(db, fid, AT)
    assert before[("OU", "Over")] == Decimal("0.620000") and after[("OU", "Over")] == Decimal("0.660000")


def test_readings_come_back_keyed_like_a_candidate_with_the_outcomes_decision_v1_never_flagged(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles")
    found = common.read(db, [fid], at=AT, cal=calibration_state(db, at=AT))
    assert {(k[1], k[2]) for k in found} == {("1X2", "Home"), ("1X2", "Draw"), ("1X2", "Away"), ("OU", "Over"), ("OU", "Under"),
                                             ("BTTS", "Yes"), ("BTTS", "No")}
    assert all(k[0] == fid and k[3] == k[3].quantize(Decimal("0.01")) for k in found)


def test_no_matches_no_reading(db: psycopg.Connection[Any]) -> None:
    assert common.read(db, [], at=AT, cal=calibration_state(db, at=AT)) == {}
