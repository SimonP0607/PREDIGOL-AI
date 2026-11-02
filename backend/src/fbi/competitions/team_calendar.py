"""A team's calendar - every competition it plays - as of a moment (plan F4).

Two tables hold a team's matches: ``core.fixtures`` (the competitions PrediGol follows) and ``core.calendar_matches`` (the rest of what
the provider lists for the team, kept apart on purpose: see migration 0087). This module reads both *as of a moment* and answers the
questions rest and congestion are made of: when did the team last play, what and where, how many matches in the last two weeks, what
is its next match. It is a reader: it writes nothing, and nothing that trains a model or decides a pick imports it
(``tests/unit/test_calendar_isolation.py``).

AS OF A MOMENT. What a packet may say about the schedule is what was known when it was built:

* a match that kicked off before the moment is a fact whenever it was recorded (the backfilled history of a match played in 2022 is
  not "unknown in 2022");
* a match still to be played must have been *recorded* by then (``core.fixtures.created_at``, or a ``core.calendar_matches`` snapshot
  observed by then) - a fixture the provider announced later did not exist yet;
* a team's list is as complete as its last fetch (``core.calendar_fetches``) at or before the moment.

IS THE CALENDAR WHOLE? The provider's list for a team and season names every match of the season, those still to be played included, so a
list read recently is whole except for a match announced after it was read. ``TeamCalendar.state`` says so for one match: whole when the
team's list was read at most ``FRESH`` before the moment and no match of the last fortnight is still marked as to-be-played after its
kick-off (that match was played, or moved, and the list has not heard). Anything else - never read, read too long ago, a match that has
not been confirmed - is *not* whole, and the reader of the calendar (the packet, the page) must say rest is at most what it shows and
the matches at least. It is what the AI's packet did for every team until now.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "team-calendar-reader-1"
"""What a packet cites as the version of the reading: the as-of rules and the meaning of «whole» below."""
TABLES: Final = ("core.fixtures", "core.calendar_matches", "core.calendar_fetches")
"""What the reader reads (a packet names them as the sources of its schedule)."""

FRESH: Final = timedelta(hours=96)
"""A list read longer ago than this is not trusted to be whole: a team plays at most about every three days."""
BACK: Final = timedelta(days=60)
"""How far back a calendar is read before the match it is read for."""
AHEAD: Final = timedelta(days=7)
"""How far ahead of the match the next one is looked for."""
FORTNIGHT: Final = timedelta(days=14)
"""The window of 'matches in the last fortnight' (congestion) and of the matches that must have been confirmed."""
WEEK: Final = timedelta(days=7)
MONTH: Final = timedelta(days=30)
RECENT_N: Final = 3
"""How many of the matches played last are listed beside the count (the packet and the page say them by competition)."""
UPCOMING_N: Final = 2
"""How many of the matches still to come within the week are listed."""

Reason = Literal["never_fetched", "stale", "unconfirmed_match"]
"""Why a calendar is not whole."""

FOLLOWED: Final = "followed"
CALENDAR: Final = "calendar"

NOT_PLAYED_STATES: Final = frozenset({"cancelled", "postponed"})

FOLLOWED_SQL = """
SELECT f.provider_fixture_id, f.kickoff_at, f.status_group, (f.home_team_id = %(team)s) AS home,
       o.name AS opponent, c.name AS competition, c.country AS country, c.competition_type, cs.season, f.round,
       CASE WHEN f.home_team_id = %(team)s THEN r.goals_home ELSE r.goals_away END AS goals_for,
       CASE WHEN f.home_team_id = %(team)s THEN r.goals_away ELSE r.goals_home END AS goals_against
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams o ON o.id = CASE WHEN f.home_team_id = %(team)s THEN f.away_team_id ELSE f.home_team_id END
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.kickoff_at >= %(lo)s AND f.kickoff_at < %(hi)s
   AND (f.kickoff_at <= %(at)s OR f.created_at <= %(at)s)
 ORDER BY f.kickoff_at
