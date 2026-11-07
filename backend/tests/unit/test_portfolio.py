"""portfolio-v1 (``fbi.portfolio``, IA-013, shadow) on plain values: correlations and their sources, the exposure limits and the
order they bind in, stakes that never exceed stake-v1 and never go to a selection that is not RECOMMENDED, the day set, the
parlays of RECOMMENDED legs, and a day with nothing recommended."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from scripts import ia_portfolio as cli

from fbi.intel import day_priority, decision
from fbi.intel import stake as staking
from fbi.parlays import correlation as icc
from fbi.portfolio import build, correlation, exposure, stakes
from fbi.portfolio.selection import Selection

AT = datetime(2033, 3, 15, 15, tzinfo=UTC)  # 10:00 Bogotá
DAY = date(2033, 3, 15)
_ids = itertools.count(1)


def sel(**kw: Any) -> Selection:
    n = next(_ids)
    base: dict[str, Any] = {
        "decision_id": n, "fixture_id": 1000 + n, "kickoff_at": AT + timedelta(hours=4), "known_at": AT - timedelta(minutes=10),
        "competition_id": 500 + n, "provider_league_id": 90000 + n, "home_team_id": 2 * n + 10_000,
        "away_team_id": 2 * n + 10_001, "market_key": "1X2", "selection": "Home", "line": Decimal(0), "odds": 2.05,
        "p_cal": 0.60, "p_push": 0.0, "p_low": 0.55, "p_high": 0.65, "p_market": 0.48, "n_bookmakers": 4,
        "price_at": AT - timedelta(minutes=15), "score": 70.0, "premium": False, "parlay_eligible": True,
        "state_v1": "APROBADO", "state_v2": "RECOMMENDED", "reason": "approved", "label": None}
    base.update(kw)
    return Selection(**base)


def caution(**kw: Any) -> Selection:
    return sel(state_v1="CAUTELA", state_v2="CAUTION", reason="risk", **kw)


def finals(selections: list[Selection], corrs: list[correlation.Correlation] | None = None,
           **kw: Any) -> list[stakes.PortfolioStake]:
    return stakes.allocate(selections, corrs or [], **kw)[0]


# -- correlation -----------------------------------------------------------------------------------------------------

def test_the_shared_factor_rules_and_their_sources() -> None:
    a = sel()
    same_match = sel(fixture_id=a.fixture_id, home_team_id=a.home_team_id, away_team_id=a.away_team_id,
                     competition_id=a.competition_id, market_key="OU", selection="Over", line=Decimal("2.5"))
    same_team = sel(home_team_id=a.away_team_id, kickoff_at=a.kickoff_at + timedelta(hours=6))
    league_window = sel(competition_id=a.competition_id, kickoff_at=a.kickoff_at + timedelta(hours=1))
    league_far = sel(competition_id=a.competition_id, kickoff_at=a.kickoff_at + timedelta(hours=5))
    window = sel(kickoff_at=a.kickoff_at + timedelta(minutes=90))
    apart = sel(kickoff_at=a.kickoff_at + timedelta(hours=5))
    got = {b.decision_id: correlation.estimate(a, b) for b in (same_match, same_team, league_window, league_far, window, apart)}
    assert [(c.source, c.rho) for c in got.values()] == [
        ("same_match", correlation.SAME_MATCH), ("same_team", correlation.SAME_TEAM),
        ("same_league_window", correlation.SAME_LEAGUE_WINDOW), ("same_league", correlation.SAME_LEAGUE),
        ("same_window", correlation.SAME_WINDOW), ("none", 0.0)]
    assert "no joint distribution" in got[same_match.decision_id].factors
    assert [c.budget_rho > 0 for c in got.values()] == [True, True, True, False, False, False], \
        "only from GROUP_MIN up do two selections share a budget"
    assert correlation.estimate(same_match, a) == got[same_match.decision_id], "symmetric, ids ordered"
    assert {c.b for c in correlation.pairs([a, same_match, apart])} == {same_match.decision_id}, "a 'none' pair is not listed"


def matrix() -> list[list[float]]:
    """Independent Poisson(1.5) home, Poisson(1.1) away, 0-7 goals each."""
    import math

    def pois(lam: float, k: int) -> float:
        return math.exp(-lam) * lam**k / math.factorial(k)

    return [[pois(1.5, h) * pois(1.1, a) for a in range(8)] for h in range(8)]


def test_the_joint_distribution_comes_first_for_one_match_and_says_so() -> None:
    a = sel()
    over = sel(fixture_id=a.fixture_id, competition_id=a.competition_id, home_team_id=a.home_team_id,
               away_team_id=a.away_team_id, market_key="OU", selection="Over", line=Decimal("2.5"))
    away = replace(over, decision_id=next(_ids), market_key="1X2", selection="Away", line=Decimal(0))
    joint = correlation.ScoreMatrixJoint({a.fixture_id: matrix()})
    home_over = correlation.estimate(a, over, joint=joint)
    assert home_over.source == "joint_distribution" and 0 < home_over.rho < 1, "a home win and over 2.5 share the goals"
    home_away = correlation.estimate(a, away, joint=joint)
    assert home_away.source == "joint_distribution" and home_away.rho < -0.4 and home_away.budget_rho == 0, \
        "exclusive outcomes: negative, and a negative correlation never scales a stake (up or down)"
    quarter = replace(over, decision_id=next(_ids), line=Decimal("2.25"))
    fallback = correlation.estimate(a, quarter, joint=joint)
    assert fallback.source == "same_match" and "the joint distribution cannot settle the pair" in fallback.factors


def test_a_significant_measured_icc_beats_the_rule_and_a_weak_one_does_not() -> None:
    a = sel(market_key="OU", selection="Over", line=Decimal("2.5"))
    b = sel(market_key="OU", selection="Over", line=Decimal("2.5"), competition_id=a.competition_id,
            kickoff_at=a.kickoff_at + timedelta(minutes=30))
    strong = {"over_2_5": icc.Estimate("over_2_5", 0.20, 0.03, 60, 300)}
    got = correlation.estimate(a, b, measured=strong)
    assert (got.source, got.rho) == ("measured_icc", 0.20)
    under = replace(b, decision_id=next(_ids), selection="Under")
    assert correlation.estimate(a, under, measured=strong).rho == pytest.approx(-0.20), "Over against Under: the polarity"
    weak = {"over_2_5": icc.Estimate("over_2_5", 0.02, 0.05, 60, 300)}
    assert correlation.estimate(a, b, measured=weak).source == "same_league_window"
    few = {"over_2_5": icc.Estimate("over_2_5", 0.30, 0.01, icc.MIN_GROUPS - 1, 100)}
    assert correlation.estimate(a, b, measured=few).source == "same_league_window"


# -- stakes ----------------------------------------------------------------------------------------------------------

def test_a_correlated_pair_is_scaled_down_and_an_unrelated_selection_is_not() -> None:
    a = sel()
    b = sel(fixture_id=a.fixture_id, competition_id=a.competition_id, home_team_id=a.home_team_id,
            away_team_id=a.away_team_id, market_key="OU", selection="Over", line=Decimal("2.5"))
    c = sel(kickoff_at=a.kickoff_at + timedelta(hours=6))
    one = staking.stake_for("APROBADO", 0.60, 2.05)
    assert one.units == staking.CAPS["APROBADO"], "the fixture: each alone is a full approved stake"
    corrs = correlation.pairs([a, b, c])
    got = {p.decision_id: p for p in finals([a, b, c], corrs)}
    factor = 1 / (1 + correlation.SAME_MATCH)
    assert got[a.decision_id].scale == pytest.approx(factor) and got[b.decision_id].scale == pytest.approx(factor)
    assert got[a.decision_id].scaled == exposure.floor_step(one.units * factor) < one.units
    assert got[c.decision_id].scale == 1.0 and got[c.decision_id].final == one.units
    assert "shared budget" in got[a.decision_id].why
    league = sel(competition_id=c.competition_id, kickoff_at=c.kickoff_at + timedelta(minutes=30))
    pair = {p.decision_id: p for p in finals([c, league], correlation.pairs([c, league]))}
    assert pair[c.decision_id].final == exposure.floor_step(one.units / (1 + correlation.SAME_LEAGUE_WINDOW)) == 0.75


def test_the_limits_bind_in_order_and_say_which() -> None:
    m = sel()
    same_match = [m, *(sel(fixture_id=m.fixture_id, competition_id=m.competition_id, home_team_id=m.home_team_id,
                           away_team_id=m.away_team_id, market_key="OU", selection=s, line=Decimal(line))
                       for s, line in (("Over", "2.5"), ("Under", "3.5")))]
    got = finals(same_match)  # no correlation given: the limits alone
    assert [(p.final, p.binding) for p in got] == [(1.0, None), (0.5, "match"), (0.0, "match")]
    t = sel()
    team = [t, sel(home_team_id=t.home_team_id, kickoff_at=t.kickoff_at + timedelta(hours=5)),
            sel(away_team_id=t.home_team_id, kickoff_at=t.kickoff_at + timedelta(hours=7))]
    assert [(p.final, p.binding) for p in finals(team)] == [(1.0, None), (0.5, "team"), (0.0, "team")]
    league = [sel(competition_id=1), sel(competition_id=1), sel(competition_id=1)]
    assert [(p.final, p.binding) for p in finals(league)] == [(1.0, None), (1.0, None), (0.0, "league")]
    family = [sel(market_key="OU", selection="Over", line=Decimal("2.5")) for _ in range(4)]
    assert [(p.final, p.binding) for p in finals(family)] == [(1.0, None)] * 3 + [(0.0, "market_family")]
    day = [sel(market_key=m) for m in ("1X2", "OU", "CORNERS", "CARDS", "YELLOW", "GOALS_HALF")]  # six families
    assert [p.binding for p in finals(day)] == [None] * 5 + ["day"] and sum(p.final for p in finals(day)) == exposure.MAX_DAY
    premium = sel(premium=True, state_v1="PICK_PREMIUM", odds=2.4, p_cal=0.62)
    check = exposure.Book().check(premium, 2.0)
    assert check.binding == "match" and check.room["match"] == check.room["team"] == exposure.MAX_MATCH, \
        "on a tie the first limit of ORDER is the one named"
    assert exposure.ORDER == ("match", "team", "league", "market_family", "day")


def test_the_limits_are_written_in_the_products_own_numbers() -> None:
    assert exposure.MAX_MATCH == exposure.MAX_TEAM == staking.CAPS["PICK_PREMIUM"]
    assert decision.MAX_PER_COMPETITION * staking.CAPS["APROBADO"] == exposure.MAX_LEAGUE
    assert decision.MAX_PICKS * staking.CAPS["APROBADO"] == exposure.MAX_DAY
    assert exposure.family_of("BTTS") == exposure.family_of("OU") == "goals" and exposure.family_of("CORNERS") == "CORNERS"


@pytest.mark.parametrize("state_v1", ["APROBADO", "CANDIDATO_PARLAY", "PICK_DEL_DIA", "PICK_PREMIUM"])
def test_a_stake_never_exceeds_stake_v1(state_v1: str) -> None:
    grid = list(itertools.product((0.31, 0.45, 0.55, 0.62, 0.75, 0.9), (1.3, 1.7, 2.05, 2.6, 3.0), (False, True)))
    pool = [sel(state_v1=state_v1, p_cal=p, odds=o, premium=prem, competition_id=1 + i % 3,
                kickoff_at=AT + timedelta(hours=2 + i % 4)) for i, (p, o, prem) in enumerate(grid)]
    corrs = correlation.pairs(pool)
    for s, p in zip(pool, finals(pool, corrs), strict=True):
        v1 = staking.stake_for("PICK_PREMIUM" if s.premium else s.state_v1, s.p_cal, s.odds, s.p_push)
        assert p.final <= p.scaled <= v1.units <= v1.cap and p.individual == v1, (s, p)
        assert p.final % staking.STEP == 0


def test_never_a_stake_for_a_selection_that_is_not_recommended_unless_hypothetical() -> None:
    others = [caution(), sel(state_v1="INVESTIGACION", state_v2="WATCH", reason="price_stale"),
              sel(state_v1="INVESTIGACION", state_v2="ABSTAIN", reason="not_calibrated"),
              sel(state_v1="RECHAZADO", state_v2="REJECTED", reason="ev_cal_below")]
    assert all(p.final == 0 and p.individual is None and not p.hypothetical for p in finals(others))
    what_if = finals(others, hypothetical=True)
    assert what_if[0].final == staking.CAPS["CAUTELA"] and what_if[0].hypothetical and what_if[0].cap_state == "CAUTELA"
    assert all(p.final == 0 and p.individual is None for p in what_if[1:]), "the what-if lets in CAUTION only"


def test_the_invariant_is_enforced() -> None:
    class Wide(exposure.Book):
        def check(self, s: Selection, units: float) -> exposure.Check:
            return exposure.Check(units, units + 1, {}, None)

    with pytest.raises(stakes.InvariantError):
        stakes.allocate([sel()], [], book=Wide())


# -- the day ---------------------------------------------------------------------------------------------------------

def test_an_empty_day_says_so_and_invents_nothing() -> None:
    for selections in ([], [caution(), sel(state_v1="RECHAZADO", state_v2="REJECTED", reason="data")]):
        doc = build.assemble(selections, day=DAY, at=AT)
        assert doc["message"].startswith("No RECOMMENDED selection") and "None is invented" in doc["message"]
        assert doc["counts"]["recommended"] == 0 and doc["selections"] == [] and doc["day_set"] == []
        assert doc["pick_of_the_day"] is None and doc["parlays"]["built"] == [] and doc["counts"]["total_units"] == 0
        assert doc["shadow"] is True and doc["hypothetical"] is False and doc["mode"] == build.MODE_RECOMMENDED
        assert "No RECOMMENDED" in cli.render(doc)
    hypo = build.assemble([caution(), caution()], day=DAY, at=AT, what_if=True)
    assert hypo["hypothetical"] is True and hypo["message"].startswith("HYPOTHETICAL (what-if)")
    assert hypo["counts"]["recommended"] == 0 and hypo["counts"]["hypothetical"] == 2
    assert all(s["hypothetical"] and s["stake"]["hypothetical"] for s in hypo["selections"])
    assert hypo["parlays"]["built"] == [], "parlays stay RECOMMENDED-only, also in the what-if"
    assert "[HYPOTHETICAL]" in cli.render(hypo)


def test_the_day_set_follows_select_days_rules() -> None:
    top = sel(provider_league_id=140, score=55.0, competition_id=7)  # La Liga: group 1
    top2 = sel(provider_league_id=140, score=54.0, competition_id=7)
    top3 = sel(provider_league_id=140, score=53.0, competition_id=7)  # a third of one competition: out
    rest = [sel(score=90.0 - i) for i in range(4)]
    stale = sel(score=99.0, known_at=AT - decision.DAY_FRESH - timedelta(minutes=1))
    same_match = sel(fixture_id=rest[0].fixture_id, score=89.5, market_key="OU", selection="Over", line=Decimal("2.5"))
    doc = build.assemble([*rest, top, top2, top3, stale, same_match], day=DAY, at=AT)
    ids = [d["decision_id"] for d in doc["day_set"]]
    assert ids == [top.decision_id, top2.decision_id, rest[0].decision_id, rest[1].decision_id, rest[2].decision_id]
    assert len(ids) == decision.MAX_PICKS and doc["pick_of_the_day"]["decision_id"] == top.decision_id
    assert doc["pick_of_the_day"]["priority_group"] == 1 and day_priority.group_of(None) == day_priority.DEFAULT_GROUP
    entry = {s["decision_id"]: s for s in doc["selections"]}
    assert entry[stale.decision_id]["fresh_for_day"] is False and entry[stale.decision_id]["day_rank"] is None
    assert doc["selections"][0]["decision_id"] == top.decision_id, "the stakes take the room in the day's order"


def test_the_what_if_puts_caution_after_the_recommended_and_labels_it() -> None:
    r = sel(score=40.0)
    c = caution(score=95.0)
    doc = build.assemble([c, r], day=DAY, at=AT, what_if=True)
    assert [s["decision_id"] for s in doc["selections"]] == [r.decision_id, c.decision_id]
    assert [s["hypothetical"] for s in doc["selections"]] == [False, True]
    plain = build.assemble([c, r], day=DAY, at=AT)
    assert [s["decision_id"] for s in plain["selections"]] == [r.decision_id] and not plain["hypothetical"]


def test_parlays_of_recommended_legs_through_the_gate_and_the_guard() -> None:
    a, b = sel(), sel(kickoff_at=AT + timedelta(hours=6))
    doc = build.assemble([a, b, caution()], day=DAY, at=AT)
    built = doc["parlays"]["built"]
    assert len(built) == 1 and {leg["decision_id"] for leg in built[0]["legs"]} == {a.decision_id, b.decision_id}
    assert built[0]["stake"]["units"] <= staking.PARLAY_CAP and built[0]["combined_odds"] == pytest.approx(2.05 * 2.05, abs=1e-3)
    assert built[0]["p_all_low"] == pytest.approx(0.55 * 0.55)
    # one competition's matchday, no measured dependence: never combined
    x, y = sel(competition_id=9), sel(competition_id=9, kickoff_at=AT + timedelta(hours=6))
    none = build.assemble([x, y], day=DAY, at=AT)
    assert none["parlays"]["built"] == [] and "grows" in none["parlays"]["reason"]
    measured = {"home_win": icc.Estimate("home_win", -0.01, 0.02, 60, 300)}
    ok = build.assemble([x, y], day=DAY, at=AT, measured=measured)
    assert len(ok["parlays"]["built"]) == 1, "measured (even if not significant): the guard lets them combine"
    stale = sel(price_at=AT - timedelta(hours=4))
    not_eligible = sel(parlay_eligible=False)
    gated = build.assemble([stale, not_eligible, sel()], day=DAY, at=AT)["parlays"]
    assert gated["candidates"] == 2 and gated["rejections"] == {"stale_price": 1} and gated["built"] == []


def test_the_command_parses_its_arguments() -> None:
    assert cli.parse_day("2033-03-15") == DAY
    with pytest.raises(ValueError):
        cli.parse_day("15/03/2033")
    with pytest.raises(ValueError):
        cli.parse_at("2033-03-15T10:00:00")
    assert cli.parse_at("2033-03-15T10:00:00+00:00") == datetime(2033, 3, 15, 10, tzinfo=UTC)
    args = cli.build_parser().parse_args(["day", "--day", "2033-03-15", "--what-if-caution", "--json"])
    assert args.what_if and args.as_json
