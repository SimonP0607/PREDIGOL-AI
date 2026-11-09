"""Which fixture of ours an event of The Odds API is. A price on the wrong match is worse than none, so every doubt is a refusal.

Same rule as any second price source (``fbi.providers.odds_sources.OddsProvider``): the home team against the home team, the away team
against the away team (never flipped), both names alike enough, the kick-off within two hours, and exactly ONE fixture that agrees. Two
that agree, or none, is no match.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fbi.providers.football_data.names import similarity
from fbi.providers.the_odds_api.parse import SharpEvent

MAX_KICKOFF_GAP = timedelta(hours=2)
MIN_NAME_SIMILARITY = 0.8


@dataclass(frozen=True, slots=True)
class KnownFixture:
    provider_fixture_id: int
    home: str
    away: str
    kickoff_at: datetime


@dataclass(frozen=True, slots=True)
class FixtureMatch:
    fixture: KnownFixture | None
    reason: str
    """``matched``, ``no fixture agrees`` or ``several fixtures agree``: written down for the report of a run, never guessed around."""


def match_fixture(event: SharpEvent, fixtures: list[KnownFixture]) -> FixtureMatch:
    agreeing = [
        f for f in fixtures
        if abs(f.kickoff_at - event.commence_at) <= MAX_KICKOFF_GAP
        and similarity(f.home, event.home_team) >= MIN_NAME_SIMILARITY
        and similarity(f.away, event.away_team) >= MIN_NAME_SIMILARITY
    ]
    if len(agreeing) == 1:
        return FixtureMatch(agreeing[0], "matched")
    return FixtureMatch(None, "no fixture agrees" if not agreeing else "several fixtures agree")
