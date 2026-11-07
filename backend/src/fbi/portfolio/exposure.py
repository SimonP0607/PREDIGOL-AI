"""Exposure limits of the shadow portfolio (``exposure-v1``), in stake-v1's units (1 % of the bankroll).

Every limit is an ENGINEERING CHOICE, not a fit: each is written in terms of numbers the product already has (stake-v1's
caps, the day set's caps) so that one change of those moves these, and no number is copied here.

    match          MAX_MATCH          stake-v1's largest single cap (PICK_PREMIUM): one match never carries more than
                                      one premium single, however many of its selections are recommended
    team           MAX_TEAM           the same: a team is its match's main risk factor
    league         MAX_LEAGUE         the day set's two picks per competition, each at a full approved stake
    market_family  MAX_MARKET_FAMILY  three full approved stakes on one family (result, goals, ...)
    day            MAX_DAY            the day set's five picks, each at a full approved stake

The checks run in that order (``ORDER``) and say which limit binds: the one with the least room left, the first in
``ORDER`` on a tie. The stakes take the room in the day's order (``stakes.allocate``); a stake is held to the room,
rounded down to stake-v1's step.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from fbi.intel import decision
from fbi.intel import stake as staking
from fbi.portfolio.selection import Selection

VERSION: Final = "exposure-v1"

Limit = Literal["match", "team", "league", "market_family", "day"]
ORDER: Final[tuple[Limit, ...]] = ("match", "team", "league", "market_family", "day")

MAX_MATCH: Final = staking.CAPS["PICK_PREMIUM"]
MAX_TEAM: Final = staking.CAPS["PICK_PREMIUM"]
MAX_LEAGUE: Final = decision.MAX_PER_COMPETITION * staking.CAPS["APROBADO"]
MAX_MARKET_FAMILY: Final = 3 * staking.CAPS["APROBADO"]
MAX_DAY: Final = decision.MAX_PICKS * staking.CAPS["APROBADO"]
LIMITS: Final[Mapping[Limit, float]] = {"match": MAX_MATCH, "team": MAX_TEAM, "league": MAX_LEAGUE,
                                         "market_family": MAX_MARKET_FAMILY, "day": MAX_DAY}

FAMILY_OF: Final[Mapping[str, str]] = {"1X2": "result", "DC": "result", "AH": "result", "DNB": "result",
                                       "OU": "goals", "BTTS": "goals"}
"""The market family of a core market; any other market (GOALS_HALF, CORNERS, CARDS, ...) is a family of its own."""


def family_of(market_key: str) -> str:
    return FAMILY_OF.get(market_key, market_key)


def floor_step(units: float) -> float:
    """Down to stake-v1's step (never up)."""
    return max(0.0, math.floor(units / staking.STEP + 1e-9) * staking.STEP)


def keys_of(s: Selection) -> dict[Limit, tuple[Hashable, ...]]:
    return {"match": (s.fixture_id,), "team": (s.home_team_id, s.away_team_id), "league": (s.competition_id,),
            "market_family": (family_of(s.market_key),), "day": ("day",)}


@dataclass(frozen=True, slots=True)
class Check:
    asked: float
    allowed: float
    room: dict[Limit, float]
    """The room left under each limit before this stake."""
    binding: Limit | None
    """The limit that held the stake below what was asked; ``None`` when nothing did."""


@dataclass
class Book:
    """The exposure taken so far, per limit and key."""

    limits: Mapping[Limit, float] = field(default_factory=lambda: dict(LIMITS))
    used: dict[Limit, dict[Hashable, float]] = field(default_factory=lambda: {k: defaultdict(float) for k in ORDER})

    def room(self, s: Selection) -> dict[Limit, float]:
        keys = keys_of(s)
        return {k: min(self.limits[k] - self.used[k][key] for key in keys[k]) for k in ORDER}

    def check(self, s: Selection, units: float) -> Check:
        room = self.room(s)
        least = min(room.values())
        if units <= least + 1e-9:
            return Check(units, units, room, None)
        binding = next(k for k in ORDER if room[k] <= least + 1e-9)
        return Check(units, floor_step(least), room, binding)

    def check_day(self, units: float) -> Check:
        """A stake that only counts against the day (a parlay: its legs' matches are already held per selection)."""
        room: dict[Limit, float] = dict.fromkeys(ORDER, math.inf)
        room["day"] = self.limits["day"] - self.used["day"]["day"]
        if units <= room["day"] + 1e-9:
            return Check(units, units, room, None)
        return Check(units, floor_step(room["day"]), room, "day")

    def add(self, s: Selection, units: float) -> None:
        for k, keys in keys_of(s).items():
            for key in keys:
                self.used[k][key] += units

    def add_day(self, units: float) -> None:
        self.used["day"]["day"] += units

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "limits": dict(self.limits),
                "used": {k: {str(key): round(v, 4) for key, v in self.used[k].items() if v > 0} for k in ORDER}}
