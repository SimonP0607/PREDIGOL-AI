"""``voi-v1`` (``fbi.budgeting``): the depth is monotone in value and D0 without it, the money never goes above budget v3's caps, budget v3's
states are hard rails on the depth, and the pure parts of the replay are total and deterministic."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import router
from fbi.ai.usage import PASS_SHARE, Budget
from fbi.budgeting import allocation, replay, tiers
from fbi.budgeting.allocation import Candidate, allocate, corrected_weights, max_tier
from fbi.budgeting.tiers import RANK, VoiInputs, depth

D = Decimal

BASE = VoiInputs(ev=D("0.06"), stake_units=D("1"), p_publish=D("0.6"), interval_width=D("0.08"), hours_to_kickoff=D("5"),
                 open_contradictions=0)
STATES = ("NORMAL", "AJUSTE", "REDUCED", "CHEAP_ONLY", "EXHAUSTED")


def budget(state: str = "NORMAL", *, spent: str = "0", daily: str = "6", cap: str = "9") -> Budget:
    return Budget(state, D(spent), D("40") + D(spent), D(daily), D("185"), D(cap))  # type: ignore[arg-type]


def rand_inputs(rng: random.Random) -> VoiInputs:
    return VoiInputs(ev=None if rng.random() < 0.1 else D(str(round(rng.uniform(-0.2, 0.4), 4))),
                     stake_units=D(str(rng.choice([0, 0.25, 0.5, 0.75, 1.0]))), p_publish=D(str(round(rng.random(), 2))),
                     interval_width=None if rng.random() < 0.2 else D(str(round(rng.uniform(0, 0.3), 3))),
                     hours_to_kickoff=D(str(round(rng.uniform(0, 72), 2))), open_contradictions=rng.randint(0, 4),
                     material_contradiction=rng.random() < 0.2, highlighted=rng.random() < 0.1)


# ── tiers ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_no_value_is_d0_and_no_ai() -> None:
    for ev in (None, D(0), D("-0.05")):
        d = depth(replace(BASE, ev=ev, stake_units=D("1.5"), p_publish=D(1), open_contradictions=2, material_contradiction=True,
                          highlighted=True))
        assert (d.tier, d.reason, d.score) == ("D0", "no_value", D(0))
    assert depth(replace(BASE, p_publish=D(0))).tier == "D0"
    assert depth(replace(BASE, hours_to_kickoff=D("0.2"))).reason == "too_late"  # 12 minutes: router-v1's 20 are not left


def test_the_tiers_of_the_architecture() -> None:
    assert depth(replace(BASE, ev=D("0.01"), p_publish=D("0.1"))).tier == "D1"          # marginal
    assert depth(BASE).tier == "D2"                                                    # publishable
    assert depth(replace(BASE, material_contradiction=True)).tier == "D3"              # material contradiction
    assert depth(replace(BASE, highlighted=True)).reason == "highlighted"
    assert depth(replace(BASE, ev=D("0.15"), p_publish=D("0.9"))).tier == "D3"        # by its score alone
    assert depth(replace(BASE, ev=D("0.01"), p_publish=D("0.1"), material_contradiction=True)).tier == "D1"  # D3 needs a D2's score


@pytest.mark.parametrize("field,more", [("ev", D("0.01")), ("stake_units", D("0.25")), ("p_publish", D("0.05")),
                                        ("interval_width", D("0.02")), ("open_contradictions", 1)])
def test_the_depth_is_monotone_in_value(field: str, more: Any) -> None:
    rng = random.Random(f"voi-{field}")
    for _ in range(400):
        x = rand_inputs(rng)
        if field == "ev" and x.ev is None:
            continue
        current = getattr(x, field)
        bigger = replace(x, **{field: (D(0) if current is None else current) + more})
        if field == "p_publish":
            bigger = replace(bigger, p_publish=min(D(1), bigger.p_publish))
        assert tiers.score(bigger) >= tiers.score(x)
        assert RANK[depth(bigger).tier] >= RANK[depth(x).tier], (x, bigger)
    for flag in ("material_contradiction", "highlighted"):
        for _ in range(200):
            off: dict[str, Any] = {flag: False}
            on: dict[str, Any] = {flag: True}
            x = replace(rand_inputs(rng), **off)
            assert RANK[depth(replace(x, **on)).tier] >= RANK[depth(x).tier]


def test_publish_proxy_and_inputs() -> None:
    assert tiers.publish_proxy(ev=None, edge=None, ev_low=None) == 0
    assert tiers.publish_proxy(ev=D("0.01"), edge=D("0.05"), ev_low=None) == tiers.P_MARGINAL
    assert tiers.publish_proxy(ev=D("0.05"), edge=D("0.005"), ev_low=None) == tiers.P_MARGINAL
    assert tiers.publish_proxy(ev=D("0.05"), edge=D("0.03"), ev_low=D("0.0")) == tiers.P_CLEAR
    assert tiers.publish_proxy(ev=D("0.05"), edge=D("0.03"), ev_low=D("0.03")) == tiers.P_ROBUST
    assert tiers.expected_value(D("0.5"), D("2.2")) == D("0.10")
    assert tiers.expected_value(D("0.5"), None) is None
    assert tiers.potential_stake(D("0.52"), D("2.2")) == D("1.0")  # quarter Kelly is 3 u, the approval's cap is 1
    assert tiers.interval_width(D("0.5"), D("0.45")) == D("0.10")
    assert tiers.interval_width(D("0.5"), D("0.45"), D("0.58")) == D("0.13")
    assert tiers.interval_width(D("0.5"), None) is None
    assert tiers.PARAMS["late_minutes"] == str(router.PARAMS["research_min_minutes"])


# ── allocation ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rails_follow_the_router() -> None:
    assert [max_tier(s) for s in STATES] == ["D3", "D3", "D2", "D1", "D0"]


@pytest.mark.parametrize("state", STATES)
def test_never_above_budget_v3s_caps(state: str) -> None:
    rng = random.Random(f"caps-{state}")
    for _ in range(300):
        daily = D(str(round(rng.uniform(0, 12), 4)))
        cap = min(D(str(round(rng.uniform(0, 20), 4))), daily * D("1.5"))
        spent = D(str(round(rng.uniform(0, 14), 4)))
        b = budget(state, spent=str(spent), daily=str(daily), cap=str(cap))
        cands = [Candidate(f"k{i}", rand_inputs(rng)) for i in range(rng.randint(0, 25))]
        learned = {"D1": D("0.01"), "D2": D("0.05")} if rng.random() < 0.3 else None
        for checkpoint in PASS_SHARE:
            a = allocate(cands, b, checkpoint=checkpoint, learned_cost=learned)
            hard = max(D(0), min(daily, cap) - spent)
            assert a.limit_usd <= hard
            assert a.allocated_usd + a.reserve_escalations_usd + a.reserve_later_usd <= a.limit_usd
            assert a.allocated_usd + a.reserve_escalations_usd <= max(D(0), min(daily * PASS_SHARE[checkpoint], cap) - spent)
            assert all(s.budget_usd >= 0 for s in a.shares)
            assert all(RANK[s.tier] <= RANK[a.max_tier] for s in a.shares)
            assert all(s.budget_usd == 0 for s in a.shares if s.tier == "D0")
            if state == "EXHAUSTED":
                assert a.allocated_usd == a.limit_usd == 0


def test_the_share_of_a_day() -> None:
    cands = [Candidate("a", replace(BASE, material_contradiction=True)), Candidate("b", BASE),
             Candidate("c", replace(BASE, ev=D("0.01"), p_publish=D("0.1"))), Candidate("d", replace(BASE, ev=None))]
    fillers = [Candidate(f"z{i}", replace(BASE, ev=D("0.01"), p_publish=D("0.1"))) for i in range(30)]
    a = allocate(cands + fillers, budget(), checkpoint="pre")
    assert a.limit_usd == D(6)
    assert a.pass_room_usd == D(6) * PASS_SHARE["pre"]                     # the line-ups keep the rest
    assert a.reserve_later_usd == D(6) - a.pass_room_usd
    assert a.reserve_escalations_usd == a.pass_room_usd * allocation.escalation_share("production")
    tiers_ = {s.key: s.tier for s in a.shares if not s.key.startswith("z")}
    assert tiers_ == {"a": "D3", "b": "D2", "c": "D1", "d": "D0"}
    money = {s.key: s.budget_usd for s in a.shares}
    assert money["a"] > money["b"] > money["c"] > money["d"] == 0
    assert money["a"] == a.distributable_usd * 6 / 40 == money["b"] * 2 == money["c"] * 6   # weights 6 + 3 + 31 x 1
    alone = allocate(cands[:1], budget(), checkpoint="pre")
    assert alone.shares[0].budget_usd == alone.distributable_usd * allocation.MAX_SELECTION_SHARE   # never the whole checkpoint
    assert alone.shares[0].capped_by == "selection_share"
    final = allocate(cands, budget(), checkpoint="final")
    assert final.reserve_later_usd == 0 and final.pass_room_usd == D(6)


def test_the_rails_lower_the_depth_and_say_so() -> None:
    cands = [Candidate("a", replace(BASE, material_contradiction=True))]
    reduced = allocate(cands, budget("REDUCED"))
    assert (reduced.shares[0].natural.tier, reduced.shares[0].tier, reduced.shares[0].capped_by) == ("D3", "D2", "rail")
    assert reduced.reserve_escalations_usd == 0                            # no top model in REDUCED: no reserve for it
    assert allocate(cands, budget("CHEAP_ONLY")).shares[0].tier == "D1"
    assert allocate(cands, budget("EXHAUSTED")).shares[0].budget_usd == 0


def test_a_learned_cost_bounds_a_selection() -> None:
    a = allocate([Candidate("b", BASE)], budget(), learned_cost={"D2": D("0.02")})
    assert a.shares[0].budget_usd == D("0.03") and a.shares[0].capped_by == "learned_cost"


def test_corrected_weights() -> None:
    assert corrected_weights({}) == allocation.TIER_WEIGHT
    assert corrected_weights({"D2": D("0.5")}) == allocation.TIER_WEIGHT     # one measure: nothing to compare
    w = corrected_weights({"D1": D("0.10"), "D2": D("0.40"), "D3": D("0.40"), "D0": D("9")})
    assert w["D0"] == 0
    assert w["D1"] == D(1) * allocation.LEARN_CLAMP                            # cheap useful signals: twice the weight, at most
    assert w["D2"] == D(3) and w["D3"] == D(6)
    w = corrected_weights({"D1": D("0.01"), "D2": D("1"), "D3": D("1")})
    assert list(w.values()) == sorted(w.values())                               # never above a deeper depth's weight


# ── replay, the pure parts ────────────────────────────────────────────────────────────────────────────────────────


AT = datetime(2031, 3, 10, 14, tzinfo=UTC)


def match_run(**over: Any) -> replay.MatchRun:
    values: dict[str, Any] = {"id": 1, "fixture_id": 7, "run_kind": "shadow", "pass_kind": "pre", "known_at": AT,
                              "labels": {"c1": "7:1X2:Home:0.00", "c2": "7:OU:Over:2.50"},
                              "contradictions": ({"code": "C06", "candidates": ["c1"]}, {"code": "C04", "candidates": ["c1", "c2"]})}
    return replay.MatchRun(**(values | over))


def test_selection_keys_and_contradictions() -> None:
    assert replay.selection_key(7, "OU", "Over", "2.5") == replay.selection_key(7, "OU", "Over", D("2.50")) == "7:OU:Over:2.50"
    m = match_run()
    assert replay.contradictions_of(m, "7:1X2:Home:0.00") == (2, True)
    assert replay.contradictions_of(m, "7:OU:Over:2.50") == (1, False)
    assert replay.contradictions_of(None, "x") == (0, False)
    assert replay.is_material({"code": "C01", "confirmed": True}) and not replay.is_material({"code": "C01"})
    later = match_run(id=2, known_at=AT + timedelta(hours=1))
    assert replay.newest_before([m, later], AT + timedelta(minutes=30)) is m
    assert replay.newest_before([m, later], AT - timedelta(minutes=1)) is None


def test_split_runs() -> None:
    m = match_run()
    passes = {(7, "shadow", "pre", AT): m}
    runs = [{"fixture_id": 7, "run_kind": "shadow", "pass_kind": "pre", "known_at": AT, "candidates": ["c1"], "cost_usd": D("0.05")},
            {"fixture_id": 7, "run_kind": "shadow", "pass_kind": "pre", "known_at": AT, "candidates": [], "cost_usd": D("0.04")},
            {"fixture_id": 7, "run_kind": "shadow", "pass_kind": "first", "known_at": AT, "candidates": ["c1"], "cost_usd": D("0.01")},
            {"fixture_id": 7, "run_kind": "shadow", "pass_kind": "pre", "known_at": AT, "candidates": ["c9"], "cost_usd": D("0.02")}]
    spend, count, lost, lost_n = replay.split_runs(runs, passes)
    assert spend == {"7:1X2:Home:0.00": D("0.07"), "7:OU:Over:2.50": D("0.02")}
    assert count == {"7:1X2:Home:0.00": 2, "7:OU:Over:2.50": 1}
    assert (lost, lost_n) == (D("0.03"), 2)
    assert replay.split_runs(list(reversed(runs)), passes) == (spend, count, lost, lost_n)


def test_build_inputs_is_deterministic() -> None:
    row = {"fixture_id": 7, "market_key": "1X2", "selection": "Home", "line": D(0), "odds": D("2.2"), "p_model": D("0.52"),
           "p_low": D("0.47"), "edge": D("0.05"), "ev": None, "reviewed_at": AT, "kickoff_at": AT + timedelta(hours=5)}
    s = replay.build_inputs(row, moment=AT, run=match_run())
    assert s == replay.build_inputs(dict(row), moment=AT, run=match_run())
    x = s.inputs
    assert (x.ev, x.stake_units, x.p_publish, x.interval_width, x.hours_to_kickoff) == (
        D("0.144"), D("1.0"), tiers.P_ROBUST, D("0.10"), D(5))
    assert (x.open_contradictions, x.material_contradiction) == (2, True)
    assert depth(x).tier == "D3"
