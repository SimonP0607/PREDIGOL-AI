"""The automatic parlay builder (REVIEW 11 Oct 2026, point 15): the user's filters only narrow what parlay-v4 chooses
from; the rule itself - gate, liquidity, independence, growth - is the one PrediGol's own parlays use."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.parlays import builder
from fbi.parlays.builder import FilterError, Filters, build, in_filters, total_odds
from fbi.parlays.engine import Candidate, Leg
from fbi.parlays.persist import Spec, choose
from fbi.picks.daily import Ranked, single_elg

D = Decimal
AT = datetime(2032, 8, 1, 15, tzinfo=UTC)


def _ranked(n: int, *, hours: float = 3, market: str = "1X2", selection: str = "Home", line: str = "0",
            price: str = "2.30", p_low: str = "0.47", competition: int = 1, books: int = 5,
            p_high: str | None = "0.55", home: int | None = None, away: int | None = None) -> Ranked:
    kickoff = AT + timedelta(hours=hours)
    c = Candidate(pick_id=n, fixture_id=n, kickoff_at=kickoff, fixture_status="scheduled",
                  home_team_id=home if home is not None else 1000 + 2 * n,
                  away_team_id=away if away is not None else 1001 + 2 * n, market_key=market, selection=selection,
                  line=D(line), qualified=True, model_status="active", p_model=D("0.50"), p_push=None,
                  p_market_fair=D("0.43"), price=D(price), price_at=AT - timedelta(minutes=30), n_bookmakers=books)
    leg = Leg(candidate=c, p_win=D("0.50"), p_push=D(0), ev=D("0.15"), probability_edge=D("0.07"))
    row = {"competition_id": competition, "p_high": None if p_high is None else D(p_high)}
    return Ranked(leg, row, D(p_low), single_elg(D(price), D(p_low), None))


def _pool() -> list[Ranked]:
    return [_ranked(1, competition=1), _ranked(2, competition=2, market="OU", selection="Over", line="2.5"),
            _ranked(3, competition=3, price="1.90", p_low="0.56"), _ranked(4, competition=4, hours=30),
            _ranked(5, competition=5, market="BTTS", selection="Yes", price="2.10", p_low="0.50")]


def test_filters_are_checked_and_canonical() -> None:
    with pytest.raises(FilterError):
        Filters(hours=2)
    with pytest.raises(FilterError):
        Filters(hours=73)
    with pytest.raises(FilterError):
        Filters(min_legs=4, max_legs=3)
    with pytest.raises(FilterError):
        Filters(max_legs=8)
    with pytest.raises(FilterError):
        Filters(markets=("CORNERS",))
    with pytest.raises(FilterError):
        Filters(min_odds=D("3"), max_odds=D("2"))
    with pytest.raises(FilterError):
        Filters(max_total_odds=D("1"))
    a = Filters.of(hours=24, min_legs=2, max_legs=4, markets=["OU", "1X2", "OU"], competitions=[3, 1, 3])
    b = Filters.of(hours=24, min_legs=2, max_legs=4, markets=["1X2", "OU"], competitions=[1, 3])
    assert a == b and repr(a) == repr(b), "the same request is the same filters (and one cache entry)"
    assert a.markets == ("1X2", "OU") and a.competitions == (1, 3)


def test_filters_only_narrow() -> None:
    x = _ranked(1, hours=3, market="OU", selection="Over", line="2.5", price="2.30", competition=7)
    assert in_filters(x, Filters(hours=24), at=AT)
    assert not in_filters(x, Filters(hours=3), at=AT), "kicks off exactly at the window's end: outside"
    assert not in_filters(x, Filters(markets=("1X2",)), at=AT)
    assert in_filters(x, Filters(markets=("1X2", "OU")), at=AT)
    assert not in_filters(x, Filters(competitions=(8,)), at=AT)
    assert in_filters(x, Filters(competitions=(7, 8)), at=AT)
    assert not in_filters(x, Filters(min_odds=D("2.31")), at=AT)
    assert not in_filters(x, Filters(max_odds=D("2.29")), at=AT)
    assert in_filters(x, Filters(min_odds=D("2.30"), max_odds=D("2.30")), at=AT)


def test_without_filters_it_is_parlay_v4s_own_choice() -> None:
    pool = _pool()
    f = Filters(hours=72, min_legs=2, max_legs=5)
    built = build(pool, pool, f, at=AT)
    expected = choose(pool, Spec("custom", 2, 5, 1))
    assert expected is not None and built.reason is None
    assert {x.leg.candidate.pick_id for x in built.legs} == {x.leg.candidate.pick_id for x in expected}
    assert [x.leg.candidate.kickoff_at for x in built.legs] == sorted(x.leg.candidate.kickoff_at for x in built.legs)
    assert built.combined_odds == total_odds(built.legs)
    assert built.p_all_low is not None and 0 < built.p_all_low < 1
    assert built.expected_log_growth is not None and built.expected_log_growth > 0


def test_the_window_and_the_markets_narrow_the_pool() -> None:
    pool = _pool()
    built = build(pool, pool, Filters(hours=24, min_legs=2, max_legs=5, markets=("1X2", "BTTS")), at=AT)
    ids = {x.leg.candidate.pick_id for x in built.legs}
    assert ids <= {1, 3, 5} and 4 not in ids, "the match 30 h away is outside a 24 h window"
    assert built.funnel.passing == 5 and built.funnel.matching == 3


def test_the_total_odds_cap_is_never_crossed() -> None:
    pool = _pool()
    f = Filters(hours=72, min_legs=2, max_legs=5, max_total_odds=D("5"))
    built = build(pool, pool, f, at=AT)
    assert built.reason is None and built.combined_odds is not None and built.combined_odds <= D("5")
    tight = build(pool, pool, Filters(hours=72, min_legs=3, max_legs=5, max_total_odds=D("4")), at=AT)
    assert tight.legs == () and tight.reason == "total_odds_cap", "three legs of 1.90+ cannot stay under 4"


def test_never_padded_and_says_why() -> None:
    pool = _pool()
    assert build([], [], Filters(), at=AT).reason == "no_candidates"
    assert build(pool, pool, Filters(markets=("AH",)), at=AT).reason == "no_match"
    one = build(pool, pool, Filters(hours=72, min_legs=2, max_legs=4, competitions=(1,)), at=AT)
    assert one.legs == () and one.reason == "too_few_legs" and one.funnel.matches == 1
    thin = [_ranked(1, books=2), _ranked(2, books=2), _ranked(3, p_high="0.95")]
    starved = build(thin, thin, Filters(hours=72), at=AT)
    assert starved.reason == "too_few_legs" and starved.funnel.combinable == 0, \
        "two books, or an interval wider than 40 points: not a leg"
    weak = [_ranked(1, p_low="0.30"), _ranked(2, p_low="0.30")]
    assert build(weak, weak, Filters(hours=72), at=AT).reason == "no_growth", "legs that do not grow together"


def test_independence_still_holds() -> None:
    shared_team = [_ranked(1, home=50, competition=1), _ranked(2, away=50, competition=2),
                   _ranked(3, competition=3)]
    built = build(shared_team, shared_team, Filters(hours=72, min_legs=2, max_legs=3), at=AT)
    teams = [t for x in built.legs for t in (x.leg.candidate.home_team_id, x.leg.candidate.away_team_id)]
    assert len(teams) == len(set(teams)), "no team twice"
    same_comp = [_ranked(n, competition=9) for n in range(1, 5)]
    capped = build(same_comp, same_comp, Filters(hours=72, min_legs=2, max_legs=4), at=AT)
    assert len(capped.legs) == 2, "at most two legs of one competition"


def test_the_ai_review_is_honoured() -> None:
    pool = _pool()
    reviewed = pool[1:]
    built = build(pool, reviewed, Filters(hours=72, min_legs=2, max_legs=5), at=AT)
    assert 1 not in {x.leg.candidate.pick_id for x in built.legs}
    assert (built.funnel.passing, built.funnel.reviewed) == (5, 4)


def test_choose_without_a_condition_is_unchanged() -> None:
    pool = _pool()
    plain = choose(pool, Spec("custom", 2, 5, 1))
    hooked = choose(pool, Spec("custom", 2, 5, 1), allow=lambda chosen, x: True)
    assert plain is not None and hooked is not None
    assert [x.leg.candidate.pick_id for x in plain] == [x.leg.candidate.pick_id for x in hooked]
    assert builder.RULE_VERSION == "builder-v1"
