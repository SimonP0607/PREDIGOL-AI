"""The player engine in SHADOW (``player-engine-v1``, IA-017): who starts, for how long, and what he does per 90 minutes.

Four steps, each a pure function of what was known at a moment (``fbi.players.history`` reads the database and keeps the facts in time
order; nothing later than the moment is ever in its view):

* ``availability``: the probability that a player starts and his expected minutes, from the recent squad sheets and minutes of his team
  (recency-weighted), the confirmed line-up when it was fetched by the moment (then the start is 0 or 1) and the absences the provider
  had reported by then. The start probability is calibrated on history, walk-forward.
* ``rates``: per-90 rates of goals, assists, shots, shots on target, fouls committed, cards and goalkeeper saves, shrunk towards the
  rate of his position (scaled by his team) and adjusted for the opponent.
* ``props``: the distribution of each prop as minutes x rate, a mixture over starting, coming off the bench and not playing, through
  the NB2 count engine of ``fbi.families.counts``; the goal share is conditioned on the team's expected goals when one is given.
* ``backtest``: the walk-forward evaluation per prop against a naive baseline, with every sample size stated.

The models produce the probabilities; no language model writes a number here. Each prop is its own family with its own status
(``fbi.players.families``) and none is ACTIVE: that API-Football prices a prop activates nothing. Nothing that decides, publishes, stakes
or serves the API imports this package (``tests/unit/test_players_isolation.py``), and it lives outside the model packages, so the model
code fingerprint does not move.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "player-engine-v1"
