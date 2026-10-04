"""The pure rules of the day's records: stages, pessimistic growth, parlay outcomes, periods."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fbi.parlays.persist import quarter_line
from fbi.picks.daily import product_day, single_elg, stage_of
from fbi.picks.product_settlement import parlay_outcome
from fbi.userdata.records import period_bounds, valid_selection

D = Decimal


def test_stages_are_the_tightest_reached() -> None:
    assert stage_of(1500) is None
    assert stage_of(1440) == "T-24h"
    assert stage_of(700) == "T-12h"
    assert stage_of(300) == "T-6h"
    assert stage_of(100) == "T-3h"


def test_the_product_day_is_bogotas() -> None:
    assert str(product_day(datetime(2032, 8, 2, 3, 30, tzinfo=UTC))) == "2032-08-01", "22:30 in Bogota"


def test_pessimistic_growth_punishes_uncertainty() -> None:
    firm = single_elg(D("2.30"), D("0.45"), None)
    loose = single_elg(D("2.30"), D("0.30"), None)
    assert firm > 0 > loose


def test_a_parlay_is_lost_on_the_first_lost_leg_and_won_only_when_all_are_in() -> None:
    assert parlay_outcome([("LOSS", D("2")), ("PENDING", D("2"))]) == ("LOST", D(-1))
    assert parlay_outcome([("WIN", D("2")), ("PENDING", D("2"))]) is None
    assert parlay_outcome([("WIN", D("2")), ("WIN", D("1.5"))]) == ("WON", D("2.0000"))
    assert parlay_outcome([("WIN", D("2")), ("VOID", D("1.5"))]) == ("PARTIAL_VOID", D("1.0000"))
    assert parlay_outcome([("PUSH", D("2")), ("VOID", D("1.5"))]) == ("VOID", D(0))


def test_quarter_lines_and_selections() -> None:
    assert quarter_line(D("-0.25")) and quarter_line(D("2.75")) and not quarter_line(D("2.5"))
    assert valid_selection("1X2", "Home", D(0)) and not valid_selection("1X2", "home", D(0))
    assert valid_selection("OU", "Over", D("2.5")) and not valid_selection("BTTS", "Maybe", D(0))


def test_history_periods_end_at_the_users_midnight() -> None:
    at = datetime(2032, 8, 2, 3, 30, tzinfo=UTC)  # 22:30 on 1 Aug in Bogota
    since, until = period_bounds("today", at=at, tz="America/Bogota")
    assert (since.isoformat(), until.isoformat()) == ("2032-08-01T00:00:00-05:00", "2032-08-02T00:00:00-05:00")
    since7, _ = period_bounds("7d", at=at, tz="America/Bogota")
    assert since7.isoformat() == "2032-07-26T00:00:00-05:00"
