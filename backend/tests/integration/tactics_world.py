"""A small world for the tactics tests (``fbi.intel.tactics``, plan F6): one league, four sides, the match to describe (T0 at home to T1)
and the matches the first two sides played before it, each with the facts the profile reads - the half-time score, the provider's list of
events, the squad sheets - and the ways those can go wrong: a list fetched only after the packet's moment, a list that does not give the
score, a match with no list, sheets the provider crossed, a sheet with ten men, a result recorded only after the moment.

The matches of T0 (every kick-off ``days`` before ``AT``), newest first:

    A  3  T0 home to T2   2-1  break 1-1   10' T2, 30' T0, subs 60' and 75', 88' T0          sheet 4-3-3, eleven S1
    G  1  T0 home to T3   4-0                       result recorded AFTER the moment: not in the sample at all
    H  6  T2 home to T0   1-1  break 0-0   50' T2, 70' T0, fetched AFTER the moment            no sheet
    B 10  T3 home to T0   0-2  break 0-1   20' T0, subs 46' and 66', 77' T0                    sheet 4-3-3, eleven S2
    C 17  T0 home to T3   1-1  break 1-0   20' T0, sub 65', 90' T3                             sheet 4-2-3-1, eleven S3
    D 24  T2 home to T0   1-0  break 1-0   40' T2, sub 60' T0                                  sheets CROSSED (the statistics say so)
    E 31  T0 home to T1   3-0  break 2-0   no list of events at all                            sheet 4-3-3, TEN men
    F 38  T0 home to T2   2-0              a list with one goal                                no sheet

and of T1: I (4 days, T1 home to T2, 0-0, a substitution at 70', sheet 5-4-1), J (11 days, T3 home to T1, 1-2: 10' T3, 50' T1, 85' T1)
and E.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from .conftest import Seed
from .helpers import scalar

AT = datetime(2034, 4, 12, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(hours=6)

S1 = list(range(100, 111))
S2 = [*range(100, 110), 112]
S3 = [*range(100, 109), 113, 114]

Event = tuple[int, str, str, str]
"""(minute, team side, type, detail)"""


def goal(minute: int, side: str, detail: str = "Normal Goal") -> Event:
    return (minute, side, "Goal", detail)


def sub(minute: int, side: str, n: int = 1) -> Event:
    return (minute, side, "subst", f"Substitution {n}")


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db = db
        self.cur = db.cursor()
        self.hash = seed.payload_hash
        self.n = 0
        self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                         "is_tracked) VALUES (98941, 'Tactics League', 'Colombia', 'league', 'club', 'domestic_league', true) "
                         "RETURNING id")
        comp = scalar(self.cur)
        self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, true) RETURNING id",
                         (comp,))
        self.season = int(scalar(self.cur))
        self.team: list[int] = []
        for i in range(4):
            self.cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (989400 + i, f"Tactics {i}"))
            self.team.append(int(scalar(self.cur)))
        self.f: dict[str, int] = {}

    def kickoff(self, days: int) -> datetime:
        return AT - timedelta(days=days)

    def match(self, key: str, days: int, home: int, away: int, result: tuple[int, int], *, ht: tuple[int, int] | None = None,
              settled: datetime | None = None) -> int:
        """A finished match ``days`` before AT between two of the sides (by index), its result recorded two hours after the kick-off."""
        self.n += 1
        ko = self.kickoff(days)
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                         "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                         (9894000 + self.n, self.season, self.team[home], self.team[away], ko))
        fid = int(scalar(self.cur))
        self.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, settled_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s)",
                         (fid, result[0], result[1], ht[0] if ht else None, ht[1] if ht else None, settled or ko + timedelta(hours=2)))
        self.f[key] = fid
        return fid

    def upcoming(self, home: int, away: int) -> int:
        self.n += 1
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                         "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'NS', 'scheduled') RETURNING id",
                         (9894000 + self.n, self.season, self.team[home], self.team[away], KICKOFF))
        self.f["U"] = int(scalar(self.cur))
        return self.f["U"]

    def events(self, key: str, events: list[Event], fetched: datetime | None = None) -> None:
        """The provider's list of events of a match, in order, fetched three hours after the kick-off unless said otherwise."""
        fid = self.f[key]
        when = fetched or self.kickoff_of(key) + timedelta(hours=3)
        for seq, (minute, side, kind, detail) in enumerate(events):
            self.cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, "
                             "payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, %s, %s, %s, %s)",
                             (fid, seq, minute, side, kind, detail, self.hash, when))

    def kickoff_of(self, key: str) -> datetime:
        row = self.db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (self.f[key],)).fetchone()
        assert row is not None
        out: datetime = row[0]
        return out

    def sheet(self, key: str, side: str, formation: str | None, players: list[int], coach: str | None = "Coach One",
              fetched: datetime | None = None) -> None:
        """A squad sheet: the formation, the coach and the starting eleven (``players``), fetched 50 minutes before the kick-off."""
        fid = self.f[key]
        when = fetched or self.kickoff_of(key) - timedelta(minutes=50)
        self.cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, coach_name, payload_hash, fetched_at) "
                         "VALUES (%s, %s, 'api-football', %s, %s, %s, %s)", (fid, side, formation, coach, self.hash, when))
        for pid in players:
            self.cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter) "
                             "VALUES (%s, %s, 'api-football', %s, true)", (fid, side, pid))

    def statistics(self, key: str, side: str, players: list[int], fetched: datetime | None = None) -> None:
        """The statistics of a match say these men played for ``side`` (the provider's statistics are right even when its sheets are not)."""
        fid = self.f[key]
        when = fetched or self.kickoff_of(key) + timedelta(hours=3)
        for pid in players:
            self.cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
                             "payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, 90, %s, %s)",
                             (fid, pid, side, self.hash, when))

    def build(self) -> dict[str, int]:
        """The whole world; returns the ids by key."""
        t0, t1, t2, t3 = 0, 1, 2, 3
        self.match("A", 3, t0, t2, (2, 1), ht=(1, 1))
        self.events("A", [goal(10, "away"), goal(30, "home"), sub(60, "home"), sub(62, "away"), sub(75, "home", 2), goal(88, "home")])
        self.sheet("A", "home", "4-3-3", S1)
        self.sheet("A", "away", "4-4-2", list(range(200, 211)), "Coach Two")
        self.match("G", 1, t0, t3, (4, 0), ht=(2, 0), settled=AT + timedelta(hours=1))
        self.match("H", 6, t2, t0, (1, 1), ht=(0, 0))
        self.events("H", [goal(50, "home"), goal(70, "away")], fetched=AT + timedelta(hours=2))
        self.match("B", 10, t3, t0, (0, 2), ht=(0, 1))
        self.events("B", [goal(20, "away"), sub(46, "away"), sub(66, "away", 2), goal(77, "away"), sub(80, "home")])
        self.sheet("B", "away", "4-3-3", S2)
        self.match("C", 17, t0, t3, (1, 1), ht=(1, 0))
        self.events("C", [goal(20, "home"), sub(65, "home"), goal(90, "away")])
        self.sheet("C", "home", "4-2-3-1", S3)
        self.match("D", 24, t2, t0, (1, 0), ht=(1, 0))
        self.events("D", [goal(40, "home"), sub(60, "away")])
        # the provider gave each team the other's eleven (and its formation went with them): T0's sheet, labelled away, lists T2's men
        theirs, ours = list(range(300, 311)), list(range(400, 411))
        self.sheet("D", "away", "5-3-2", theirs, "Coach One")
        self.sheet("D", "home", "4-3-3", ours, "Coach Two")
        self.statistics("D", "home", theirs)
        self.statistics("D", "away", ours)
        self.match("E", 31, t0, t1, (3, 0), ht=(2, 0))
        self.sheet("E", "home", "4-3-3", S1[:10])
        self.match("F", 38, t0, t2, (2, 0))
        self.events("F", [goal(15, "home")])
        self.match("I", 4, t1, t2, (0, 0), ht=(0, 0))
        self.events("I", [sub(70, "home")])
        self.sheet("I", "home", "5-4-1", list(range(500, 511)), "Coach Three")
        self.match("J", 11, t3, t1, (1, 2), ht=(1, 0))
        self.events("J", [goal(10, "home"), goal(50, "away"), goal(85, "away")])
        self.upcoming(t0, t1)
        return self.f
