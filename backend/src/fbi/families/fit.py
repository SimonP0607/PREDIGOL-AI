"""Fit one count family on one competition (plan F10), with the engine PrediGol already trusts for goals.

A count of a team in a match - the goals of a half, its corners, its cards - follows the same story as its goals: how much the team makes
happen (attack) against how much the opponent lets happen (defence), plus a home effect. ``fbi.models.goals.fit_goal_model`` fits exactly that
by weighted, penalised maximum likelihood with a time decay; here it is borrowed as it is (not edited: editing it would renew the version of
every model) and what a count other than goals needs is added around it - the dispersion, and the rule about what the model may know.

THE RULE ABOUT WHAT THE MODEL MAY KNOW. A match is training material only once its result is known: ``OUTCOME_KNOWN_AFTER`` after the kick-off.
``fit_family`` applies it itself, so a caller cannot forget it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import numpy as np
from numpy.typing import ArrayLike, NDArray

from fbi.families.counts import MAX_COUNT, convolve, fit_dispersion, nb_pmf, normalised
from fbi.models.goals import GoalModel, GoalObs, fit_goal_model

OUTCOME_KNOWN_AFTER: Final = timedelta(hours=6)
"""A match is known this long after it kicked off: 90 minutes, the break, stoppage time, extra time and the penalties, then the provider."""
MIN_TRAIN: Final = 120
"""Fewer finished matches than this in one competition and no model is fitted (a prediction from nothing is worse than none)."""
MIN_TEAM_MATCHES: Final = 8
"""A team with fewer matches than this in the window is not predicted: its strength is still mostly the prior."""
DAY: Final = 86400.0


class NotEnoughHistoryError(ValueError):
    """The competition has too few finished matches in the window to fit a family."""


@dataclass(frozen=True, slots=True)
class Match:
    """One finished match as a family sees it: the count of the home side and of the away side (the two numbers a rule compares a line with)."""
    fixture_id: int
    kickoff_at: datetime
    home_id: int
    away_id: int
    home: int
    away: int
    neutral: bool = False


@dataclass(frozen=True, slots=True)
class Dispersion:
    home: float
    away: float
    total: float


NO_DISPERSION: Final = Dispersion(0.0, 0.0, 0.0)
"""Poisson on the three counts (the goals of a half)."""


@dataclass(frozen=True, slots=True)
class Prediction:
    """The distribution of each side's count and of the total, for one match that has not been played."""
    mean_home: float
    mean_away: float
    pmf_home: NDArray[np.float64]
    pmf_away: NDArray[np.float64]
    pmf_total: NDArray[np.float64]


@dataclass
class Fitted:
    measure: str
    model: GoalModel
    dispersion: Dispersion
    at: datetime
    n_train: int
    xi: float
    penalty: float
    matches_by_team: dict[int, int]

    def knows(self, home_id: int, away_id: int) -> bool:
        return all(self.matches_by_team.get(t, 0) >= MIN_TEAM_MATCHES for t in (home_id, away_id)) and self.model.knows(home_id) and self.model.knows(away_id)

    def means(self, home_id: int, away_id: int, *, neutral: bool = False) -> tuple[float, float]:
        return self.model.lambdas(home_id, away_id, neutral=neutral)

    def predict(self, home_id: int, away_id: int, *, neutral: bool = False) -> Prediction | None:
        """``None`` when either team is not known well enough."""
        if not self.knows(home_id, away_id):
            return None
        mh, ma = self.means(home_id, away_id, neutral=neutral)
        return prediction(mh, ma, self.dispersion)


def prediction(mean_home: float, mean_away: float, dispersion: Dispersion) -> Prediction:
    """The distributions of a match whose means are known: each side's count, and the total of the two (NB2 on the total when it is
    over-dispersed, the convolution of the sides when it is not)."""
    ph, pa = nb_pmf(mean_home, dispersion.home), nb_pmf(mean_away, dispersion.away)
    total = nb_pmf(mean_home + mean_away, dispersion.total, 2 * MAX_COUNT) if dispersion.total > 0.0 else convolve(ph, pa)
    return Prediction(mean_home, mean_away, normalised(ph), normalised(pa), normalised(total))


def known_at(m: Match) -> datetime:
    return m.kickoff_at + OUTCOME_KNOWN_AFTER


def fit_family(matches: Sequence[Match], *, measure: str, at: datetime, xi: float, penalty: float,
               dispersion: Dispersion | None = None) -> Fitted:
    """Fit ``measure`` on the matches of ONE competition that were already known at ``at``.

    ``dispersion=None`` estimates it on the model's own training window, which is a little too small (see ``fit_dispersion``); the walk-forward
    evaluation passes the one it measured on out-of-sample predictions.
    """
    train = [m for m in matches if known_at(m) <= at]
    if len(train) < MIN_TRAIN:
        raise NotEnoughHistoryError(f"{len(train)} finished matches known at {at:%Y-%m-%d}, {MIN_TRAIN} are needed")
    weights = [math.exp(-xi * max(0.0, (at - m.kickoff_at).total_seconds() / DAY)) for m in train]
    obs = [GoalObs(m.home_id, m.away_id, m.home, m.away, w, m.neutral) for m, w in zip(train, weights, strict=True)]
    model = fit_goal_model(obs, kind="poisson", xi=xi, penalty=penalty, with_covariance=False)
    by_team: dict[int, int] = {}
    for m in train:
        by_team[m.home_id] = by_team.get(m.home_id, 0) + 1
        by_team[m.away_id] = by_team.get(m.away_id, 0) + 1
    if dispersion is None:
        mus = [model.lambdas(m.home_id, m.away_id, neutral=m.neutral) for m in train]
        mh, ma = np.array([x[0] for x in mus]), np.array([x[1] for x in mus])
        yh, ya = np.array([m.home for m in train], dtype=float), np.array([m.away for m in train], dtype=float)
        w = np.array(weights)
        dispersion = Dispersion(fit_dispersion(yh, mh, w), fit_dispersion(ya, ma, w), fit_dispersion(yh + ya, mh + ma, w))
    return Fitted(measure, model, dispersion, at, len(train), xi, penalty, by_team)


def estimate_dispersion(y_home: ArrayLike, mu_home: ArrayLike, y_away: ArrayLike, mu_away: ArrayLike) -> Dispersion:
    """The dispersion of the two sides and of the total from OUT-OF-SAMPLE predictions."""
    yh, ya = np.asarray(y_home, dtype=float), np.asarray(y_away, dtype=float)
    mh, ma = np.asarray(mu_home, dtype=float), np.asarray(mu_away, dtype=float)
    return Dispersion(fit_dispersion(yh, mh), fit_dispersion(ya, ma), fit_dispersion(yh + ya, mh + ma))
