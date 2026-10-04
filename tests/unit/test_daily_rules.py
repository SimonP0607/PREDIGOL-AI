"""The pure rules of the day's records: stages, pessimistic growth, parlay outcomes, periods."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fbi.parlays.engine import Candidate, Leg
from fbi.parlays.persist import SPECS, choose, quarter_line
from fbi.picks.daily import Ranked, passing, product_day, single_elg, stage_of
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


def _ranked(n: int, kickoff: datetime, p_low: str = "0.45", price: str = "2.30") -> Ranked:
    c = Candidate(pick_id=n, fixture_id=n, kickoff_at=kickoff, fixture_status="scheduled", home_team_id=100 + 2 * n,
                  away_team_id=101 + 2 * n, market_key="1X2", selection="Home", line=D(0), qualified=True,
                  model_status="active", p_model=D("0.50"), p_push=None, p_market_fair=D("0.43"), price=D(price),
                  price_at=kickoff - timedelta(hours=1), n_bookmakers=5)
    leg = Leg(candidate=c, p_win=D("0.50"), p_push=D(0), ev=D("0.15"), probability_edge=D("0.07"))
    return Ranked(leg, {}, D(p_low), single_elg(D(price), D(p_low), None))


def test_a_multiday_parlay_takes_a_leg_from_another_day_when_it_must() -> None:
    today = datetime(2032, 8, 1, 15, tzinfo=UTC)
    pool = [_ranked(1, today, "0.48"), _ranked(2, today + timedelta(hours=1), "0.48"),
            _ranked(3, today + timedelta(hours=2), "0.48"), _ranked(4, today + timedelta(days=1), "0.45")]
    legs = choose(pool, SPECS["multiday"])
    assert legs is not None
    days = {product_day(x.leg.candidate.kickoff_at) for x in legs}
    assert len(days) == 2 and 4 in {x.leg.candidate.fixture_id for x in legs}
    assert choose(pool[:3], SPECS["multiday"]) is None, "one day only: no multi-day parlay"


def test_a_probability_without_an_interval_is_not_ranked() -> None:
    at = datetime(2032, 8, 1, 15, tzinfo=UTC)
    row = {"pick_id": 1, "fixture_id": 1, "kickoff_at": at + timedelta(hours=5), "fixture_status": "scheduled",
           "home_team_id": 10, "away_team_id": 11, "market_key": "AH", "selection": "Away", "line": D("0.5"),
           "pick_status": "qualified", "model_status": "active", "p_model": D("0.58"), "p_push": None,
           "p_fair": D("0.19"), "best_odds": D("4.50"), "price_at": at - timedelta(minutes=20), "n_bookmakers": 3,
           "p_low": None}
    assert passing([row], at=at, source="qualified") == [], "no low end to rank by: not ranked as if certain"
    measured = passing([{**row, "fixture_id": 2, "p_low": D("0.40")}], at=at, source="qualified")
    assert [x.p_low for x in measured] == [D("0.40")]


def test_a_stored_lower_bound_is_already_on_the_conditional_footing() -> None:
    """The pick stores its bounds as it stores its probability - conditional on the bet
    settling (fbi.picks.engine) - so the bound is used as stored, never converted twice."""
    at = datetime(2032, 8, 1, 15, tzinfo=UTC)
    row = {"pick_id": 1, "fixture_id": 1, "kickoff_at": at + timedelta(hours=5), "fixture_status": "scheduled",
           "home_team_id": 10, "away_team_id": 11, "market_key": "AH", "selection": "Home", "line": D("-1"),
           "pick_status": "qualified", "model_status": "active", "p_model": D("0.60"), "p_push": D("0.20"),
           "p_fair": D("0.50"), "best_odds": D("2.10"), "price_at": at - timedelta(minutes=20), "n_bookmakers": 3,
           "p_low": D("0.50")}
    (x,) = passing([row], at=at, source="qualified")
    assert x.p_low == D("0.50")
    (y,) = passing([row | {"p_low": D("0.6000004")}], at=at, source="qualified")
    assert y.p_low == D("0.60"), "a bound is never above its own point"
