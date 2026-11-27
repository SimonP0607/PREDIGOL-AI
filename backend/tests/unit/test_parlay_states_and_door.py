"""RP-11.2 and RP-11.3: the six states of a leg in the joint, the dependence marks of the pairs and the door of the experimental parlays
(``fbi.parlays.settlement_states`` and ``fbi.parlays.door``). Cases checked by hand."""

from __future__ import annotations

import pytest

from fbi.api.contracts.intelligence.console import ParlayDoor
from fbi.parlays import door as pd
from fbi.parlays import settlement_states as ss
from fbi.parlays.correlation import Estimate


def leg(fixture: int, price: float, **states: float) -> ss.LegStates:
    return ss.LegStates(fixture, price, states)


def test_a_half_win_a_push_and_a_void_have_their_own_payout() -> None:
    a = leg(1, 2.0, win=0.4, half_win=0.2, push=0.1, half_loss=0.1, loss=0.2)
    assert [a.factor(s) for s in ("win", "half_win", "push", "void", "half_loss", "loss")] == [2.0, 1.5, 1.0, 1.0, 0.5, 0.0]


def test_two_legs_by_hand() -> None:
    a = leg(1, 2.0, win=0.5, loss=0.5)
    b = leg(2, 1.9, win=0.4, half_win=0.1, push=0.1, half_loss=0.1, loss=0.3)
    d = ss.distribution([a, b])
    assert ss.check(d)
    assert d.p_loss == pytest.approx(1 - 0.5 * 0.7)  # a loses, or b loses
    assert d.p_full_win == pytest.approx(0.5 * 0.4)
    assert d.p_profit == pytest.approx(0.5 * (0.4 + 0.1 + 0.1))  # a wins and b wins, half wins or pushes (a half loss returns just the stake)
    assert d.expected_return == pytest.approx(1.0 * 1.055)
    assert dict(d.outcomes)[0.0] == pytest.approx(0.65)
    assert dict(d.outcomes)[1.9 * 2.0] == pytest.approx(0.2)
    assert dict(d.outcomes)[2.0 * 1.45] == pytest.approx(0.05)


def test_a_void_leg_lets_the_parlay_go_on_and_all_void_returns_the_stake() -> None:
    d = ss.distribution([leg(1, 2.0, void=1.0), leg(2, 3.0, win=0.5, loss=0.5)])
    assert dict(d.outcomes) == {0.0: pytest.approx(0.5), 3.0: pytest.approx(0.5)}
    assert dict(ss.distribution([leg(1, 2.0, void=1.0), leg(2, 3.0, push=1.0)]).outcomes) == {1.0: pytest.approx(1.0)}


def test_a_leg_whose_states_do_not_add_up_to_one_is_refused() -> None:
    with pytest.raises(ss.StatesError, match="add up to one"):
        leg(1, 2.0, win=0.5, loss=0.4)
    with pytest.raises(ss.StatesError, match="unknown"):
        leg(1, 2.0, win=0.5, draw=0.5)
    with pytest.raises(ss.StatesError, match="above 1"):
        leg(1, 1.0, win=1.0)


def test_the_rules_of_the_parlays_are_not_relaxed_here() -> None:
    a, b, c, e = (leg(i, 2.0, win=0.5, loss=0.5) for i in (1, 2, 3, 4))
    with pytest.raises(ss.StatesError, match="same match"):
        ss.distribution([a, leg(1, 1.8, win=0.5, loss=0.5)])
    with pytest.raises(ss.StatesError, match="1 to 3"):
        ss.distribution([a, b, c, e])
    assert ss.check(ss.distribution([a, b, c]))


def test_every_distribution_adds_up_to_one_over_many_shapes() -> None:
    shapes = [{"win": 1.0}, {"win": 0.3, "half_win": 0.2, "push": 0.1, "void": 0.05, "half_loss": 0.15, "loss": 0.2}, {"loss": 1.0},
              {"half_win": 0.5, "half_loss": 0.5}]
    for i, x in enumerate(shapes):
        for y in shapes:
            for z in shapes:
                assert ss.check(ss.distribution([leg(1, 1.7, **x), leg(2, 2.2, **y), leg(3, 3.1, **z)])), (i, x, y, z)


def est(rho: float, se: float, groups: int = 60) -> Estimate:
    return Estimate("over_2_5", rho, se, groups, groups * 4)


