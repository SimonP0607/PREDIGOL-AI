"""The parlay engine: every leg passes the value gate, no two legs share a match or a team,
and when there are not enough such legs the answer is "no valid parlay" - never padding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.parlays import engine
from fbi.parlays.engine import Candidate, GateConfig, Leg, Reject

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
D = Decimal


def cand(i: int, *, fixture: int | None = None, home: int | None = None, away: int | None = None,
         hours: float = 5, qualified: bool = True, model_status: str = "champion", status: str = "scheduled",
         p_model: str = "0.55", p_push: str | None = None, p_fair: str | None = "0.50", price: str | None = "2.10",
         price_age_min: float = 20, books: int | None = 6, market: str = "1X2", selection: str = "Home",
         line: str = "0") -> Candidate:
    fid = fixture if fixture is not None else 1000 + i
    return Candidate(
        pick_id=i, fixture_id=fid, kickoff_at=NOW + timedelta(hours=hours), fixture_status=status,
        home_team_id=home if home is not None else 10 * fid, away_team_id=away if away is not None else 10 * fid + 1,
        market_key=market, selection=selection, line=D(line), qualified=qualified, model_status=model_status,
        p_model=D(p_model), p_push=D(p_push) if p_push is not None else None,
        p_market_fair=D(p_fair) if p_fair is not None else None, price=D(price) if price is not None else None,
        price_at=NOW - timedelta(minutes=price_age_min) if price is not None else None, n_bookmakers=books,
    )


def build_daily(cands: list[Candidate], cfg: GateConfig | None = None) -> engine.Parlay:
    s = engine.DAILY
    return engine.build("daily", cands, now=NOW, window=s.window, min_legs=s.min_legs, max_legs=s.max_legs, cfg=cfg)


def test_five_valid_independent_selections_make_the_daily_parlay() -> None:
    p = build_daily([cand(i, hours=2 + i) for i in range(1, 6)])
    assert p.status == "ok" and len(p.legs) == 5
    assert p.independence == "distinct_fixtures_and_teams"
    # combined odds are the product of the prices; the joint probability the product of p_win
    assert p.combined_odds == (D("2.10") ** 5).quantize(D("0.01"))
    assert p.probability_all_win == (D("0.55") ** 5).quantize(D("0.000001"))
    # EV of the parlay = product of (1 + leg EV) - 1, each leg EV = 0.55 * 2.10 - 1 = 0.155
    assert p.expected_value == ((D("1.155") ** 5) - 1).quantize(D("0.0001"))
    assert p.risk == "very_high"
    assert p.prices_as_of == NOW - timedelta(minutes=20)
    assert [leg.candidate.kickoff_at for leg in p.legs] == sorted(leg.candidate.kickoff_at for leg in p.legs)


def test_insufficient_qualified_picks_give_no_parlay_and_say_why() -> None:
    cands = [cand(i) for i in range(1, 4)] + [cand(i, qualified=False) for i in range(4, 7)]
    p = build_daily(cands)
    assert p.status == "no_valid_parlay" and p.legs == ()
    assert p.combined_odds is None and p.probability_all_win is None and p.expected_value is None
    assert p.eligible_legs == 3 and p.required_legs == 5
    assert p.rejections["not_qualified"] == 3


def test_a_parlay_is_never_padded_with_legs_that_fail() -> None:
    good = [cand(i) for i in range(1, 5)]
    bad = cand(9, price="1.70")  # 0.55 * 1.70 - 1 < 0
    p = build_daily([*good, bad])
    assert p.status == "no_valid_parlay"
    assert p.rejections == {"non_positive_ev": 1}


def test_a_stale_price_is_rejected() -> None:
    assert engine.assess(cand(1, price_age_min=4 * 60), NOW, GateConfig()) is Reject.STALE_PRICE
    assert isinstance(engine.assess(cand(1, price_age_min=2 * 60), NOW, GateConfig()), Leg)


def test_negative_or_zero_ev_is_rejected() -> None:
    assert engine.assess(cand(1, price="1.70"), NOW, GateConfig()) is Reject.NON_POSITIVE_EV
    # exactly break-even is not value either
    assert engine.assess(cand(1, p_model="0.50", price="2.00"), NOW, GateConfig()) is Reject.NON_POSITIVE_EV


def test_the_same_fixture_twice_is_rejected_by_the_correlation_guard() -> None:
    cands = [cand(i) for i in range(1, 5)] + [cand(5, fixture=1001, market="OU", selection="Over", line="2.5")]
    p = build_daily(cands)
    assert p.status == "no_valid_parlay"
    assert p.rejections.get("same_fixture") == 1


def test_a_team_cannot_appear_in_two_legs() -> None:
    cands = [cand(i) for i in range(1, 5)] + [cand(5, fixture=2005, home=10 * 1001)]  # 10010 plays in fixture 1001
    p = build_daily(cands)
    assert p.status == "no_valid_parlay" and p.rejections.get("shared_team") == 1


def test_one_leg_per_selection_keeps_the_best_price() -> None:
    a = cand(1, price="2.10")
    b = cand(2, fixture=1001, price="2.30")  # same fixture, market, selection, line: another pick of it
    legs, rejections = engine.gate([a, b], NOW, GateConfig())
    assert len(legs) == 1 and legs[0].candidate.pick_id == 2 and rejections["duplicate_selection"] == 1


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"qualified": False}, Reject.NOT_QUALIFIED),
    ({"model_status": "retired"}, Reject.MODEL_RETIRED),
    ({"status": "live"}, Reject.NOT_SCHEDULED),
    ({"hours": 0.1}, Reject.TOO_CLOSE_TO_KICKOFF),
    ({"price": None}, Reject.NO_PRICE),
    ({"p_fair": None}, Reject.NO_CONSENSUS),
    ({"books": 1}, Reject.FEW_BOOKMAKERS),
    ({"price": "2.80", "p_fair": "0.50"}, Reject.PRICE_OUTLIER),  # 40% above fair: one book's error
])
def test_every_gate_names_the_rule_that_failed(kwargs: dict[str, object], reason: Reject) -> None:
    assert engine.assess(cand(1, **kwargs), NOW, GateConfig()) is reason  # type: ignore[arg-type]


def test_the_shadow_preview_is_the_only_way_an_unqualified_pick_passes() -> None:
    assert engine.assess(cand(1, qualified=False), NOW, GateConfig()) is Reject.NOT_QUALIFIED
    assert isinstance(engine.assess(cand(1, qualified=False), NOW, GateConfig(allow_unqualified=True)), Leg)


def test_a_push_is_neither_a_win_nor_a_loss() -> None:
    # Asian Handicap -1.0: P(win | settled) 0.60, P(push) 0.20 -> P(win) 0.48, P(lose) 0.32
    ev, p_win = engine.expected_value(D("0.60"), D("0.20"), D("2.00"))
    assert p_win == D("0.4800") and ev == D("0.48") * 1 - D("0.32")
    leg = engine.assess(cand(1, p_model="0.60", p_push="0.20", price="2.00", market="AH", line="-1"), NOW,
                        GateConfig())
    assert isinstance(leg, Leg) and leg.p_win == D("0.48") and leg.ev == D("0.16")


def test_the_multiday_parlay_takes_six_or_seven_legs_in_two_days() -> None:
    s = engine.MULTIDAY
    seven = [cand(i, hours=3 * i) for i in range(1, 8)]
    p = engine.build("multiday", seven, now=NOW, window=s.window, min_legs=s.min_legs, max_legs=s.max_legs)
    assert p.status == "ok" and len(p.legs) == 7
    six = [cand(i, hours=3 * i) for i in range(1, 7)] + [cand(9, hours=60)]  # 60 h is outside the 48 h window
    p6 = engine.build("multiday", six, now=NOW, window=s.window, min_legs=s.min_legs, max_legs=s.max_legs)
    assert p6.status == "ok" and len(p6.legs) == 6 and p6.rejections["outside_window"] == 1
    five = [cand(i, hours=3 * i) for i in range(1, 6)]
    p5 = engine.build("multiday", five, now=NOW, window=s.window, min_legs=s.min_legs, max_legs=s.max_legs)
    assert p5.status == "no_valid_parlay"


def test_legs_are_chosen_by_value_not_by_order() -> None:
    cands = [cand(i, price="2.05") for i in range(1, 6)] + [cand(6, price="2.40")]
    p = build_daily(cands)
    assert p.status == "ok" and 6 in {leg.candidate.pick_id for leg in p.legs}


def test_dependent_legs_are_never_multiplied() -> None:
    a, b = cand(1), cand(2, fixture=1001, market="OU", selection="Over", line="2.5")
    legs = [engine.assess(a, NOW, GateConfig()), engine.assess(b, NOW, GateConfig())]
    assert all(isinstance(x, Leg) for x in legs)
    _, joint, _ = engine.combine([x for x in legs if isinstance(x, Leg)])
    assert joint is None


@pytest.mark.parametrize(("p", "risk"), [("0.35", "moderate"), ("0.30", "moderate"), ("0.12", "high"),
                                         ("0.05", "very_high")])
def test_risk_follows_the_probability_of_winning_every_leg(p: str, risk: str) -> None:
    assert engine.risk_of(D(p)) == risk


def test_min_and_max_legs_must_make_sense() -> None:
    with pytest.raises(ValueError):
        engine.build("daily", [], now=NOW, window=timedelta(hours=1), min_legs=3, max_legs=2)
