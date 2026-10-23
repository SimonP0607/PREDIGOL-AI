"""A team's matches in EVERY competition (plan F4): ``/fixtures?team=&season=``, kept apart from the matches PrediGol follows.

``core.fixtures`` holds the competitions PrediGol follows, so the rest and the congestion read from it alone are *bounds*: a cup or a
continental tie it does not follow is not there. The provider lists all of a team's matches of a season in one request; this module asks
for it (a feed of ``fbi.ingestion.reference``, so it shares the daily budget, the live reserve and the record of every question) and
writes what it says into ``core.calendar_matches`` (change-only, one row per match and moment it changed) and ``core.calendar_fetches``
(the log of the questions). A match that ``core.fixtures`` already holds is not written twice: the followed matches keep their own,
richer table.

What is NOT done here, on purpose: nothing is created in ``core.competitions``, ``core.competition_seasons``, ``core.teams`` or
``core.fixtures`` for a competition PrediGol does not follow. The opponent of such a match is a name and a provider id in the calendar
row, nothing more. That is what makes it impossible for these matches to reach a model, an Elo or a pick (``tests/unit/test_calendar_isolation.py``).

Who is asked, and how often: the teams of the followed competitions that play within seven days, once per season they play in.
A team whose next match is within two days is asked about daily (a cup tie in midweek is what its rest depends on), within four days
every other day, and within seven days weekly. A team with no match in the next seven days is not asked: its calendar is read when its
next match comes near. On 22 Oct 2026 that is 1,509 (team, season) pairs, about 1,100 requests a day once all are read, of a budget of
60,000 (the busiest of the last seven days spent 22,395).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.ingestion.fixtures import status_group
from fbi.ingestion.reference import (
    Target,
    _int,
    _map,
    _response,
    _small,
    _text,
    write_row_if_changed,
)
from fbi.providers.api_football.normalize import canonical_status

NORMALIZER_VERSION = "team-calendar-1"

HORIZON = timedelta(days=7)
"""A team is asked about when its next followed match is within this."""
EVERY_NEAR = timedelta(hours=20)
"""Next match within two days: about daily (just under a day, so a read that ran a little late is not pushed a whole day later)."""
EVERY_SOON = timedelta(hours=44)
"""Next match within four days: about every other day."""
EVERY_WEEK = timedelta(days=7) - timedelta(hours=1)
"""Next match within seven days: weekly."""
NEAR = timedelta(days=2)
SOON = timedelta(days=4)

TARGETS_SQL = """
SELECT t.provider_team_id, cs.season, min(f.kickoff_at) AS next_kickoff
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
 WHERE c.is_tracked AND cs.is_current AND f.status_group = 'scheduled'
   AND f.kickoff_at > %(at)s AND f.kickoff_at <= %(at)s + %(horizon)s AND t.provider_team_id > 0
 GROUP BY t.provider_team_id, cs.season
 ORDER BY next_kickoff, t.provider_team_id, cs.season
"""
"""One row per (team, season) with a followed match in the next seven days, the soonest to play first."""

FOLLOWED_SQL = "SELECT provider_fixture_id FROM core.fixtures WHERE provider_fixture_id = ANY(%(ids)s)"


def every_for(next_kickoff: datetime, at: datetime) -> timedelta:
    """How long an answer about a team stays fresh, by how close its next match is."""
    ahead = next_kickoff - at
    if ahead <= NEAR:
        return EVERY_NEAR
    if ahead <= SOON:
        return EVERY_SOON
    return EVERY_WEEK


def targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    """Each (team, season) with a followed match within the horizon, the soonest to play first."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TARGETS_SQL, {"at": at, "horizon": HORIZON})
        rows = cur.fetchall()
    return [Target(f"team:{tp}:{season}", {"team": int(tp), "season": int(season)}, every_for(kickoff, at),
                   {"team": int(tp), "season": int(season)})
            for tp, season, kickoff in rows]


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """One match of a team's list, as the provider says it."""

    provider_fixture_id: int
    kickoff_at: datetime
    status_short: str
    status_group: str
    provider_league_id: int
    league_name: str
    league_country: str | None
    season: int
    round: str | None
    home_provider_team_id: int
    home_name: str
    away_provider_team_id: int
    away_name: str
    goals_home: int | None
    goals_away: int | None

    def values(self) -> dict[str, Any]:
        """The columns of ``core.calendar_matches`` that can change from one reading to the next (everything but the key)."""
        return {
            "kickoff_at": self.kickoff_at, "status_short": self.status_short, "status_group": self.status_group,
            "provider_league_id": self.provider_league_id, "league_name": self.league_name,
            "league_country": self.league_country, "season": self.season, "round": self.round,
            "home_provider_team_id": self.home_provider_team_id, "home_name": self.home_name,
            "away_provider_team_id": self.away_provider_team_id, "away_name": self.away_name,
            "goals_home": self.goals_home, "goals_away": self.goals_away,
        }


