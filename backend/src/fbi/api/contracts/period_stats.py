"""The statistics of a match by half (plan PM, PM-10-03): the match, the first half and the second half, for the statistics the
competition has built (``fbi.core.period_rules``). A figure the provider did not send is ``null``, never zero."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Period = Literal["total", "1h", "2h"]


class PeriodFigure(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(description="The statistic (a column of core.fixture_team_stats_period): corners, shots, fouls...")
    home: float | None = None
    away: float | None = None


class PeriodBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: Period
    figures: list[PeriodFigure]


class MatchPeriodStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: int
    built: list[str] = Field(description="The statistics this competition has built by half (>= 90 % of the matches asked, at least 5).")
    asked: int = Field(description="Matches of the competition whose halves were asked.")
    periods: list[PeriodBlock]
    as_of: datetime | None = Field(default=None, description="When the halves were read from the provider.")
    source: str = "api-football"
