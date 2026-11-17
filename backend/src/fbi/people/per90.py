"""Observed per-90 rates of a player for his profile (plan 2026, AD-H07, ``IA-090``): what he DID, never a forecast.

A rate is the count of an action over the minutes of the matches in which that action was reported, times 90 - a match whose
sheet does not report the action (a NULL, not a 0) is left out with its minutes, so a league that does not record shots does
not lower anyone's shots. With fewer than ``MIN_MINUTES`` behind it the rate is not shown (``muestra_insuficiente``); with no
reported match at all it says so (``sin_datos``: «sin estadística individual»), never a 0.

The interval is the 95 % score interval of a Poisson rate - Wilson's construction for a count over an exposure:
``(x + z²/2 ± z·sqrt(x + z²/4)) / t`` with ``t`` the minutes / 90. It says how much the figure could move with the minutes
there are; it is not a prediction of the next match.

This is not the player engine (``fbi.players``, in shadow, which shrinks to a prior and adjusts for the opponent): nothing here
imports it, and nothing of its output reaches a profile.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

MIN_MINUTES: Final = 450
"""The contract's minimum: five full matches."""
WINDOW_DAYS: Final = 365
Z95: Final = 1.959963984540054
METRICS: Final = ("goals", "assists", "shots", "shots_on_target", "fouls_committed", "yellow_cards", "saves")
COLUMN: Final = {"goals": "goals", "assists": "assists", "shots": "shots_total", "shots_on_target": "shots_on",
                 "fouls_committed": "fouls_committed", "yellow_cards": "yellow_cards", "saves": "saves"}
"""Metric -> its column of ``core.fixture_player_stats``."""


@dataclass(frozen=True, slots=True)
class Line:
    """One appearance (minutes > 0): its minutes and the counts its sheet reports (None: not reported)."""

    minutes: int
    counts: dict[str, int | None]


@dataclass(frozen=True, slots=True)
class Rate:
    metric: str
    count: int
    matches: int
    """Appearances whose sheet reports the metric."""
    minutes: int
    """Their minutes."""
    value: float | None
    """None below ``MIN_MINUTES`` or without any reported match."""
    low: float | None
    high: float | None

    @property
    def sample_ok(self) -> bool:
        return self.value is not None


def score_interval(count: int, minutes: int, z: float = Z95) -> tuple[float, float]:
    """The score interval of a Poisson rate, per 90 minutes."""
    if minutes <= 0 or count < 0:
        raise ValueError("an interval needs minutes and a non-negative count")
    t = minutes / 90.0
    centre, half = count + z * z / 2.0, z * math.sqrt(count + z * z / 4.0)
    return max(0.0, (centre - half) / t), (centre + half) / t


def rate(metric: str, lines: Iterable[Line], *, min_minutes: int = MIN_MINUTES) -> Rate:
    count = matches = minutes = 0
    for line in lines:
        v = line.counts.get(metric)
        if v is None or line.minutes <= 0:
            continue
        count, matches, minutes = count + v, matches + 1, minutes + line.minutes
    if matches == 0 or minutes < min_minutes:
        return Rate(metric, count, matches, minutes, None, None, None)
    low, high = score_interval(count, minutes)
    return Rate(metric, count, matches, minutes, round(count * 90.0 / minutes, 2), round(low, 2), round(high, 2))


def rates(lines: Iterable[Line], metrics: Iterable[str] = METRICS, *, min_minutes: int = MIN_MINUTES) -> list[Rate]:
    kept = list(lines)
    return [rate(m, kept, min_minutes=min_minutes) for m in metrics]
