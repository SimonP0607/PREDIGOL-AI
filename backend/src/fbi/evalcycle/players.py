"""The cycle's one door to the player engine (``player-engine-v1``, IA-108): the men of each side as E1 knew them, and a player's prop.

``inputs`` turns the estimated starters of a match (``lineup-estimate-v1``: what ``fbi.shadowjobs.lineup_estimate.estimate_fixture``
reads as of the moment, with the engine's history of both teams) into the inputs of the dependency table (``dependency.PlayerInput``):
each man's start and bench probabilities and minutes, his goal rate per 90 against this opponent (``fbi.players.rates.player_rate``) and
the rate of a replacement at his position in his team (``position_rate`` x ``team_factor``: the prior the rate is shrunk to). Nothing
here reads the database or a clock; no model of language computes anything.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fbi.evalcycle.dependency import PlayerInput
from fbi.players import VERSION as MODEL
from fbi.players import lineup_estimate, props, rates

GOALS = "goals"
ESTIMATE_VERSION = lineup_estimate.VERSION
__all__ = ["ESTIMATE_VERSION", "MODEL", "inputs", "prop_over"]


def inputs(doc: Mapping[str, Any], *, at: datetime) -> list[PlayerInput]:
    """Every estimated man of both sides with his goal rate (``doc``: ``estimate_fixture``'s answer). Pure."""
    h = doc["history"]
    fx = doc["fixture"]
    out: list[PlayerInput] = []
    for side, opponent in (("home", fx.away_team_id), ("away", fx.home_team_id)):
        block = doc["sides"][side]
        team = int(block["team_id"])
        for e in block["estimates"]:
            r = rates.player_rate(h, e.provider_player_id, GOALS, at=at, team_id=team, opponent_id=opponent, position=e.position)
            replacement = rates.position_rate(h, GOALS, e.position) * rates.team_factor(h, team, GOALS)
            out.append(PlayerInput(e.provider_player_id, side, e.position, e.p_start, e.p_sub, e.minutes_start, e.minutes_sub,
                                   r.per90, replacement, e.absence_status))
    return out


def prop_over(per90: float, phi: float, *, p_start: float, minutes_start: float, p_sub: float = 0.0, minutes_sub: float = 0.0,
              line: float = 0.5) -> float:
    """P(his count > line) with the player engine's mixture (``fbi.players.props``): not playing is a count of 0 (group «siempre»)."""
    return float(props.forecast("prop", per90, phi, [(p_start, minutes_start), (p_sub, minutes_sub)], [line]).over[line])
