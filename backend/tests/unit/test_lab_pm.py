"""IA-154 to IA-157: the pure arithmetic of the LAB lines of the plan PM, checked on synthetic data before any real data is read."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from scripts import lab_fichas as lf
from scripts import lab_pm_common as lc
from scripts import lab_portfolio as lp
from scripts import lab_season_sim as ls
from scripts import lab_stabilization as lst

from fbi.models.goals import GoalObs, fit_goal_model
from fbi.research import protocol

# ── common ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_lab_script_names_a_registered_protocol() -> None:
    for key in (lst.KEY, lf.KEY, ls.KEY, *lp.KEYS):
        assert protocol.require(key).registered_on == "2026-11-21"


def test_wilson_and_block_bootstrap() -> None:
    lo, hi = lc.wilson(90, 100)
    assert lo < 0.9 < hi and 0.82 < lo < 0.84 and 0.94 < hi < 0.95
    v = np.ones(100)
    mean, lo, hi = lc.block_bootstrap_mean(v, np.arange(100) // 10, reps=200, seed=1)
    assert mean == lo == hi == 1.0


def test_monday_of_is_the_iso_week_start() -> None:
    assert lc.monday_of(datetime(2026, 11, 22, 23, 0, tzinfo=UTC)) == datetime(2026, 11, 16, tzinfo=UTC)
    assert lc.monday_of(datetime(2026, 11, 16, 0, 0, tzinfo=UTC)) == datetime(2026, 11, 16, tzinfo=UTC)


# ── PM-10-08 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _season(rng: np.random.Generator, teams: int, matches: int, tau: float, sigma: float) -> list[np.ndarray]:
    levels = rng.normal(10.0, tau, teams)
    return [rng.normal(level, sigma, matches) for level in levels]


def test_stabilization_recovers_the_known_ratio_of_noise_to_signal() -> None:
    rng = np.random.default_rng(7)
    tau, sigma = 1.0, 3.0  # n50 = sigma^2 / tau^2 = 9
    parts = [lst.season_parts(_season(rng, 20, 38, tau, sigma), rng) for _ in range(30)]
    assert all(p is not None for p in parts)
    res = lst.league_result([p for p in parts if p is not None], rng=rng, reps=200)
    assert 7.0 < res["n50"] < 11.5
    assert res["n70"] == pytest.approx(res["n50"] * (0.7 / 0.3), rel=1e-9)
    assert res["n50_ci"][0] < res["n50"] < res["n50_ci"][1]
    assert res["validated"] is True and abs(res["half_r"] - res["half_r_predicted"]) < 0.1


def test_no_spread_between_teams_means_no_stable_minimum() -> None:
    assert lst.n_for(0.5, 4.0, 0.0) is None and lst.n_for(0.5, 4.0, -1.0) is None
    assert lst.reliability_at(10, 4.0, -1.0) == 0.0
    assert lst.n_for(0.5, 4.0, 1.0) == pytest.approx(4.0)


def test_a_season_with_too_few_teams_or_matches_is_left_out() -> None:
    rng = np.random.default_rng(1)
    assert lst.season_parts(_season(rng, 9, 30, 1, 1), rng) is None
    assert lst.season_parts(_season(rng, 20, 9, 1, 1), rng) is None


def test_stabilization_verdict_needs_five_leagues_and_seventy_percent() -> None:
    good, bad = {"validated": True}, {"validated": False}
    assert lst.verdict({1: good, 2: good, 3: good, 4: good})[0] == "INSUFICIENTE"
    assert lst.verdict(dict.fromkeys(range(7), good) | {8: bad, 9: bad, 10: bad})[0] == "PASA"
    assert lst.verdict(dict.fromkeys(range(6), good) | {8: bad, 9: bad, 10: bad})[0] == "NO PASA"


def test_the_table_never_lowers_the_current_minimum() -> None:
    measured = {"stats": {"corners_for": {"verdict": "PASA", "eligible_leagues": 9, "n50_median": 1.2, "n70_median": 2.8,
                                          "leagues": {}},
                          "fouls_for": {"verdict": "NO PASA", "eligible_leagues": 9, "n50_median": 20.0, "n70_median": 47.0,
                                        "leagues": {}}}}
    t = lst.table_of(measured, {}, {})
    assert t["stats"]["corners_for"]["proposed_min_matches"] == lst.CURRENT_MIN_MATCHES
    assert "n50" not in t["stats"]["fouls_for"]


# ── PM-09-07 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _rr(teams: int) -> list[ls.Game]:
    t0 = datetime(2024, 8, 1, tzinfo=UTC)
    games, k = [], 0
    for h in range(teams):
        for a in range(teams):
            if h != a:
                games.append(ls.Game(k, t0 + timedelta(hours=k), h, a, 1, 0))
                k += 1
    return games


def test_double_round_robin_is_recognised_exactly() -> None:
    assert ls.is_double_round_robin(_rr(10)) == (True, 10)
    assert ls.is_double_round_robin(_rr(10)[:-1])[0] is False
    assert ls.is_double_round_robin(_rr(9))[0] is False


def test_cut_index_leaves_at_least_the_share_played() -> None:
    assert ls.cut_index(90, 1) == 29 and ls.cut_index(90, 2) == 59
    assert ls.cut_index(91, 1) == 30


def test_truth_shares_a_tie_across_the_line() -> None:
    final = {1: (10, 5, 5), 2: (10, 5, 5), 3: (8, 0, 1), 4: (1, 0, 0), 5: (0, 0, 0), 6: (0, -1, 0), 7: (0, -2, 0), 8: (0, -3, 0),
             9: (0, -4, 0), 10: (0, -5, 0)}
    tr = ls.truth(final, 10)
    assert tr["champion"][1] == tr["champion"][2] == 0.5 and tr["champion"][3] == 0.0
    assert tr["top4"][4] == 1.0 and tr["bottom3"][10] == 1.0 and tr["bottom3"][7] == 0.0


def test_a_certain_season_is_simulated_as_certain() -> None:
    teams = list(range(10))
    start = {t: (30 - 3 * t, 0, 0) for t in teams}
    m = np.zeros((11, 11))
    m[0, 0] = 1.0  # every match left ends 0-0
    res = ls.simulate(teams, start, [(1, 2), (3, 4)], [m, m], sims=500, rng=np.random.default_rng(1))
    assert res["champion"][0] == 1.0 and res["top4"][3] == 1.0 and res["top4"][4] == 0.0 and res["bottom3"][9] == 1.0


def test_brier_skill_and_ece() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0])
    p = np.array([0.9, 0.1, 0.8, 0.2])
    q = np.full(4, 0.5)
    bss, lo, hi = ls.bss_interval(p, q, y, np.array([0, 0, 1, 1]), reps=200, seed=1)
    assert bss == pytest.approx(1 - ls.brier(p, y) / 0.25) and lo <= bss <= hi
    assert ls.ece(np.array([0.2] * 10), np.array([0.0] * 8 + [1.0] * 2), bins=1) == pytest.approx(0.0)


def test_season_sim_verdict_is_insufficient_without_a_hundred_seasons() -> None:
    units = [{"season_block": b, "cut": c, "objective": o, "p": 0.5, "q": 0.5, "y": float(b % 2)}
             for b in range(10) for c in ls.CUTS for o in ls.OBJECTIVES]
    assert ls.evaluate(units, seed=1, reps=50)["verdict"] == "INSUFICIENTE"


# ── PM-08-07 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_jaccard_by_chance_and_neighbours() -> None:
    assert lf.jaccard_by_chance(4) == pytest.approx(1.0)
    assert 0.05 < lf.jaccard_by_chance(20) < 0.15
    x = np.array([[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [5.0, 5.0], [5.1, 5.0], [5.0, 5.1]])
    nb = lf.neighbours(x, k=2)
    assert nb[0] == {1, 2} and nb[3] == {4, 5}


def test_style_is_stable_when_teams_keep_their_style() -> None:
    rng = np.random.default_rng(3)
    base = rng.normal(0, 1, (16, len(lf.DIMS)))
    means = {(1, s): {t: base[t] + rng.normal(0, 0.2, len(lf.DIMS)) for t in range(16)} for s in range(2021, 2026)}
    e = lf.style_stability(means)
    assert e["pairs"] == 4 and all(v is not None and v > 0.8 for v in e["median_spearman"].values())


def test_card_verdicts_follow_the_protocol() -> None:
    e = {"pairs": 40, "median_spearman": dict.fromkeys(lf.DIMS, 0.7)}
    p = {"league_seasons": 40, "ci": [0.45, 0.55], "chance": 0.1}
    a = {"league_seasons": 30, "share_agree": 0.9, "rule": {"with_accumulation": []}}
    t = {"league_seasons": 30, "share": 0.95}
    i = {"referees": 300, "coaches": 300, "referee_share": 0.5, "coach_share": 0.9}
    v = lf.verdicts(e, 0.6, p, a, t, i)
    assert v == {"E": "PASA", "P": "PASA", "A": "INSUFICIENTE", "T": "PASA", "I": "NO PASA"}


def test_the_coded_rules_have_no_accumulation_threshold_today(tmp_path: Path) -> None:
    rules = Path(__file__).resolve().parents[2] / "config" / "rules"
    r = lf.accumulation_rule_coded(rules)
    assert r["read"] and r["files"] > 5 and r["with_accumulation"] == []
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "v1.yaml").write_text("discipline: {yellow_card_ban: 5}\n", encoding="utf-8")
    assert lf.accumulation_rule_coded(tmp_path)["with_accumulation"] == ["x"]


# ── PM-12-03 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_onex2_and_pool() -> None:
    m = np.array([[0.2, 0.1], [0.3, 0.4]])
    assert lp.onex2(m) == pytest.approx([0.3, 0.6, 0.1])
    p = lp.pool(np.array([0.5, 0.3, 0.2]), np.array([0.5, 0.3, 0.2]))
    assert p == pytest.approx([0.5, 0.3, 0.2])


def _league(rng: np.random.Generator, n_teams: int, matches: int, home: float) -> list[GoalObs]:
    att, de = rng.normal(0, 0.3, n_teams), rng.normal(0, 0.3, n_teams)
    out = []
    for _ in range(matches):
        h, a = rng.choice(n_teams, 2, replace=False)
        lh, la = math.exp(0.1 + home + att[h] - de[a]), math.exp(0.1 + att[a] - de[h])
        out.append(GoalObs(int(h), int(a), int(rng.poisson(lh)), int(rng.poisson(la))))
    return out


def test_home_term_moves_toward_the_recent_home_advantage() -> None:
    rng = np.random.default_rng(5)
    old = _league(rng, 20, 1500, 0.35)
    model = fit_goal_model(old, kind="poisson", penalty=1.0, with_covariance=False)
    recent = _league(rng, 20, 3000, -0.05)  # a season without home advantage
    h = lp.home_term(model, [(o.home_id, o.away_id, o.goals_home, 1.0) for o in recent], prior_sd=1.0)
    assert h < model.home - 0.2
    assert lp.home_term(model, [], prior_sd=1.0) == model.home


def test_market_strengths_recover_the_order_of_teams_and_the_gradient_is_right() -> None:
    from scipy.optimize import check_grad

    rng = np.random.default_rng(2)
    strength = np.linspace(-1, 1, 12)
    rows = []
    for _ in range(400):
        h, a = rng.choice(12, 2, replace=False)
        z = 0.3 + strength[h] - strength[a]
        a1, a2 = 1 / (1 + math.exp(-(-0.5 - z))), 1 / (1 + math.exp(-(0.6 - z)))
        rows.append((int(h), int(a), np.array([1 - a2, a2 - a1, a1]), 1.0))
    fit = lp.market_fit(rows, penalty=0.01)
    assert fit is not None
    idx, theta = fit
    est = np.array([theta[idx[t]] for t in range(12)])
    assert np.corrcoef(est, strength)[0, 1] > 0.99
    p = lp.market_predict(fit, 11, 0)
    assert p is not None and p[0] > 0.7 and p.sum() == pytest.approx(1.0)
    assert lp.market_predict(fit, 11, 99) is None
    # the analytic gradient of the cross-entropy, against finite differences, at a random point
    hi = np.array([r[0] for r in rows])
    ai = np.array([r[1] for r in rows])
    q = np.array([r[2] for r in rows])
    w = np.ones(len(rows))
    x0 = rng.normal(0, 0.3, 12 + 3)
    err = check_grad(lambda t: lp.market_objective(t, hi, ai, q, w, 0.5)[0], lambda t: lp.market_objective(t, hi, ai, q, w, 0.5)[1], x0)
    assert err < 1e-3 * max(1.0, float(np.abs(lp.market_objective(x0, hi, ai, q, w, 0.5)[1]).max()))


def test_conformal_quantile_and_paired_comparison() -> None:
    s = np.linspace(0, 1, 101)
    q = lp.conformal_q(s, 0.10)
    assert q is not None and 0.9 <= q <= 0.92
    assert lp.conformal_q(np.array([])) is None
    a, b = np.full(200, 1.0), np.full(200, 1.1)
    r = lp.paired(a, b, np.arange(200) // 7, seed=1, reps=100)
    assert r["mean"] == pytest.approx(-0.1) and r["ci"][1] < 0 and r["n"] == 200