"""
"""The followed matches of the window known at the moment (a match to come must have been recorded by then)."""

CALENDAR_SQL = """
WITH seen AS (
    SELECT DISTINCT ON (m.provider_fixture_id) m.*
      FROM core.calendar_matches m
     WHERE (m.home_provider_team_id = %(tp)s OR m.away_provider_team_id = %(tp)s)
       AND (m.observed_at <= %(at)s OR m.kickoff_at <= %(at)s)
     ORDER BY m.provider_fixture_id, (m.observed_at <= %(at)s) DESC, m.observed_at DESC)
SELECT s.provider_fixture_id, s.kickoff_at, s.status_group, (s.home_provider_team_id = %(tp)s) AS home,
       CASE WHEN s.home_provider_team_id = %(tp)s THEN s.away_name ELSE s.home_name END AS opponent,
       s.league_name AS competition, s.league_country AS country, c.competition_type, s.season, s.round,
       CASE WHEN s.home_provider_team_id = %(tp)s THEN s.goals_home ELSE s.goals_away END AS goals_for,
       CASE WHEN s.home_provider_team_id = %(tp)s THEN s.goals_away ELSE s.goals_home END AS goals_against
  FROM seen s
  LEFT JOIN core.competitions c ON c.provider_league_id = s.provider_league_id
 WHERE s.kickoff_at >= %(lo)s AND s.kickoff_at < %(hi)s
   AND NOT EXISTS (SELECT 1 FROM core.fixtures f WHERE f.provider_fixture_id = s.provider_fixture_id)
 ORDER BY s.kickoff_at
"""
"""The matches of the window the provider lists for the team that PrediGol does not follow, as they stood at the moment."""

FETCH_SQL = """
SELECT max(fetched_at) FROM core.calendar_fetches WHERE provider_team_id = %(tp)s AND fetched_at <= %(at)s
"""


@dataclass(frozen=True, slots=True)
class Match:
    """One match of a team's calendar, from the team's side."""

    provider_fixture_id: int
    kickoff_at: datetime
    status_group: str
    followed: bool
    """Is it one of the competitions PrediGol follows (``core.fixtures``)?"""
    home: bool
    opponent: str | None
    competition: str
    country: str | None
    competition_type: str | None
    """PrediGol's classification where it knows the competition (domestic_league, domestic_cup, continental, international); None
    for a competition it has never been told about."""
    season: int | None
    round: str | None
    goals_for: int | None
    goals_against: int | None

    @property
    def played(self) -> bool:
        return self.status_group == "finished"

    def result(self) -> str | None:
        """'2-1' from the team's side, once it is played and the score is known."""
        if not self.played or self.goals_for is None or self.goals_against is None:
            return None
        return f"{self.goals_for}-{self.goals_against}"


@dataclass(frozen=True, slots=True)
class CalendarState:
    """Whether the calendar can be taken as the team's whole schedule for one match, and why not when it cannot."""

    complete: bool
    reason: Reason | None
    """Why not (None: complete)."""
    fetched_at: datetime | None
    age_hours: float | None


