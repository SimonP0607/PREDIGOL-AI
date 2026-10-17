"""How complete a live match's data is - so the richest matches lead the Live page.

The score is built only from what is stored for the match right now; a match the
provider barely covers sinks to the bottom and is shown compactly, instead of every
match weighing the same.
"""

from __future__ import annotations

from typing import Literal

WEIGHTS: dict[str, int] = {
    "score": 10, "minute": 10, "events": 15, "stats": 20,
    "lineups": 10, "players": 10, "live_odds": 15, "markets": 10,
}
RICH_FROM = 70
PARTIAL_FROM = 40
FULL_MARKETS = 10
"""An in-play book offering this many markets counts as full breadth; fewer count half."""


def completeness(*, goals_home: int | None, goals_away: int | None, elapsed: int | None, events: int,
                 stats: int, lineups: bool, players: bool, live_quotes: int,
                 markets_offered: int | None) -> tuple[int, Literal["rich", "partial", "basic"], dict[str, bool]]:
    has_score = goals_home is not None and goals_away is not None
    has_stats = stats > 0
    # A goalless match has no goal or card yet; with statistics flowing the event feed is
    # covering it, so an empty event list there is not missing data.
    goalless = has_score and goals_home == 0 and goals_away == 0
    signals = {
        "score": has_score,
        "minute": elapsed is not None,
        "events": events > 0 or (goalless and has_stats),
        "stats": has_stats,
        "lineups": lineups,
        "players": players,
        "live_odds": live_quotes > 0,
        "markets": (markets_offered or 0) > 0,
    }
    total = sum(WEIGHTS[k] for k, on in signals.items() if on and k != "markets")
    if markets_offered:
        total += WEIGHTS["markets"] if markets_offered >= FULL_MARKETS else WEIGHTS["markets"] // 2
    level: Literal["rich", "partial", "basic"] = (
        "rich" if total >= RICH_FROM else "partial" if total >= PARTIAL_FROM else "basic")
    return total, level, signals
