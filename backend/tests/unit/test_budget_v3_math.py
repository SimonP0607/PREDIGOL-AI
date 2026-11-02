"""The arithmetic of the adaptive budget v3 (Plan Maestro IA, section 26), without a database: the reserve, the day's weight
and allocation, the month's projection, the states, the LAB's yielding, the cooldown of a spent limit and the alert thresholds."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from fbi.ai.budget_v3 import (
    crossed,
    daily_allocation,
    day_weight,
    lab_allocation,
    limit_cooldown,
    locked_reserve,
    project_month,
    state_of,
)

D = Decimal


def test_the_reserve_is_kept_until_the_last_five_days_and_then_spent() -> None:
    assert locked_reserve(remaining=D(100), reserve=D(10), days_left=20) == 10
    assert locked_reserve(remaining=D(100), reserve=D(10), days_left=6) == 10
    assert locked_reserve(remaining=D(100), reserve=D(10), days_left=5) == 0, "released in the last five days"
    assert locked_reserve(remaining=D(10), reserve=D(10), days_left=20) == 0, "all that is left IS the reserve: production's"
    assert locked_reserve(remaining=D("10.01"), reserve=D(10), days_left=20) == 10


def test_a_days_weight_is_its_load_against_the_average_between_half_and_the_factor() -> None:
    f = D(2)
    assert day_weight(load_today=10, loads_rest=30, days_left=4, factor=f) == pytest.approx(1.0)
    assert day_weight(load_today=20, loads_rest=30, days_left=4, factor=f) == pytest.approx(1.6), "a Saturday gets more"
    assert day_weight(load_today=40, loads_rest=30, days_left=4, factor=f) == 2.0, "never more than the factor"
    assert day_weight(load_today=1, loads_rest=60, days_left=4, factor=f) == 0.5, "a quiet day keeps half the average"
    assert day_weight(load_today=0, loads_rest=0, days_left=4, factor=f) == 1.0, "nothing known: the average"
    assert day_weight(load_today=5, loads_rest=5, days_left=0, factor=f) == 1.0


def test_the_days_allocation_is_the_average_times_its_weight_within_the_ceiling_and_what_is_left() -> None:
    assert daily_allocation(available=D(100), days_left=10, weight=1.6, ceiling=D(20)) == D("16.0000")
    assert daily_allocation(available=D(100), days_left=10, weight=1.6, ceiling=D(12)) == D("12.0000"), "the soft target's ceiling"
    assert daily_allocation(available=D(5), days_left=1, weight=2.0, ceiling=D(20)) == D("5.0000"), "never more than what is left"
    assert daily_allocation(available=D(0), days_left=10, weight=1.0, ceiling=D(20)) == 0
    assert daily_allocation(available=D(100), days_left=0, weight=1.0, ceiling=D(20)) == 0


def test_the_projection_adds_what_today_has_left_and_the_days_after_at_the_unit_cost() -> None:
    # 0.50 a match; today 10 matches (5.00 expected, 2.00 spent: 3.00 to go); two more days of 10 and 20 matches (15.00)
    assert project_month(spent_month=D(40), spent_today=D(2), unit_cost=D("0.5"), load_today=10.0, loads_after=[10.0, 20.0],
                         run_rate=D(4)) == D(58)
    # today already spent more than expected: nothing more is added for today
    assert project_month(spent_month=D(40), spent_today=D(9), unit_cost=D("0.5"), load_today=10.0, loads_after=[10.0],
                         run_rate=D(4)) == D(45)
    # no unit cost to measure: the days after spend at the run rate
    assert project_month(spent_month=D(40), spent_today=D(1), unit_cost=None, load_today=10.0,
                         loads_after=[1.0, 1.0, 1.0], run_rate=D(4)) == D(55)
    assert project_month(spent_month=D(0), spent_today=D(0), unit_cost=None, load_today=0.0, loads_after=[],
                         run_rate=D(0)) == 0, "a month with nothing to measure projects what it has spent"


STATE_ARGS = {"monthly": D(185), "spent_month": D(80), "spent_today": D(2), "daily": D(6), "cap": D(9),
              "projected": D(120), "limit_active": False}


def state(**kw: object) -> tuple[str, tuple[str, ...]]:
    return state_of(**(STATE_ARGS | kw))  # type: ignore[arg-type]


def test_the_state_follows_the_projection_not_a_fixed_share_of_the_day() -> None:
    assert state() == ("NORMAL", ())
    assert state(projected=D("175.75")) == ("NORMAL", ()), "exactly 95 % is still normal"
    assert state(projected=D("175.76")) == ("AJUSTE", ("projection_over_95",))
    assert state(projected=D(185)) == ("AJUSTE", ("projection_over_95",)), "exactly 100 % is still AJUSTE"
    assert state(projected=D("185.01")) == ("REDUCED", ("projection_over_100",))


def test_the_old_routes_ladder_of_the_day_stays_until_it_is_retired() -> None:
    assert state(spent_today=D("5.99")) == ("NORMAL", ())
    assert state(spent_today=D(6)) == ("REDUCED", ("day_allocation",))
    assert state(spent_today=D("7.49")) == ("REDUCED", ("day_allocation",))
    assert state(spent_today=D("7.5")) == ("CHEAP_ONLY", ("day_allocation_125",))
    assert state(spent_today=D(6), projected=D(190)) == ("REDUCED", ("day_allocation", "projection_over_100")), \
        "every reason is told"


def test_the_layer_stops_when_the_month_the_day_or_the_provider_says_so() -> None:
    assert state(monthly=D(0)) == ("EXHAUSTED", ("no_envelope",))
    assert state(spent_month=D(185)) == ("EXHAUSTED", ("month_spent",))
    assert state(limit_active=True) == ("EXHAUSTED", ("api_limit",))
    assert state(spent_today=D(9)) == ("EXHAUSTED", ("day_cap",))
    assert state(daily=D(0), cap=D(0), spent_today=D(0)) == ("EXHAUSTED", ("day_cap",))
    assert state(spent_month=D(190), limit_active=True)[1] == ("month_spent",), "the month is told first"


def test_production_goes_first_and_the_lab_gets_what_the_joint_ceiling_leaves() -> None:
    assert lab_allocation(envelope=D(55), joint_ceiling=D(190), projected_production=D(150)) == 40
    assert lab_allocation(envelope=D(55), joint_ceiling=D(190), projected_production=D(120)) == 55, "its own envelope"
    assert lab_allocation(envelope=D(15), joint_ceiling=D(190), projected_production=D(185)) == 5
    assert lab_allocation(envelope=D(55), joint_ceiling=D(190), projected_production=D(195)) == 0, "a heavy month: no LAB"


def test_a_spent_limit_is_left_alone_for_longer_each_time_and_never_for_more_than_six_hours() -> None:
    minutes = [limit_cooldown(n) / timedelta(minutes=1) for n in range(0, 10)]
    assert minutes == [0, 30, 60, 120, 240, 360, 360, 360, 360, 360]


def test_the_alert_thresholds_a_figure_has_reached() -> None:
    assert crossed(D(90), D(185)) == []
    assert crossed(D(93), D(185)) == [50]
    assert crossed(D("92.5"), D(185)) == [50], "92.5 is exactly 50 %"
    assert crossed(D("92.49"), D(185)) == []
    assert crossed(D(130), D(185)) == [50, 70]
    assert crossed(D(185), D(185)) == [50, 70, 85, 95, 100]
    assert crossed(D(200), D(0)) == [], "no envelope, no alert"
    assert crossed(D(176), D(185), (95, 100)) == [95], "the projection alerts at 95 and 100"