def test_the_marks_of_the_pairs_come_from_the_measured_correlation() -> None:
    same = (7, "2026-11-20")
    legs = [ss.LegStates(1, 2.0, {"win": 0.5, "loss": 0.5}, "over_2_5", same), ss.LegStates(2, 2.0, {"win": 0.5, "loss": 0.5}, "over_2_5", same),
            ss.LegStates(3, 2.0, {"win": 0.5, "loss": 0.5}, "over_2_5", (9, "2026-11-20"))]
    by_pair = {(p.first, p.second): p for p in ss.pairs(legs, {"over_2_5": est(0.2, 0.05)})}
    assert by_pair[(0, 1)].mark == "dependiente_positiva" and by_pair[(0, 2)].mark == "independiente" and by_pair[(1, 2)].mark == "independiente"
    assert ss.pairs(legs, {"over_2_5": est(-0.2, 0.05)})[0].mark == "dependiente_negativa"
    assert ss.pairs(legs, {"over_2_5": est(0.05, 0.05)})[0].mark == "independiente", "the interval contains zero"
    assert ss.pairs(legs, {"over_2_5": est(0.2, 0.05, groups=10)})[0].mark == "sin_medida", "too few days measured"
    assert ss.pairs(legs, {})[0].mark == "sin_medida"


def test_a_mark_never_changes_the_joint() -> None:
    legs = [leg(1, 2.0, win=0.5, loss=0.5), leg(2, 2.0, win=0.5, loss=0.5)]
    assert ss.distribution(legs).p_full_win == pytest.approx(0.25)


# ── the door ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_combination_of_four_legs_or_with_two_of_a_match_is_always_refused() -> None:
    assert pd.refuse([1, 2, 3, 4]) is not None and pd.refuse([1, 2, 2]) is not None
    assert pd.refuse([1, 2, 3]) is None and pd.refuse([]) is None


def good(**over: object) -> pd.Door:
    args: dict[str, object] = {"combinations": [[1, 2], [3, 4, 5]], "pick_door_ready": True, "reliability": pd.Reliability(1800, True),
                               "prospective": pd.Prospective(120, 30, 20.0, 40.0)}
    return pd.evaluate(**(args | over))  # type: ignore[arg-type]


def test_with_everything_met_the_door_is_ready_for_the_owner_and_still_cannot_publish() -> None:
    d = good()
    assert d.ready and d.first_open == "owner_authorization" and d.can_publish is False
    assert [c.state for c in d.conditions][:-1] == ["cumplida"] * 5 and d.conditions[-1].state == "solo_dueno"


def test_today_nothing_is_decided() -> None:
    d = pd.evaluate(combinations=[], pick_door_ready=False, reliability=None, prospective=pd.Prospective(13, 3, 2.0, 6.0))
    assert {c.key: c.state for c in d.conditions} == {"max_three_legs": "no_evaluada", "distinct_fixtures": "no_evaluada", "legs_pass_pick_door": "no_cumplida",
                                                        "historical_reliability": "no_evaluada", "prospective_reliability": "pendiente",
                                                        "owner_authorization": "solo_dueno"}
    assert d.ready is False and d.first_open == "max_three_legs"


def test_a_parlay_with_a_repeated_match_or_four_legs_breaks_the_structure() -> None:
    assert {c.key: c.state for c in good(combinations=[[1, 2, 2]]).conditions}["distinct_fixtures"] == "no_cumplida"
    assert {c.key: c.state for c in good(combinations=[[1, 2, 3, 4]]).conditions}["max_three_legs"] == "no_cumplida"
    assert good(combinations=[[1, 2, 3, 4]]).ready is False


def test_the_thresholds_of_the_plan_are_kept() -> None:
    assert pd.MIN_COMBINATIONS == 1500 and pd.MIN_SETTLED == 100 and pd.MAX_LEGS == 3
    assert {c.key: c.state for c in good(reliability=pd.Reliability(1499, True)).conditions}["historical_reliability"] == "pendiente"
    assert {c.key: c.state for c in good(reliability=pd.Reliability(1500, False)).conditions}["historical_reliability"] == "no_cumplida"
    assert {c.key: c.state for c in good(reliability=pd.Reliability(1500, None)).conditions}["historical_reliability"] == "no_evaluada"
    assert {c.key: c.state for c in good(prospective=pd.Prospective(99, 30, 20.0, 40.0)).conditions}["prospective_reliability"] == "pendiente"
    assert {c.key: c.state for c in good(prospective=pd.Prospective(100, 45, 20.0, 40.0)).conditions}["prospective_reliability"] == "no_cumplida"
    assert {c.key: c.state for c in good(prospective=pd.Prospective(100, 30, None, None)).conditions}["prospective_reliability"] == "no_evaluada"


def test_the_json_and_the_contract_agree_and_the_contract_refuses_a_false_ready() -> None:
    doc = good().as_json()
    contract = ParlayDoor.model_validate(doc)
    assert contract.can_publish is False and contract.conditions[-1].state == "solo_dueno"
    broken = {**doc, "conditions": [dict(c) for c in doc["conditions"]]}
    broken["conditions"][0]["state"] = "no_cumplida"
    with pytest.raises(ValueError, match="ready means"):
        ParlayDoor.model_validate(broken)
    swapped = {**doc, "ready": False, "conditions": [dict(c) for c in doc["conditions"]]}
    swapped["conditions"][-1]["state"] = "cumplida"
    with pytest.raises(ValueError, match="owner"):
        ParlayDoor.model_validate(swapped)
