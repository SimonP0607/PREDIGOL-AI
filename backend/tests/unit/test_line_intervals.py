"""The batch line arithmetic is the scalar one: every market, quarter lines and pushes included."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from fbi.models.goals import GoalModel, GoalObs, fit_goal_model
from fbi.models.line_intervals import distributions, line_intervals, outcome_batch
from fbi.models.lines import asian_handicap, double_chance, over_under
from fbi.models.scoring import dc_tau, matrices_batch, poisson_matrix

D = Decimal
LINES_AH = [D(x) for x in ("-2.75", "-1.5", "-1", "-0.75", "-0.25", "0", "0.25", "0.5", "1", "1.25", "2.5")]
LINES_OU = [D(x) for x in ("0.5", "1.75", "2", "2.25", "2.5", "3", "3.75", "4.5")]


@pytest.mark.parametrize(("lh", "la", "rho"), [(1.4, 1.1, None), (2.6, 0.7, -0.08), (0.9, 1.8, 0.05)])
def test_the_batch_path_equals_the_scalar_one(lh: float, la: float, rho: float | None) -> None:
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    m = m / m.sum()
    batch = matrices_batch(np.array([lh]), np.array([la]), None if rho is None else np.array([rho]))
    assert np.allclose(batch[0], m)
    d = distributions(batch)
    for line in LINES_AH:
        for side in ("Home", "Away"):
            win, push = outcome_batch(d, "AH", side, line)
            ref = asian_handicap(m, selection=side, line=line)
            assert win[0] == pytest.approx(ref.win, abs=1e-12) and push[0] == pytest.approx(ref.push, abs=1e-12)
    for line in LINES_OU:
        for side in ("Over", "Under"):
            win, push = outcome_batch(d, "OU", side, line)
            ref = over_under(m, selection=side, line=line)
            assert win[0] == pytest.approx(ref.win, abs=1e-12) and push[0] == pytest.approx(ref.push, abs=1e-12)
    dc = double_chance(m)
    for sel, p in dc.items():
        win, push = outcome_batch(d, "DC", sel, D(0))
        assert win[0] == pytest.approx(p, abs=1e-12) and push[0] == 0
    with pytest.raises(ValueError):
        outcome_batch(d, "AH", "Draw", D(0))


def test_intervals_bracket_the_point_and_narrow_with_data() -> None:
    rng = np.random.default_rng(3)
    teams = list(range(1, 9))

    def fit(n: int) -> GoalModel:
        obs = []
        for _ in range(n):
            h, a = rng.choice(teams, size=2, replace=False)
            obs.append(GoalObs(int(h), int(a), int(rng.poisson(1.5)), int(rng.poisson(1.1))))
        return fit_goal_model(obs, kind="poisson", penalty=1.0, with_covariance=True)

    triples = [("AH", "Home", D("-0.75")), ("OU", "Over", D("2.25")), ("DC", "1X", D(0))]
    small, large = fit(120), fit(1200)
    widths = []
    for model in (small, large):
        bounds = line_intervals(model, 1, 2, triples)
        assert bounds is not None and set(bounds) == set(triples)
        m, _, _ = model.score_matrix(1, 2)
        m = m / m.sum()
        point = {triples[0]: asian_handicap(m, selection="Home", line=D("-0.75")).win,
                 triples[1]: over_under(m, selection="Over", line=D("2.25")).win,
                 triples[2]: double_chance(m)["1X"]}
        for t, (lo, hi) in bounds.items():
            assert lo < hi and lo <= point[t] + 0.02 and point[t] - 0.02 <= hi
        widths.append(np.mean([hi - lo for lo, hi in bounds.values()]))
    assert widths[1] < widths[0], "ten times the data, a narrower interval"