def _when(value: Any) -> datetime | None:
    """The provider's ISO date with its offset, as an aware UTC moment (a date without an offset is not a moment: None)."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo is not None else None


def entries(body: Mapping[str, Any]) -> Iterator[CalendarEntry]:
    """The matches of a ``/fixtures`` answer. An entry that cannot be read whole is left out (never half-written)."""
    for entry in _response(body):
        if not isinstance(entry, Mapping):
            continue
        fixture, league = _map(entry.get("fixture")), _map(entry.get("league"))
        teams, goals = _map(entry.get("teams")), _map(entry.get("goals"))
        home, away = _map(teams.get("home")), _map(teams.get("away"))
        fixture_id, league_id, season = _int(fixture.get("id")), _int(league.get("id")), _int(league.get("season"))
        home_id, away_id = _int(home.get("id")), _int(away.get("id"))
        kickoff = _when(fixture.get("date"))
        league_name, home_name, away_name = _text(league.get("name")), _text(home.get("name")), _text(away.get("name"))
        if (fixture_id is None or fixture_id <= 0 or league_id is None or season is None or kickoff is None
                or home_id is None or away_id is None or home_id <= 0 or away_id <= 0 or home_id == away_id
                or league_name is None or home_name is None or away_name is None):
            continue
        short = canonical_status(_map(fixture.get("status")).get("short"))
        yield CalendarEntry(
            provider_fixture_id=fixture_id, kickoff_at=kickoff, status_short=short, status_group=status_group(short),
            provider_league_id=league_id, league_name=league_name, league_country=_text(league.get("country")),
            season=season, round=_text(league.get("round")), home_provider_team_id=home_id, home_name=home_name,
            away_provider_team_id=away_id, away_name=away_name, goals_home=_small(goals.get("home")),
            goals_away=_small(goals.get("away")))


def apply(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str, observed: datetime) -> int:
    """Write what a team's list says: the matches PrediGol does not follow (change-only), and the log of the question.

    Returns the rows added to ``core.calendar_matches``. An empty or unreadable answer still leaves its line in the log: "asked and
    nothing came" is not "never asked"."""
    parsed = list(entries(body))
    team, season = int(t.params["team"]), int(t.params["season"])
    with conn.cursor() as cur:
        followed: set[int] = set()
        if parsed:
            cur.execute(FOLLOWED_SQL, {"ids": [e.provider_fixture_id for e in parsed]})
            followed = {int(row[0]) for row in cur.fetchall()}
        added = 0
        for e in parsed:
            if e.provider_fixture_id in followed:
                continue
            added += write_row_if_changed(cur, "core.calendar_matches", {"provider_fixture_id": e.provider_fixture_id},
                                          e.values(), observed_at=observed, payload_hash=payload_hash,
                                          version=NORMALIZER_VERSION)
        cur.execute(
            "INSERT INTO core.calendar_fetches (provider_team_id, season, fetched_at, matches, followed, rows_added, "
            "payload_hash, normalizer_version) VALUES (%(tp)s, %(s)s, %(at)s, %(n)s, %(f)s, %(a)s, %(h)s, %(v)s) "
            "ON CONFLICT DO NOTHING",
            {"tp": team, "s": season, "at": observed, "n": len(parsed), "f": len(followed), "a": added, "h": payload_hash,
             "v": NORMALIZER_VERSION})
    return added
