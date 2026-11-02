"""The calendar of a match: what each team has played and has coming, in EVERY competition (plan F4).

The Match Center follows the competitions PrediGol follows. A team plays more than those: a cup tie, a continental night, a friendly.
This answer adds them, from the list the provider gives for the team, and says how sure it is: ``complete`` is true only for a side
whose list was read lately and has no match left unconfirmed; otherwise the figures are what PrediGol could see (rest is at most what
it shows, the matches at least), and ``reason`` says why. It is context: no price, no probability, nothing a pick is made of.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

Reason = Literal["never_fetched", "stale", "unconfirmed_match"]
Scope = Literal["provider_calendar", "tracked_competitions"]


class CalendarMatch(Contract):
    """One match of a team: when, where, against whom and in which competition."""

    provider_fixture_id: int
    kickoff_at: datetime
    days: float = Field(description="Days before the match of the page (a match already played) or after it (a match to come).")
    competition: str
    competition_type: str | None = Field(
        description="PrediGol's classification where it knows the competition (domestic_league, domestic_cup, continental, "
                    "international); null for a competition it has never been told about.")
    country: str | None
    round: str | None
    home: bool = Field(description="Was the team at home.")
    opponent: str | None
    result: str | None = Field(description="From the team's side ('2-1'), once the match is played and its score is known.")
    followed: bool = Field(description="One of the competitions PrediGol follows (the rest are known only from the team's list).")


class TeamCalendarView(Contract):
    team_id: int
    team: str
    complete: bool = Field(description="True: the list was read lately and nothing is left unconfirmed, so these are the team's "
                                       "real figures. False: they are what PrediGol could see (rest is at most, matches at least).")
    reason: Reason | None = Field(description="Why it is not complete: the list was never read, was read too long ago, or a match "
                                              "that should have been played is still marked to be played.")
    fetched_at: datetime | None = Field(description="When the team's list was last read (null: never).")
    age_hours: float | None
    rest_days: float | None = Field(description="Days between the last match played and this one (null: none known).")
    matches_last_7d: int
    matches_last_14d: int
    matches_last_30d: int
    outside_last_14d: int = Field(description="Of the matches of the last fortnight, those in a competition PrediGol does not "
                                              "follow: the ones its other pages would not have counted.")
    recent: list[CalendarMatch] = Field(description="The last matches played before this one, newest first.")
    upcoming: list[CalendarMatch] = Field(description="The next matches within the week after this one, soonest first.")


class MatchCalendar(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    complete: bool = Field(description="Both sides are complete.")
    scope: Scope = Field(description="provider_calendar: both sides come from the team's whole list. tracked_competitions: "
                                     "at least one side is only what PrediGol follows.")
    home: TeamCalendarView
    away: TeamCalendarView
