"""Rest and congestion as they really were: counted from every match a team played, in any competition (plan F4.4, definitions ``rest-v1``).

Pure. It takes the calendar of a team (``fbi.competitions.team_calendar``, already loaded) and one kick-off and returns the numbers the
experiment of ``fbi.research.rest_ab`` is made of. It reads nothing and writes nothing, and nothing that trains a model or decides a pick
imports it (``tests/unit/test_calendar_isolation.py``): the experiment gets the numbers, never the calendar.

WHAT "REAL" MEANS HERE. The rest PrediGol's models read is the days since the team's previous match *in the competitions PrediGol follows*
(``features.engine``: "days since the team's previous match in the dataset"). The real rest also counts the cup tie, the continental night
and the friendly that the provider lists for the team. ``SideRest.rest_days_tracked`` is the first, ``rest_days`` the second, and the
difference between them is what the calendar adds.

WHOLE, LOOKING BACK. A packet or a page asks whether a calendar was whole *when it was made* (``TeamCalendar.state``: read within 96 hours,
nothing left unconfirmed). An experiment asks it of matches already played, and the list it reads was read afterwards, which is better, not
worse: the past of a list does not change (a match announced late and played before the match under study is in it). So the rule of
``rest-v1`` is, for one side of one finished match:

* the team's list was read AFTER the match (``fetched_at >= kickoff``): it shows how that stretch of the season ended;
* no match of the fortnight before it is left marked to-be-played (the list never heard whether it was played);
* a previous match was played within the sixty days before it (rest is defined).

The rule does not see a gap that sits in a season the feed does not read (a match of the previous season just before a new one), which is why the
first match of a team's season has to be read with care; the numbers of the sample say how often a side falls out of it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fbi.competitions.team_calendar import BACK, FORTNIGHT, MONTH, WEEK, TeamCalendar
from fbi.research.rest_ab import Incomplete, SideRest

VERSION: Final = "rest-v1"
"""The meaning of every number below and of «whole»; a change is a new version."""


def _days(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86400


def side_rest(cal: TeamCalendar, kickoff: datetime) -> SideRest:
    """The rest and congestion of one side at ``kickoff``, from the matches it had played by then (newest first), whichever the competition."""
    played = [m for m in cal.played_before(kickoff) if kickoff - m.kickoff_at <= BACK]
    last = played[0] if played else None
    last_followed = next((m for m in played if m.followed), None)
    last_outside = next((m for m in played if not m.followed), None)
    ahead = cal.next_after(kickoff)

    reason: Incomplete | None = None
    if cal.fetched_at is None or cal.fetched_at < kickoff:
        reason = "not_read_after_the_match"
    elif cal.unconfirmed(kickoff):
        reason = "unconfirmed_match"
    elif last is None:
        reason = "no_previous_match"

    def within(span_days: float) -> list[bool]:
        return [m.followed for m in played if _days(kickoff, m.kickoff_at) <= span_days]

    week, fortnight, month = within(WEEK.days), within(FORTNIGHT.days), within(MONTH.days)
    return SideRest(
        rest_days=None if last is None else _days(kickoff, last.kickoff_at),
        rest_days_tracked=None if last_followed is None else _days(kickoff, last_followed.kickoff_at),
        rest_days_outside=None if last_outside is None else _days(kickoff, last_outside.kickoff_at),
        played_7d=len(week), played_14d=len(fortnight), played_30d=len(month),
        outside_14d=sum(1 for followed in fortnight if not followed),
        next_gap_days=None if ahead is None else _days(ahead.kickoff_at, kickoff),
        next_competition_type=None if ahead is None else ahead.competition_type,
        whole=reason is None, reason=reason)
