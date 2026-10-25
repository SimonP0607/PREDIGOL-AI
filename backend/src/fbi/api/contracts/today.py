"""Today, for Home (plan UX, A9): the matches around today with PrediGol's forecast labelled and one line of the reading, the
leagues suggested until the reader picks theirs, and why there is no pick today when there is none."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.reading import ReadingFact
from fbi.api.envelope import Section


class TodayForecast(Contract):
    outcome: Literal["home", "draw", "away"] = Field(description="The likely outcome of PrediGol's result forecast.")
    probability: Decimal = Field(description="Its probability, a share of one.")
    calibrated: bool = Field(description="False: the model's own number (labelled «sin calibrar»).")


class TodayMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str = Field(description="scheduled, live, finished, postponed, cancelled... as the data says it.")
    status: str | None = Field(description="The provider's short status (1H, HT, FT, PST...).")
    elapsed: int | None = Field(description="The minute, while it is live.")
    goals_home: int | None = Field(description="Live: the score now; finished: the final score; otherwise null.")
    goals_away: int | None
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    suggested: bool = Field(description="In the leagues suggested until the reader picks theirs (plan section 24: for "
                                        "Colombia, the Liga BetPlay, the national team, the Libertadores and the big "
                                        "European leagues).")
    forecast: TodayForecast | None = Field(description="Null when PrediGol has no forecast of it (or readers do not see it).")
    headline: ReadingFact | None = Field(description="One line of the reading: what the match is about (a final, a second "
                                                     "leg, what a side fights for). Null when nothing stands out.")
    has_reading: bool = Field(description="Whether the match's reading has its context (a packet) - the full reading at "
                                          "/matches/{id}/reading.")


class NoPick(Contract):
    day: date = Field(description="The product day (America/Bogota) the picks belong to.")
    state: Literal["picks", "reviewing", "none"] = Field(
        description="picks: the day has published picks; reviewing: PrediGol is still reading the day (before the set "
                    "is chosen, 06:00 Bogota at the latest) - no hour is promised; none: no match met the conditions.")
    stage: str | None = Field(description="none: the furthest stage the day's selections reached (data, market, model, "
                                          "calibration, value, risk, context, selection), from the published set's own "
                                          "funnel; null when there was no selection at all.")
    reason: str | None = Field(description="none: the commonest reason at that stage (e.g. non_positive_ev, "
                                           "odds_above_cap), or no_matches / no_qualified_candidates.")
    matches: int = Field(description="The day's matches of the followed competitions.")


class Today(Contract):
    day: date
    suggested: list[CompetitionBadge] = Field(description="The suggested leagues PrediGol follows, in the order they are "
                                                          "suggested.")
    suggested_team: str | None = Field(description="The national team suggested with them (Colombia).")
    matches: Section[list[TodayMatch]] = Field(description="From 48 hours ago (results) to 36 hours ahead, kick-off order: "
                                                           "the reader's own day is cut in the reader's time zone.")
    no_pick: Section[NoPick]