@dataclass(frozen=True, slots=True)
class TeamCalendar:
    team_id: int
    at: datetime
    matches: tuple[Match, ...]
    fetched_at: datetime | None
    """The newest read of the team's list at or before ``at`` (None: never read by then)."""

    def played_before(self, kickoff: datetime) -> list[Match]:
        """Matches played before the moment and before ``kickoff``, newest first."""
        edge = min(kickoff, self.at)
        return sorted((m for m in self.matches if m.played and m.kickoff_at < edge), key=lambda m: m.kickoff_at,
                      reverse=True)

    def previous(self, kickoff: datetime) -> Match | None:
        done = self.played_before(kickoff)
        return done[0] if done else None

    def played_within(self, kickoff: datetime, span: timedelta) -> list[Match]:
        """Matches played in the ``span`` before ``kickoff`` (and before the moment)."""
        return [m for m in self.played_before(kickoff) if m.kickoff_at >= kickoff - span]

    def outside_within(self, kickoff: datetime, span: timedelta) -> int:
        """How many of the matches played in the ``span`` before ``kickoff`` are in a competition PrediGol does not follow:
        what the packet, the page and the rest count would not have seen without this calendar."""
        return sum(1 for m in self.played_within(kickoff, span) if not m.followed)

    def recent(self, kickoff: datetime, n: int = RECENT_N) -> list[Match]:
        """The ``n`` matches played last before ``kickoff`` (and the moment), newest first."""
        return self.played_before(kickoff)[:n]

    def upcoming(self, kickoff: datetime, n: int = UPCOMING_N, within: timedelta = AHEAD) -> list[Match]:
        """The first ``n`` matches still to be played after ``kickoff`` within ``within`` (a cancelled or postponed one is
        not), soonest first."""
        later = [m for m in self.matches if m.status_group not in NOT_PLAYED_STATES and not m.played
                 and kickoff < m.kickoff_at <= kickoff + within]
        return sorted(later, key=lambda m: (m.kickoff_at, m.provider_fixture_id))[:n]

    def next_after(self, kickoff: datetime, within: timedelta = AHEAD) -> Match | None:
        """The first match still to be played after ``kickoff`` within ``within`` (a cancelled or postponed one is not)."""
        coming = self.upcoming(kickoff, 1, within)
        return coming[0] if coming else None

    def rest_days(self, kickoff: datetime) -> float | None:
        previous = self.previous(kickoff)
        return None if previous is None else round((kickoff - previous.kickoff_at).total_seconds() / 86400, 1)

    def unconfirmed(self, kickoff: datetime) -> list[Match]:
        """Matches of the fortnight before ``kickoff`` that are still marked to-be-played although their kick-off has passed:
        the list has not heard whether they were played. Only matches the list is the source of are doubted - a followed
        match is kept up to date by the live pipeline."""
        edge = min(kickoff, self.at)
        return [m for m in self.matches if not m.followed and m.status_group == "scheduled"
                and edge - FORTNIGHT <= m.kickoff_at < edge]

    def state(self, kickoff: datetime) -> CalendarState:
        if self.fetched_at is None:
            return CalendarState(False, "never_fetched", None, None)
        age = (self.at - self.fetched_at).total_seconds() / 3600
        if self.at - self.fetched_at > FRESH:
            return CalendarState(False, "stale", self.fetched_at, round(age, 1))
        if self.unconfirmed(kickoff):
            return CalendarState(False, "unconfirmed_match", self.fetched_at, round(age, 1))
        return CalendarState(True, None, self.fetched_at, round(age, 1))


def _match(row: dict[str, Any], *, followed: bool) -> Match:
    return Match(
        provider_fixture_id=int(row["provider_fixture_id"]), kickoff_at=row["kickoff_at"],
        status_group=str(row["status_group"]), followed=followed, home=bool(row["home"]),
        opponent=row["opponent"], competition=str(row["competition"]), country=row["country"],
        competition_type=row["competition_type"], season=None if row["season"] is None else int(row["season"]),
        round=row["round"], goals_for=None if row["goals_for"] is None else int(row["goals_for"]),
        goals_against=None if row["goals_against"] is None else int(row["goals_against"]))


def load(conn: psycopg.Connection[Any], *, team_id: int, at: datetime, kickoff: datetime, back: timedelta = BACK,
         ahead: timedelta = AHEAD) -> TeamCalendar:
    """The team's matches from ``back`` before ``kickoff`` to ``ahead`` after it, as known at ``at``."""
    window = {"lo": kickoff - back, "hi": kickoff + ahead + timedelta(seconds=1), "at": at}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT provider_team_id FROM core.teams WHERE id = %s", (team_id,))
        team = cur.fetchone()
        followed = [_match(r, followed=True) for r in _all(cur, FOLLOWED_SQL, {**window, "team": team_id})]
        listed: list[Match] = []
        fetched_at: datetime | None = None
        if team is not None and int(team["provider_team_id"]) > 0:
            tp = int(team["provider_team_id"])
            listed = [_match(r, followed=False) for r in _all(cur, CALENDAR_SQL, {**window, "tp": tp})]
            cur.execute(FETCH_SQL, {"tp": tp, "at": at})
            row = cur.fetchone()
            fetched_at = None if row is None else row["max"]
    merged = sorted([*followed, *listed], key=lambda m: (m.kickoff_at, m.provider_fixture_id))
    return TeamCalendar(team_id=team_id, at=at, matches=tuple(merged), fetched_at=fetched_at)


def _all(cur: psycopg.Cursor[dict[str, Any]], sql: str, params: dict[str, Any]) -> Sequence[dict[str, Any]]:
    cur.execute(sql, params)
    return cur.fetchall()
