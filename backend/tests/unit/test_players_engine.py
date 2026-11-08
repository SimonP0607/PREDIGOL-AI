"""``player-engine-v1`` (IA-017, shadow): the as-of cut, the minutes mixture, the shrinkage, the distributions and the walk-forward."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fbi.families import counts
from fbi.players import availability as av
from fbi.players import backtest as bt
from fbi.players import families as fam
from fbi.players import props
from fbi.players import rates as rt
from fbi.players.history import (
    DOUBTFUL,
    OUT,
    History,
    Match,
    PlayerMatch,
    SheetLine,
    absence_status,
    absences_at,
    available_at,
    position_of,
)

T0 = datetime(2026, 1, 3, 15, 0, tzinfo=UTC)
ZERO = dict.fromkeys(fam.STATS, 0)


def line(pid: int, side: str, *, started: bool = True, minutes: int = 90, position: str = "F", **stats: int | None) -> PlayerMatch:
    return PlayerMatch.make(pid, side, started, minutes, position, ZERO | stats)


def match(fid: int, kickoff: datetime, lines: tuple[PlayerMatch, ...], *, home: int = 1, away: int = 2,
          fetched: datetime | None = None) -> Match:
    return Match(fid, kickoff, 39, home, away, available_at(kickoff, fetched or kickoff + timedelta(hours=3)), lines)


def world(n_rounds: int = 60, seed: int = 7) -> list[Match]:
    """Four teams, fourteen men each (ten regulars, two rotating starters, two subs), weekly matches, Poisson counts."""
    rng = random.Random(seed)
    pos = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F", "M", "F", "D"]
    out: list[Match] = []
    fid = 1
    for r in range(n_rounds):
        ko = T0 + timedelta(days=7 * r)
        pairs = [(1, 2), (3, 4)] if r % 2 == 0 else [(1, 3), (2, 4)]
        for home, away in pairs:
            lines: list[PlayerMatch] = []
            for side, team in (("home", home), ("away", away)):
                for j in range(14):
                    pid = team * 100 + j
                    starter = j < 10 or (j == 10 and rng.random() < 0.7) or (j == 11 and rng.random() < 0.3)
                    played = starter or rng.random() < 0.5
                    minutes = (90 if rng.random() < 0.7 else rng.randint(55, 85)) if starter else (rng.randint(5, 30) if played else 0)
                    scale = minutes / 90.0
                    p = pos[j]
                    goals = int(np.random.default_rng(rng.randint(0, 10**9)).poisson((0.5 if p == "F" else 0.1) * scale))
                    shots = int(np.random.default_rng(rng.randint(0, 10**9)).poisson((2.5 if p == "F" else 0.7) * scale))
                    saves = int(np.random.default_rng(rng.randint(0, 10**9)).poisson(3.0 * scale)) if p == "G" else 0
                    lines.append(PlayerMatch.make(pid, side, starter, minutes, p, ZERO | {"goals": goals, "shots": shots, "shots_on": shots // 2,
                                                                                     "saves": saves, "fouls": None if j == 9 else 1}))
            out.append(match(fid, ko, tuple(lines), home=home, away=away))
            fid += 1
    return out


# ── the as-of cut ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_match_is_known_after_it_ended_and_a_late_reread_does_not_hide_it() -> None:
    ko = T0
    assert available_at(ko, ko + timedelta(hours=1)) == ko + timedelta(hours=3)  # never before the end
    assert available_at(ko, ko + timedelta(hours=5)) == ko + timedelta(hours=5)  # when it was read
    assert available_at(ko, ko + timedelta(days=30)) == ko + timedelta(hours=48)  # a re-read 26 h+ later: it existed by then


def test_the_walk_never_sees_the_match_it_forecasts_nor_one_not_yet_read() -> None:
    first = match(1, T0, (line(10, "home", goals=3), line(20, "away")))
    # read 10 hours after its kick-off, which is after the next match's moment (kick-off - 90 min)
    late = match(2, T0 + timedelta(days=1), (line(10, "home", goals=5), line(20, "away")), fetched=T0 + timedelta(days=1, hours=10))
    third = match(3, T0 + timedelta(days=1, hours=6), (line(10, "home"), line(20, "away")))
    engine = bt.Engine([third, late, first])
    engine.walk(third.kickoff, record_from=T0, train_from=T0)
    assert engine.h.matches == 1  # only the first: the second was not read by the third's moment, the third is the target
    engine.prepare(third.kickoff - bt.LEAD)
    assert [a.fixture_id for a in engine.h.appearances[10]] == [1]
    engine.prepare(late.available_at)
    assert [a.fixture_id for a in engine.h.appearances[10]] == [1, 2]


def test_absences_are_the_newest_answer_by_the_moment() -> None:
    obs = {(5, 10): [(T0, "LISTED", "Missing Fixture"), (T0 + timedelta(hours=5), "CLEARED", "Missing Fixture")],
           (5, 11): [(T0 + timedelta(hours=1), "LISTED", "Questionable")]}
    assert absences_at(obs, 5, [10, 11, 12], T0 + timedelta(minutes=30)) == {10: OUT}
    assert absences_at(obs, 5, [10, 11, 12], T0 + timedelta(hours=2)) == {10: OUT, 11: DOUBTFUL}
    assert absences_at(obs, 5, [10, 11, 12], T0 + timedelta(hours=6)) == {11: DOUBTFUL}  # cleared: recovered
    assert absence_status("Missing Fixture") == OUT and absence_status("Questionable") == DOUBTFUL and absence_status(None) == DOUBTFUL


def test_positions_come_from_the_sheet_then_the_profile() -> None:
    assert position_of("G", "Attacker") == "G"
    assert position_of(None, "Midfielder") == "M"
    assert position_of(None, None) == "?"


# ── shrinkage ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_shrinkage_goes_from_the_prior_to_the_player() -> None:
    assert rt.shrunk_rate([], [], [], 0.3, 6.0) == pytest.approx(0.3)
    few = rt.shrunk_rate([2], [90], [1.0], 0.3, 6.0)
    many = rt.shrunk_rate([2] * 200, [90] * 200, [1.0] * 200, 0.3, 6.0)
    assert 0.3 < few < many < 2.0 and many == pytest.approx(2.0, abs=0.06)
    # minutes count, not appearances: two 45-minute halves are one 90
    assert rt.shrunk_rate([1, 1], [45, 45], [1.0, 1.0], 0.3, 6.0) == pytest.approx(rt.shrunk_rate([2], [90], [1.0], 0.3, 6.0))
    with pytest.raises(ValueError):
        rt.shrunk_rate([1], [], [], 0.3, 6.0)


def test_recency_halves_every_half_life() -> None:
    assert rt.recency_weight(T0 + timedelta(days=180), T0) == pytest.approx(0.5)
    assert rt.recency_weight(T0, T0 + timedelta(days=3)) == 1.0  # never more than now


def test_a_player_with_no_record_gets_his_position_times_his_team() -> None:
    h = History()
    for m in world(10):
        h.add(m, bt.LINES_BY_STAT)
    r = rt.player_rate(h, 99_999, "shots", at=T0 + timedelta(days=80), team_id=1, opponent_id=2, position="F")
    assert r.nineties == 0.0
    assert r.player_per90 == pytest.approx(r.prior_per90)
    assert r.prior_per90 == pytest.approx(r.position_per90 * r.team_factor)
    assert r.per90 == pytest.approx(r.player_per90 * r.opponent_factor)
    assert 0.5 < r.team_factor < 2.0 and 0.5 < r.opponent_factor < 2.0


def test_a_null_count_is_left_out_with_its_minutes() -> None:
    h = History()
    for m in world(10):
        h.add(m, bt.LINES_BY_STAT)
    r = rt.player_rate(h, 109, "fouls", at=T0 + timedelta(days=80), team_id=1, opponent_id=2, position="F")  # j = 9: fouls NULL
    assert r.nineties == 0.0


# ── availability ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _history(n: int = 20) -> History:
    h = History()
    for m in world(n):
        h.add(m, bt.LINES_BY_STAT)
    return h


def test_the_rules_decide_out_confirmed_bench_and_left_off() -> None:
    h = _history()
    model = av.StartModel()
    assert av.availability(h, model, 1, 100, "G", absence=OUT).p_play == 0.0
    sheet = {100: SheetLine(100, None, "G", True), 112: SheetLine(112, None, "F", False)}
    starter = av.availability(h, model, 1, 100, "G", sheet=sheet)
    assert (starter.p_start, starter.p_sub, starter.basis) == (1.0, 0.0, av.CONFIRMED_STARTER)
    bench = av.availability(h, model, 1, 112, "F", sheet=sheet)
    assert bench.p_start == 0.0 and 0.0 < bench.p_sub < 1.0 and bench.basis == av.CONFIRMED_BENCH
    left = av.availability(h, model, 1, 105, "M", sheet=sheet)
    assert left.p_play == 0.0 and left.basis == av.NOT_IN_LINEUP


def test_a_regular_starts_more_often_than_a_rotation_man_and_minutes_mix() -> None:
    h = _history()
    model = av.StartModel()
    regular = av.availability(h, model, 1, 101, "D")
    rotation = av.availability(h, model, 1, 111, "M")
    assert regular.p_start > 0.85 > 0.5 > rotation.p_start
    assert regular.expected_minutes == pytest.approx(regular.p_start * regular.minutes_start + regular.p_sub * regular.minutes_sub)
    assert 0.0 <= rotation.p_play <= 1.0
    assert set(av.candidates(h, 1)) == {100 + j for j in range(14)}


def test_a_man_who_moved_is_not_a_candidate_of_his_old_team() -> None:
    h = History()
    h.add(match(1, T0, (line(7, "home"), line(8, "away")), home=1, away=2), bt.LINES_BY_STAT)
    h.add(match(2, T0 + timedelta(days=7), (line(7, "home"), line(9, "away")), home=3, away=2), bt.LINES_BY_STAT)
    assert 7 not in av.candidates(h, 1) and 7 in av.candidates(h, 3)


def test_the_logistic_fit_recovers_a_known_relation() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(4000, 1))
    y = (rng.random(4000) < 1 / (1 + np.exp(-(0.5 + 2.0 * x[:, 0])))).astype(int)
    coef = av.fit_logistic(np.column_stack([np.ones(4000), x]).tolist(), y.tolist(), ridge=0.0)
    assert coef[0] == pytest.approx(0.5, abs=0.15) and coef[1] == pytest.approx(2.0, abs=0.2)


def test_an_unfitted_start_model_is_the_share() -> None:
    f = av.StartFeatures(0.7, True, False, 10)
    assert av.StartModel().p(f) == 0.7
    assert av.StartModel.fit([f] * 10, [1] * 10).coef is None  # too few, and one class


# ── distributions ────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phi", [0.0, 0.3])
def test_the_mixture_is_a_distribution_with_the_no_play_mass_at_zero(phi: float) -> None:
    scen = [(0.6, 85.0), (0.25, 20.0)]
    pmf = props.mixture_pmf(0.9, phi, scen)
    assert float(pmf.sum()) + counts.tail_mass(pmf) == pytest.approx(1.0)
    assert float(pmf.sum()) == pytest.approx(1.0, abs=1e-9)
    assert pmf[0] >= 0.15  # at least the no-play mass
    mean = float((np.arange(pmf.size) * pmf).sum())
    assert mean == pytest.approx(0.9 * (0.6 * 85 + 0.25 * 20) / 90, rel=1e-6)


def test_a_certain_start_is_the_count_engine_itself() -> None:
    pmf = props.mixture_pmf(1.2, 0.2, [(1.0, 90.0), (0.0, 20.0)])
    assert np.allclose(pmf, counts.nb_pmf(1.2, 0.2, props.KMAX))


def test_playing_conditions_drop_the_no_play_mass() -> None:
    scen = [(0.3, 90.0), (0.0, 20.0)]
    cond = props.conditional_on_playing(0.5, 0.0, scen)
    assert cond is not None and np.allclose(cond, counts.nb_pmf(0.5, 0.0, props.KMAX))
    assert props.conditional_on_playing(0.5, 0.0, [(0.0, 90.0), (0.0, 20.0)]) is None
    with pytest.raises(ValueError):
        props.mixture_pmf(0.5, 0.0, [(0.8, 90.0), (0.3, 20.0)])


def test_the_forecast_reads_the_lines() -> None:
    pf = props.forecast("player_goals", 0.6, 0.0, [(1.0, 90.0)], (0.5, 1.5))
    assert pf.over[0.5] == pytest.approx(1 - np.exp(-0.6))
    assert pf.over[1.5] < pf.over[0.5] and pf.over_if_plays == pf.over


def test_the_goal_shares_add_up_to_the_team_expected_goals() -> None:
    rates_ = {1: 0.5, 2: 0.2, 3: 0.05}
    minutes = {1: 90.0, 2: 60.0, 3: 45.0}
    s = props.goal_scale(rates_, minutes, 1.8)
    assert sum(rates_[p] * s * minutes[p] / 90 for p in rates_) == pytest.approx(1.8)
    with pytest.raises(ValueError):
        props.goal_scale({1: 0.5}, {1: 0.0}, 1.0)


# ── the families ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_no_family_is_active_and_each_has_its_own_status() -> None:
    assert fam.STATUSES == (fam.SHADOW,)
    assert all(f.status == fam.SHADOW for f in fam.FAMILIES)
    assert len({f.key for f in fam.FAMILIES}) == len(fam.FAMILIES)
    assert {f.stat for f in fam.FAMILIES} <= set(fam.STATS)
    saves = fam.BY_KEY["keeper_saves"]
    assert fam.applies(saves, "G") and not fam.applies(saves, "F")
    assert not fam.applies(fam.BY_KEY["player_goals"], "G")


# ── the walk-forward ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_evaluation_states_its_samples_and_is_deterministic() -> None:
    matches = world(60)
    start = T0 + timedelta(days=7 * 30)
    end = T0 + timedelta(days=7 * 60)
    one = bt.evaluate(matches, {}, start=start, end=end)
    two = bt.evaluate(list(reversed(matches)), {}, start=start, end=end)
    assert one == two
    assert one["fixtures_evaluated"] == 60 and one["sides_evaluated"] == 120
    s = one["availability"]["start"]
    assert s["n"] > 0 and s["brier"] < s["brier_baseline"]  # the regulars are easy
    by = {f["family"]: f for f in one["families"]}
    assert set(by) == {f.key for f in fam.FAMILIES}
    # 60 matches are far below the data threshold: every family is NOT_MODELABLE, with its reasons
    assert all(f["verdict"] == fam.NOT_MODELABLE and f["reasons"] for f in by.values())
    goals = by["player_goals"]["lines"]["0.5"]
    assert goals["n"] == by["player_goals"]["player_matches"] > 0
    assert {"log_loss", "log_loss_baseline", "brier", "brier_baseline", "log_loss_diff", "log_loss_diff_se", "reliability"} <= set(goals)
    assert by["keeper_saves"]["starters"] == 120  # one keeper a side
    assert by["player_fouls"]["coverage"] < 1.0  # the men with a NULL count are not outcomes


def test_a_large_enough_history_makes_a_family_modelable() -> None:
    matches = world(200, seed=11)
    rec = bt.Engine(matches).walk(T0 + timedelta(days=7 * 200), record_from=T0 + timedelta(days=7 * 20), train_from=T0)
    shots = next(f for f in bt.verdicts(rec) if f["family"] == "player_shots")
    assert shots["player_matches"] >= bt.MIN_PLAYER_MATCHES and shots["verdict"] == fam.MODELABLE


def test_a_rule_out_that_started_is_counted_not_hidden() -> None:
    matches = world(12)
    target = next(m for m in reversed(matches) if m.home_team_id == 1)
    obs = {(target.fixture_id, 100): [(target.kickoff - timedelta(days=1), "LISTED", "Missing Fixture")]}
    rec = bt.Engine(matches, obs).walk(target.kickoff + timedelta(seconds=1), record_from=target.kickoff, train_from=T0)
    assert rec.ruled_out == 1 and rec.ruled_out_started == 1  # the keeper started anyway


def test_show_side_conditions_goals_on_team_xg() -> None:
    matches = world(20)
    engine = bt.Engine(matches)
    at = T0 + timedelta(days=7 * 20)
    engine.walk(at, record_from=at, train_from=T0)
    engine.prepare(at)
    plain = engine.forecast_side(at=at, team_id=1, opponent_id=2, sheet=None, absences={})
    cond = engine.forecast_side(at=at, team_id=1, opponent_id=2, sheet=None, absences={}, team_xg=2.0)
    assert plain["goal_scale"] is None and cond["goal_scale"] is not None
    total = 0.0
    for p in cond["players"]:
        goals = next((x for x in p["props"] if x["family"] == "player_goals"), None)
        if goals is not None:
            total += goals["mean"]
    assert total == pytest.approx(2.0, rel=1e-3)
    for p in plain["players"]:
        for x in p["props"]:
            assert x["status"] == fam.SHADOW
            assert all(0.0 <= v <= 1.0 for v in x["p_over"].values())
