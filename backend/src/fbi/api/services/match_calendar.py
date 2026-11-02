"""The calendar of a match, read for the product and for the Admin Console's preview (plan F4). Reading only.

Each team's matches in every competition - the ones PrediGol follows and the rest of what the provider lists for the team - as they
stand now (``fbi.competitions.team_calendar``, the same reader the AI's packet uses, there cut at the packet's moment). This module
only lays them out: it computes no probability, reads no price and decides nothing. Unlike the packet, the page may say who the
opponent was and how a match ended: they are facts about the past, shown to a reader, not an input anyone computes with.

Who sees it. Off for users until the owner decides (``FBI_CALENDAR_USERS``, plan §22); the Admin Console's preview
(``preview=shadow``) does not depend on it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.contracts.match_calendar import CalendarMatch, MatchCalendar, TeamCalendarView
from fbi.api.envelope import Envelope, ok, unavailable
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_one
from fbi.competitions import team_calendar as tc
from fbi.core.clock import now
from fbi.core.env import environment

USERS_SWITCH: Final = "FBI_CALENDAR_USERS"
"""``FBI_CALENDAR_USERS=1`` lets every signed-in account see the calendar of a match. Off until the owner decides: the Admin
Console's preview does not depend on it. The API needs a restart to read it."""
RECENT_N: Final = 5
UPCOMING_N: Final = 3

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, f.home_team_id, f.away_team_id, h.name AS home_name, a.name AS away_name
  FROM core.fixtures f
  JOIN core.teams h ON h.id = f.home_team_id
  JOIN core.teams a ON a.id = f.away_team_id
 WHERE f.id = %(f)s
"""


def users_may_see() -> bool:
    return environment().get(USERS_SWITCH, "0").strip().lower() in {"1", "on", "true", "yes"}


def _entry(m: tc.Match, kickoff: datetime, *, ahead: bool) -> CalendarMatch:
    delta: timedelta = (m.kickoff_at - kickoff) if ahead else (kickoff - m.kickoff_at)
    return CalendarMatch(
        provider_fixture_id=m.provider_fixture_id, kickoff_at=m.kickoff_at, days=round(delta.total_seconds() / 86400, 1),
        competition=m.competition, competition_type=m.competition_type, country=m.country, round=m.round, home=m.home,
        opponent=m.opponent, result=m.result() if not ahead else None, followed=m.followed)


def _side(conn: Conn, team_id: int, name: str, *, at: datetime, kickoff: datetime) -> TeamCalendarView:
    cal = tc.load(conn, team_id=team_id, at=at, kickoff=kickoff)
    state = cal.state(kickoff)
    return TeamCalendarView(
        team_id=team_id, team=name, complete=state.complete, reason=state.reason,
        fetched_at=state.fetched_at, age_hours=state.age_hours, rest_days=cal.rest_days(kickoff),
        matches_last_7d=len(cal.played_within(kickoff, tc.WEEK)), matches_last_14d=len(cal.played_within(kickoff, tc.FORTNIGHT)),
        matches_last_30d=len(cal.played_within(kickoff, tc.MONTH)), outside_last_14d=cal.outside_within(kickoff, tc.FORTNIGHT),
        recent=[_entry(m, kickoff, ahead=False) for m in cal.recent(kickoff, RECENT_N)],
        upcoming=[_entry(m, kickoff, ahead=True) for m in cal.upcoming(kickoff, UPCOMING_N)])


def match_calendar(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None = None
                   ) -> Envelope[MatchCalendar | None]:
    """The calendar of a match; ``preview`` (the Admin Console) sees it whether or not users do."""
    fixture: dict[str, Any] | None = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    if not preview and not users_may_see():
        return unavailable(None, "The calendar of a match is not shown to users yet.")
    moment = at or now()
    kickoff: datetime = fixture["kickoff_at"]
    home = _side(conn, int(fixture["home_team_id"]), str(fixture["home_name"]), at=moment, kickoff=kickoff)
    away = _side(conn, int(fixture["away_team_id"]), str(fixture["away_name"]), at=moment, kickoff=kickoff)
    whole = home.complete and away.complete
    data = MatchCalendar(
        fixture_id=int(fixture["id"]), kickoff_at=kickoff, status_group=str(fixture["status_group"]), complete=whole,
        scope="provider_calendar" if whole else "tracked_competitions", home=home, away=away)
    return ok(data, data_as_of=max((s.fetched_at for s in (home, away) if s.fetched_at is not None), default=None))
