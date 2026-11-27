"""RP-9.6 (EXP-E6): the streaks of ten, the residual of the market, the four types and the verdict, on simulated matches. Pure."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np

from fbi.research import exp_conditions, exp_protocol
from fbi.research import exp_e6 as e6

T0 = datetime(2026, 1, 1, 15, tzinfo=UTC)


def played(i: int, home: int, away: int, goals: tuple[int, int], *, day: int | None = None, q: float | None = 0.5) -> e6.Played:
    return e6.Played(i, T0 + timedelta(days=i if day is None else day), home, away, goals[0], goals[1], q)


def run_of(team: int, n: int, goals: tuple[int, int], *, start: int = 0) -> list[e6.Played]:
    """``n`` matches of ``team`` (at home, against a different opponent each time) with the same score."""
    return [played(start + i, team, 100 + i, goals) for i in range(n)]


def test_a_streak_needs_ten_matches_and_all_ten_must_agree() -> None:
    wins = run_of(1, 10, (2, 0))
    assert e6.streaks_of(wins, 1) == {e6.WINS, e6.FEW}, "ten wins by 2-0: wins and few goals (two in total)"
    assert e6.streaks_of(wins[:9], 1) == set(), "nine is not a streak"
    nine_and_a_draw = [*wins[:9], played(9, 1, 109, (1, 1))]
    assert e6.streaks_of(nine_and_a_draw, 1) == {e6.FEW}, "a draw breaks the wins; the goals streak holds (two in total)"
    assert e6.streaks_of(run_of(1, 10, (3, 3)), 1) == {e6.MANY}
    away = [played(i, 100 + i, 1, (0, 1)) for i in range(10)]
    assert e6.streaks_of(away, 1) == {e6.WINS, e6.FEW}, "the result is read from the side of the team, home or away"
    assert e6.streaks_of([played(i, 100 + i, 1, (3, 0)) for i in range(10)], 1) == {e6.LOSSES, e6.MANY}


def test_the_match_that_follows_a_streak_has_the_residual_of_the_market() -> None:
    history = run_of(1, 10, (2, 2))
    nxt = played(10, 1, 50, (2, 2), q=0.62)
    found = e6.cases([*history, nxt])
    assert len(found) == 1 and found[0].fixture == 10 and found[0].types == (e6.MANY,)
    assert found[0].residual == 1.0 - 0.62, "four goals: the Over 2.5 happened"
    under = e6.cases([*history, played(10, 1, 50, (1, 0), q=0.62)])
    assert under[0].residual == 0.0 - 0.62


def test_nothing_of_the_match_itself_or_later_enters_its_streak_and_a_match_without_a_consensus_is_not_a_case() -> None:
    history = run_of(1, 10, (2, 0))
    base = e6.cases([*history, played(10, 1, 50, (0, 0), q=0.4)])
    later = e6.cases([*history, played(10, 1, 50, (0, 0), q=0.4), played(11, 1, 51, (5, 5), q=0.4)])
    assert [c.fixture for c in base] == [10], "the eleventh match follows the streak of the ten before it"
    assert later[0] == base[0], "the figure of a match does not change when later matches arrive"
    assert [c.fixture for c in later] == [10, 11] and later[1].types == (e6.FEW,), "the 0-0 breaks the wins and leaves the few goals: ten of two or fewer"
    assert all(c.fixture != 10 for c in e6.cases([*history, played(10, 1, 50, (0, 0), q=None)])), "no consensus, no residual"
    assert e6.cases(history) == [], "the ten matches themselves follow no streak of ten"


def test_a_streak_across_a_long_break_is_not_a_streak() -> None:
    history = [played(i, 1, 100 + i, (2, 0), day=i) for i in range(10)]
    near = played(10, 1, 50, (1, 0), day=10 + e6.MAX_SPAN_DAYS - 12)
    far = played(11, 1, 51, (1, 0), day=9 + e6.MAX_SPAN_DAYS + 5)
    assert len(e6.cases([*history, near])) == 1
    assert e6.cases([*history, far]) == []


def test_a_match_is_in_the_type_of_either_team_and_in_several_types_at_once() -> None:
    a = run_of(1, 10, (2, 0), start=0)   # team 1: wins and few goals
    b = [played(20 + i, 200 + i, 2, (4, 1)) for i in range(10)]   # team 2: ten defeats with many goals
    found = e6.cases([*sorted([*a, *b], key=lambda m: m.kickoff), played(40, 1, 2, (1, 1), q=0.5)])
    assert len(found) == 1 and set(found[0].types) == {e6.WINS, e6.FEW, e6.LOSSES, e6.MANY}
    assert found[0].types == tuple(t for t in e6.TYPES if t in found[0].types), "in the order of the protocol"
    series = e6.series_of(found)
    assert all(len(series[t][0]) == 1 for t in e6.TYPES)


def two_sided_world(n_each: int, shift: dict[str, float], *, seed: int = 4) -> dict[str, tuple[list[float], list[date]]]:
    rng = np.random.default_rng(seed)
    start = date(2026, 1, 1)
    out: dict[str, tuple[list[float], list[date]]] = {}
    for t in e6.TYPES:
        q = rng.uniform(0.35, 0.65, n_each)
        happened = (rng.random(n_each) < np.clip(q + shift.get(t, 0.0), 0.01, 0.99)).astype(float)
        out[t] = ((happened - q).tolist(), [start + timedelta(days=int(k // 4)) for k in range(n_each)])
    return out


def test_a_market_that_prices_every_streak_right_is_an_abandonment_once_all_four_types_have_their_sample() -> None:
    judgement, figures = e6.judge(two_sided_world(1500, {}), seed=7)
    assert judgement.verdict == "abandono" and set(figures) == set(e6.TYPES)
    assert all(f["n"] == 1500 and f["verdict"] == "dentro del error" for f in figures.values())


def test_a_planted_error_of_the_market_after_one_type_of_streak_is_a_success_with_its_interval_and_its_sign() -> None:
    judgement, figures = e6.judge(two_sided_world(2000, {e6.MANY: 0.08}), seed=7)
    assert judgement.verdict == "exito" and judgement.reason.startswith(e6.MANY)
    assert judgement.mean > 0.04 and judgement.low > 0 and (judgement.adjusted_p or 1.0) < exp_protocol.ALPHA
    assert figures[e6.MANY]["same_sign_halves"] is True and figures[e6.WINS]["verdict"] == "dentro del error"
    mirrored, _ = e6.judge(two_sided_world(2000, {e6.FEW: -0.08}), seed=7)
    assert mirrored.verdict == "exito" and mirrored.mean < 0 and mirrored.high < 0, "the market paying too much is a success too: the residual is different from zero"


def test_with_a_type_short_of_its_sample_nothing_is_abandoned_and_nothing_is_stretched() -> None:
    series = two_sided_world(1500, {})
    series[e6.LOSSES] = (series[e6.LOSSES][0][:120], series[e6.LOSSES][1][:120])
    judgement, figures = e6.judge(series, seed=7)
    assert judgement.verdict == "insuficiente" and "3 de 4" in judgement.reason
    assert figures[e6.LOSSES]["verdict"] is None and figures[e6.LOSSES]["n"] == 120
    empty, _ = e6.judge({}, seed=7)
    assert empty.verdict == "insuficiente" and empty.n == 0


def test_the_sample_is_the_one_fixed_from_the_power_of_the_question_and_the_experiment_plugs_into_the_launcher() -> None:
    assert e6.REQUIRED == 500 and e6.STREAK == 10 and e6.KEY == "EXP-E6" and exp_protocol.E6.segments == e6.TYPES
    assert "fbi.research.exp_e6" in exp_conditions.PLUGINS
    exp_conditions.unregister("EXP-E6")
    try:
        spec = e6.register()
        assert spec.required == 500 and spec.run is e6.run
    finally:
        exp_conditions.unregister("EXP-E6")
