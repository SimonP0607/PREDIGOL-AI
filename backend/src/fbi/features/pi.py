"""pi-ratings (Constantinou & Fenton 2013): deterministic, versioned, walk-forward.

Each team carries two ratings, one for home and one for away matches, on a
scale that maps to an expected goal difference:

    g(R) = sign(R) * (b ** (|R| / c) - 1),   b = 10, c = 3

For home team H against away team A the predicted goal difference is
g(R_H_home) - g(R_A_away). After the match the error e = |observed - predicted|
is damped, psi(e) = c * log10(1 + e), so a 5-0 does not count five times a 1-0.
The side that did better than predicted moves up, the other down:

    R_H_home += lambda * psi      R_H_away += gamma * (change of R_H_home)
    R_A_away -= lambda * psi      R_A_home += gamma * (change of R_A_away)

with the paper's learning rates lambda = 0.035 and gamma = 0.7. These are fixed
a priori from the publication, not fitted on our data (fitting them on the
matches later used to evaluate them would leak the test into the features).
Changing any of them is a new version; history under the old one is kept.

Reference: A. C. Constantinou and N. E. Fenton (2013), "Determining the level of
ability of football teams by dynamic ratings based on the relative discrepancies
in scores between adversaries", Journal of Quantitative Analysis in Sports
9(1), 37-50, doi:10.1515/jqas-2012-0036.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PiParams:
    version: str = "pi-v1.0"
    learning_rate: float = 0.035
    cross_venue_rate: float = 0.7
    b: float = 10.0
    c: float = 3.0

    def as_dict(self) -> dict[str, object]:
        return {"version": self.version, "lambda": self.learning_rate, "gamma": self.cross_venue_rate,
                "b": self.b, "c": self.c}


def expected_gd(rating: float, params: PiParams) -> float:
    return math.copysign(params.b ** (abs(rating) / params.c) - 1.0, rating)


@dataclass
class PiBook:
    params: PiParams = field(default_factory=PiParams)
    home: dict[int, float] = field(default_factory=dict)
    away: dict[int, float] = field(default_factory=dict)

    def ratings(self, team_id: int) -> tuple[float, float]:
        return self.home.get(team_id, 0.0), self.away.get(team_id, 0.0)

    def predicted_gd(self, home_id: int, away_id: int) -> float:
        p = self.params
        return expected_gd(self.home.get(home_id, 0.0), p) - expected_gd(self.away.get(away_id, 0.0), p)

    def update(self, home_id: int, away_id: int, goals_home: int, goals_away: int) -> None:
        p = self.params
        predicted = self.predicted_gd(home_id, away_id)
        observed = goals_home - goals_away
        error = abs(observed - predicted)
        psi = p.c * math.log10(1.0 + error)
        sign = 1.0 if observed > predicted else -1.0 if observed < predicted else 0.0
        h_home, h_away = self.ratings(home_id)
        a_home, a_away = self.ratings(away_id)
        new_h_home = h_home + sign * psi * p.learning_rate
        new_a_away = a_away - sign * psi * p.learning_rate
        self.home[home_id] = new_h_home
        self.away[home_id] = h_away + (new_h_home - h_home) * p.cross_venue_rate
        self.away[away_id] = new_a_away
        self.home[away_id] = a_home + (new_a_away - a_away) * p.cross_venue_rate
