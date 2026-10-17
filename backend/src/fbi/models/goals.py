"""Poisson (Maher 1982) and Dixon-Coles (1997), fitted by weighted maximum likelihood.

PARAMETERISATION - each strength enters exactly once:

    log lambda_home = mu + home + attack[h] - defence[a]
    log lambda_away = mu        + attack[a] - defence[h]

with sum(attack) = 0 and sum(defence) = 0 imposed by construction (the last
team's value is minus the sum of the others). The legacy model multiplied a
team's attack by the opponent's defence AND by a league average that already
contained both, counting strength twice; here there is one intercept and one
term per side, and a test recovers known parameters from simulated seasons.

TIME DECAY. A match of age t days has weight exp(-xi * t). xi is a
hyper-parameter: it is chosen on a validation window before the test window,
never on the test window, and recorded with the fitted model.

SHRINKAGE. ``penalty`` adds penalty * (sum attack^2 + sum defence^2) to the
negative log-likelihood - a Gaussian prior centred on an average team. Without
it a team that has not scored in its few training matches gets an attack of
minus infinity and a probability of exactly zero of ever scoring. Like xi, the
penalty is chosen on the validation window.

UNCERTAINTY. The Hessian at the optimum is computed from the analytic
gradient by central differences; its inverse (Laplace approximation) is the
parameter covariance, and probability intervals are quantiles over parameter
draws. BFGS's own running inverse-Hessian estimate is NOT used: it is an
optimiser's device, not a curvature measurement. It is an approximation and is
labelled as one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import gammaln

from fbi.models.scoring import (
    MarketProbabilities,
    dc_tau,
    from_matrix,
    market_rows_batch,
    poisson_matrix,
)

INTERVAL_LEVEL = 0.9


class InvalidCorrectionError(ValueError):
    """The fitted Dixon-Coles rho cannot be applied at these expected goals."""


def dc_valid(lam_home: float, lam_away: float, rho: float) -> bool:
    """Whether every Dixon-Coles tau factor is positive for these expected goals."""
    return (1 - lam_home * lam_away * rho > 0) and (1 + lam_home * rho > 0) and (1 + lam_away * rho > 0) and rho < 1


@dataclass(frozen=True, slots=True)
class GoalObs:
    home_id: int
    away_id: int
    goals_home: int
    goals_away: int
    weight: float = 1.0
    neutral: bool = False


@dataclass
class GoalModel:
    kind: str  # "poisson" | "dixon_coles"
    teams: list[int]
    mu: float
    home: float
    attack: NDArray[np.float64]
    defence: NDArray[np.float64]
    rho: float
    xi: float
    n_train: int
    converged: bool
    loglik: float
    cov: NDArray[np.float64] | None = None
    index: dict[int, int] = field(default_factory=dict)
    penalty: float = 0.0
    _draws: NDArray[np.float64] | None = None

    def knows(self, team_id: int) -> bool:
        return team_id in self.index

    def lambdas(self, home_id: int, away_id: int, *, neutral: bool = False) -> tuple[float, float]:
        h, a = self.index[home_id], self.index[away_id]
        adv = 0.0 if neutral else self.home
        lh = float(np.exp(self.mu + adv + self.attack[h] - self.defence[a]))
        la = float(np.exp(self.mu + self.attack[a] - self.defence[h]))
        return lh, la

    def score_matrix(
        self, home_id: int, away_id: int, *, neutral: bool = False
    ) -> tuple[NDArray[np.float64], float, float]:
        """The joint distribution over (home goals, away goals), and the lambdas.

        Everything the model says about a match is in here. ``predict`` reads
        seven numbers off it; fbi.models.lines reads the handicap, total and
        double-chance markets off the same matrix, which is why those markets
        need nothing fitted and were disabled only for want of this accessor.
        """
        lh, la = self.lambdas(home_id, away_id, neutral=neutral)
        m = poisson_matrix(lh, la)
        if self.kind == "dixon_coles":
            if not dc_valid(lh, la, self.rho):
                # tau is only a probability adjustment inside
                # max(-1/lh, -1/la) <= rho <= min(1/(lh*la), 1). Outside it a
                # score gets a negative probability; clipping rho would be a
                # different model, so the fixture is declined instead.
                raise InvalidCorrectionError(
                    f"Dixon-Coles correction rho={self.rho:.3f} is invalid for expected goals "
                    f"{lh:.2f}-{la:.2f}")
            m = dc_tau(m, lh, la, self.rho)
        return m, lh, la

    def predict(self, home_id: int, away_id: int, *, neutral: bool = False) -> MarketProbabilities:
        m, lh, la = self.score_matrix(home_id, away_id, neutral=neutral)
        return from_matrix(m, lh, la)

    def parameter_draws(self, draws: int = 200, seed: int = 7) -> NDArray[np.float64] | None:
        """Draws from the Laplace approximation, made once per fitted model and reused."""
        if self.cov is None:
            return None
        if self._draws is None or len(self._draws) != draws:
            rng = np.random.default_rng(seed)
            try:
                self._draws = rng.multivariate_normal(_pack(self), self.cov, size=draws, check_valid="raise")
            except (np.linalg.LinAlgError, ValueError):
                return None
        return self._draws

    def lambda_draws(self, home_id: int, away_id: int, *, neutral: bool = False, draws: int = 200
                     ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64] | None] | None:
        """(lambda_home, lambda_away, rho) for each parameter draw that is inside the model, or None
        when there is no covariance or too few draws are valid."""
        theta = self.parameter_draws(draws)
        if theta is None:
            return None
        n = len(self.teams)
        h, a = self.index[home_id], self.index[away_id]
        att = np.concatenate([theta[:, 2:n + 1], -theta[:, 2:n + 1].sum(axis=1, keepdims=True)], axis=1)
        dfn = np.concatenate([theta[:, n + 1:2 * n], -theta[:, n + 1:2 * n].sum(axis=1, keepdims=True)], axis=1)
        adv = 0.0 if neutral else 1.0
        lh = np.exp(theta[:, 0] + adv * theta[:, 1] + att[:, h] - dfn[:, a])
        la = np.exp(theta[:, 0] + att[:, a] - dfn[:, h])
        rho = theta[:, 2 * n] if self.kind == "dixon_coles" else None
        if rho is not None:
            ok = (1 - lh * la * rho > 0) & (1 + lh * rho > 0) & (1 + la * rho > 0) & (1 - rho > 0)
            lh, la, rho = lh[ok], la[ok], rho[ok]
            if len(lh) < draws // 2:
                return None
        return lh, la, rho

    def interval_rows(self, home_id: int, away_id: int, *, neutral: bool = False, draws: int = 200,
                      level: float = INTERVAL_LEVEL) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        """(lo, hi) for every MARKET_ROWS probability, or None when there is no covariance.

        None is an honest "no interval", which is not the same as an interval of width zero."""
        theta = self.parameter_draws(draws)
        if theta is None:
            return None
        n = len(self.teams)
        h, a = self.index[home_id], self.index[away_id]
        att = np.concatenate([theta[:, 2:n + 1], -theta[:, 2:n + 1].sum(axis=1, keepdims=True)], axis=1)
        dfn = np.concatenate([theta[:, n + 1:2 * n], -theta[:, n + 1:2 * n].sum(axis=1, keepdims=True)], axis=1)
        adv = 0.0 if neutral else 1.0
        lh = np.exp(theta[:, 0] + adv * theta[:, 1] + att[:, h] - dfn[:, a])
        la = np.exp(theta[:, 0] + att[:, a] - dfn[:, h])
        rho = theta[:, 2 * n] if self.kind == "dixon_coles" else None
        if rho is not None:
            # A draw can put rho where tau turns a score probability negative.
            # Those parameter vectors are outside the model; they are dropped.
            ok = (1 - lh * la * rho > 0) & (1 + lh * rho > 0) & (1 + la * rho > 0) & (1 - rho > 0)
            lh, la, rho = lh[ok], la[ok], rho[ok]
            if len(lh) < draws // 2:
                return None
        rows = market_rows_batch(lh, la, rho)
        point = np.array(self.predict(home_id, away_id, neutral=neutral).as_rows())
        q = (1 - level) / 2
        lo, hi = np.quantile(rows, q, axis=0), np.quantile(rows, 1 - q, axis=0)
        return np.minimum(lo, point), np.maximum(hi, point)

    def interval_1x2(self, home_id: int, away_id: int, *, neutral: bool = False, draws: int = 200,
                     level: float = INTERVAL_LEVEL) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """(lo, hi) for (home, draw, away); the point itself when there is no covariance."""
        out = self.interval_rows(home_id, away_id, neutral=neutral, draws=draws, level=level)
        if out is None:
            point = np.array(self.predict(home_id, away_id, neutral=neutral).as_1x2())
            return point, point
        return out[0][:3], out[1][:3]


def _pack(m: GoalModel) -> NDArray[np.float64]:
    parts = [np.array([m.mu, m.home]), m.attack[:-1], m.defence[:-1]]
    if m.kind == "dixon_coles":
        parts.append(np.array([m.rho]))
    return np.concatenate(parts)


def _unpack(template: GoalModel, theta: NDArray[np.float64]) -> GoalModel:
    n = len(template.teams)
    mu, home = float(theta[0]), float(theta[1])
    att = np.append(theta[2:n + 1], -theta[2:n + 1].sum())
    dfn = np.append(theta[n + 1:2 * n], -theta[n + 1:2 * n].sum())
    rho = float(theta[2 * n]) if template.kind == "dixon_coles" else 0.0
    return GoalModel(template.kind, template.teams, mu, home, att, dfn, rho, template.xi, template.n_train,
                     template.converged, template.loglik, None, template.index, template.penalty)


@dataclass(frozen=True, slots=True)
class _Data:
    hi: NDArray[np.int64]
    ai: NDArray[np.int64]
    gh: NDArray[np.float64]
    ga: NDArray[np.float64]
    w: NDArray[np.float64]
    home_flag: NDArray[np.float64]
    const: NDArray[np.float64]
    m00: NDArray[np.bool_]
    m01: NDArray[np.bool_]
    m10: NDArray[np.bool_]
    m11: NDArray[np.bool_]


def _objective(theta: NDArray[np.float64], d: _Data, n: int, dc: bool,
               penalty: float) -> tuple[float, NDArray[np.float64]]:
    """Penalised weighted negative log-likelihood and its exact gradient."""
    mu, home = theta[0], theta[1]
    att = np.append(theta[2:n + 1], -theta[2:n + 1].sum())
    dfn = np.append(theta[n + 1:2 * n], -theta[n + 1:2 * n].sum())
    log_lh = mu + home * d.home_flag + att[d.hi] - dfn[d.ai]
    log_la = mu + att[d.ai] - dfn[d.hi]
    lh, la = np.exp(log_lh), np.exp(log_la)
    ll = d.gh * log_lh - lh + d.ga * log_la - la - d.const
    r_h = d.gh - lh  # d ll / d log lambda_home
    r_a = d.ga - la
    g_rho = 0.0
    if dc:
        rho = theta[2 * n]
        tau = np.ones_like(lh)
        dth = np.zeros_like(lh)
        dta = np.zeros_like(lh)
        dtr = np.zeros_like(lh)
        m = d.m00
        tau[m] = 1.0 - lh[m] * la[m] * rho
        dth[m] = -lh[m] * la[m] * rho
        dta[m] = -lh[m] * la[m] * rho
        dtr[m] = -lh[m] * la[m]
        m = d.m01
        tau[m] = 1.0 + lh[m] * rho
        dth[m] = lh[m] * rho
        dtr[m] = lh[m]
        m = d.m10
        tau[m] = 1.0 + la[m] * rho
        dta[m] = la[m] * rho
        dtr[m] = la[m]
        m = d.m11
        tau[m] = 1.0 - rho
        dtr[m] = -1.0
        if np.any(tau <= 0):
            return 1e12, np.zeros_like(theta)
        ll = ll + np.log(tau)
        r_h = r_h + dth / tau
        r_a = r_a + dta / tau
        g_rho = -float((d.w * dtr / tau).sum())
    value = -float((d.w * ll).sum()) + penalty * float((att ** 2).sum() + (dfn ** 2).sum())
    wr_h, wr_a = d.w * r_h, d.w * r_a
    g_att = -(np.bincount(d.hi, wr_h, n) + np.bincount(d.ai, wr_a, n)) + 2.0 * penalty * att
    g_dfn = (np.bincount(d.ai, wr_h, n) + np.bincount(d.hi, wr_a, n)) + 2.0 * penalty * dfn
    grad = np.concatenate([
        [-(wr_h.sum() + wr_a.sum()), -(wr_h * d.home_flag).sum()],
        g_att[:-1] - g_att[-1],
        g_dfn[:-1] - g_dfn[-1],
        [g_rho] if dc else [],
    ])
    return value, grad


def _hessian(theta: NDArray[np.float64], d: _Data, n: int, dc: bool, penalty: float) -> NDArray[np.float64]:
    """Central differences of the exact gradient."""
    k = len(theta)
    h = np.empty((k, k))
    for j in range(k):
        step = 1e-5 * max(1.0, abs(float(theta[j])))
        up, down = theta.copy(), theta.copy()
        up[j] += step
        down[j] -= step
        h[:, j] = (_objective(up, d, n, dc, penalty)[1] - _objective(down, d, n, dc, penalty)[1]) / (2 * step)
    return (h + h.T) / 2.0


def _covariance(hess: NDArray[np.float64]) -> NDArray[np.float64] | None:
    try:
        chol = np.linalg.cholesky(hess)
    except np.linalg.LinAlgError:
        return None  # not a strict minimum: no honest Laplace interval exists
    inv_chol = np.linalg.inv(chol)
    cov = inv_chol.T @ inv_chol
    return np.asarray((cov + cov.T) / 2.0, dtype=np.float64)


def fit_goal_model(obs: Sequence[GoalObs], *, kind: str = "poisson", xi: float = 0.0,
                   penalty: float = 0.0, with_covariance: bool = True) -> GoalModel:
    """Weighted, optionally penalised MLE. ``obs`` weights already include the time decay."""
    if kind not in ("poisson", "dixon_coles"):
        raise ValueError(f"unknown goal model {kind!r}")
    if penalty < 0:
        raise ValueError("penalty must be >= 0")
    teams = sorted({o.home_id for o in obs} | {o.away_id for o in obs})
    if len(teams) < 3:
        raise ValueError("need at least three teams to identify attack and defence")
    index = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    gh = np.array([o.goals_home for o in obs], dtype=np.float64)
    ga = np.array([o.goals_away for o in obs], dtype=np.float64)
    d = _Data(
        hi=np.array([index[o.home_id] for o in obs], dtype=np.int64),
        ai=np.array([index[o.away_id] for o in obs], dtype=np.int64),
        gh=gh, ga=ga,
        w=np.array([o.weight for o in obs], dtype=np.float64),
        home_flag=np.array([0.0 if o.neutral else 1.0 for o in obs]),
        const=gammaln(gh + 1) + gammaln(ga + 1),
        m00=(gh == 0) & (ga == 0), m01=(gh == 0) & (ga == 1), m10=(gh == 1) & (ga == 0), m11=(gh == 1) & (ga == 1),
    )
    dc = kind == "dixon_coles"
    mean_goals = max(float((d.w * (gh + ga)).sum() / (2 * d.w.sum())), 0.1)
    theta0 = np.concatenate([[np.log(mean_goals), 0.25], np.zeros(n - 1), np.zeros(n - 1)])
    options = {"maxiter": 3000, "gtol": 1e-6}
    if dc:
        # Warm start from the Poisson optimum: the rho term only reshapes four
        # scores, and starting next to the answer keeps the optimiser away from
        # the region where tau would turn negative.
        base = minimize(_objective, theta0, args=(d, n, False, penalty), jac=True, method="BFGS", options=options)
        theta0 = np.concatenate([base.x, [0.0]])
    res = minimize(_objective, theta0, args=(d, n, dc, penalty), jac=True, method="BFGS", options=options)
    theta = np.asarray(res.x, dtype=np.float64)
    # BFGS often stops with "precision loss" a hair from the optimum. What
    # matters is that the gradient is flat there, per unit of weight.
    grad_ok = float(np.abs(res.jac).max()) < 1e-3 * max(1.0, float(d.w.sum()) / 100.0)
    template = GoalModel(kind, teams, 0.0, 0.0, np.zeros(n), np.zeros(n), 0.0, xi, len(obs), False, 0.0,
                         None, index, penalty)
    fitted = _unpack(template, theta)
    fitted.converged = bool(res.success) or grad_ok
    fitted.loglik = float(-res.fun)
    if with_covariance and fitted.converged:
        fitted.cov = _covariance(_hessian(theta, d, n, dc, penalty))
    return fitted
