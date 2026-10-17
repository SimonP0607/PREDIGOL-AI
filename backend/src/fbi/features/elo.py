"""Elo V2: deterministic, versioned, walk-forward.

The update is the World Football Elo form - K * G * (W - We) - with the
goal-difference multiplier G from eloratings.net:

    G = 1            if |goal difference| <= 1
    G = 1.5          if |goal difference| == 2
    G = (11 + gd)/8  if |goal difference| >= 3

Parameters are fixed a priori from the literature, not fitted on our data: a
parameter chosen by looking at how well it predicts matches that are then
used to evaluate it is the textbook way to leak the future into a backtest.
Changing any of them is a new version; history under the old version is kept.

The update is zero-sum within a match: what one side gains the other loses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EloParams:
    version: str = "elo-v2.0"
    initial: float = 1500.0
    k: float = 20.0
    home_advantage: float = 65.0
    """Rating points added to the home side's expectation; not applied at a neutral venue."""

    def as_dict(self) -> dict[str, object]:
        return {"version": self.version, "initial": self.initial, "k": self.k,
                "home_advantage": self.home_advantage, "margin": "eloratings.net G"}


def expected_score(rating: float, opponent: float, *, advantage: float = 0.0) -> float:
    """Probability-like expected score of ``rating`` against ``opponent``."""
    return float(1.0 / (1.0 + 10.0 ** ((opponent - (rating + advantage)) / 400.0)))


def margin_multiplier(goal_difference: int) -> float:
    gd = abs(goal_difference)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


@dataclass(frozen=True, slots=True)
class EloUpdate:
    home_before: float
    home_after: float
    away_before: float
    away_after: float
    expected_home: float
    actual_home: float
    k: float
    multiplier: float


@dataclass
class EloBook:
    params: EloParams = field(default_factory=EloParams)
    ratings: dict[int, float] = field(default_factory=dict)

    def rating(self, team_id: int) -> float:
        return self.ratings.get(team_id, self.params.initial)

    def update(self, home_id: int, away_id: int, goals_home: int, goals_away: int, *, neutral: bool) -> EloUpdate:
        rh, ra = self.rating(home_id), self.rating(away_id)
        advantage = 0.0 if neutral else self.params.home_advantage
        eh = expected_score(rh, ra, advantage=advantage)
        wh = 1.0 if goals_home > goals_away else 0.5 if goals_home == goals_away else 0.0
        g = margin_multiplier(goals_home - goals_away)
        delta = self.params.k * g * (wh - eh)
        self.ratings[home_id] = rh + delta
        self.ratings[away_id] = ra - delta
        return EloUpdate(rh, rh + delta, ra, ra - delta, eh, wh, self.params.k, g)
