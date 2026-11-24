"""Which competitions and statistics by half are built (plan PM, PM-05-01, decision DM-13): the rule the probe of PM-01-05 closed with.

A statistic of a competition is **built** when, of the matches of the competition whose halves were asked, at least ``BUILD_SHARE`` carry
that statistic - the figure of the match and of both halves, for both teams - and at least ``MIN_SAMPLE`` were asked. Anything less is not
built, however close: the probe's rule is not lowered. A competition with fewer than ``MIN_SAMPLE`` matches asked has no decision yet (it
is in *probation*: the closing pass asks it until it has five); a competition with five or more and no statistic built is *closed* (it
is not asked again). The share is over every match asked, not only those that answered: a match whose answer lacked the halves counts
against every statistic.

Pure: no database, no clock, no environment. ``scripts.coverage_probe`` (PM-01-05) holds the same two numbers; a test holds them equal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

BUILD_SHARE: Final = 0.90
"""DM-13 and the PM-01-05 report: 90 % of the matches asked."""
MIN_SAMPLE: Final = 5
"""Matches asked a competition needs before it is decided."""

STATS: Final[tuple[str, ...]] = (
    "shots", "shots_on_target", "shots_off_target", "shots_blocked", "shots_inside_box", "shots_outside_box", "corners", "fouls",
    "offsides", "yellow_cards", "red_cards", "saves", "possession_pct", "passes", "passes_accurate", "expected_goals",
)
"""The statistics of ``core.fixture_team_stats_period`` (a test holds them equal to ``fbi.providers.api_football.period_stats``)."""

Gate = Literal["probation", "build", "closed"]


@dataclass(frozen=True, slots=True)
class StatDecision:
    stat: str
    asked: int
    filled: int
    build: bool

    @property
    def share(self) -> float | None:
        return self.filled / self.asked if self.asked else None


def decide(asked: int, filled: Mapping[str, int]) -> dict[str, StatDecision]:
    """The decision of each statistic of one competition: ``filled[stat]`` of ``asked`` matches carry it in both halves for both teams."""
    return {stat: StatDecision(stat, asked, filled.get(stat, 0),
                               asked >= MIN_SAMPLE and filled.get(stat, 0) * 100 >= round(BUILD_SHARE * 100) * asked)
            for stat in STATS}


def gate(asked: int, filled: Mapping[str, int]) -> Gate:
    """What the closing pass and the fill do with a competition: ask it while it has no decision (``probation``), ask it when at least one
    statistic is built (``build``), leave it alone when it has a decision and none is built (``closed``)."""
    if asked < MIN_SAMPLE:
        return "probation"
    return "build" if any(d.build for d in decide(asked, filled).values()) else "closed"


def built(asked: int, filled: Mapping[str, int], stat: str) -> bool:
    """Whether ``stat`` of a competition is built: the only question a reader of the data by half asks before showing a figure."""
    return stat in STATS and decide(asked, filled)[stat].build
