"""PM-05-08: the facts of a match's «importance» on a real database, as of a moment - the last match day of a season and the one before
it, the home and away places from the stored table taken before kick-off (never one taken after, never a fixture created later), a
knock-out round, and the owner's command."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.competitions import importance as imp
from tests.integration.helpers import scalar
from tests.integration.test_competition_phases_db import rr

pytestmark = pytest.mark.integration
START = datetime(2026, 3, 1, 20, tzinfo=UTC)
WEEK = timedelta(days=7)
CREATED = datetime(2026, 1, 10, tzinfo=UTC)


class Season:
    def __init__(self, db: psycopg.Connection[Any], league: int) -> None:
        self.db = db
        self.fx = league * 1000
        with db.cursor() as cur:
            cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                        "VALUES (%s, %s, 'league', 'club', 'domestic_league') RETURNING id", (league, f"L{league}"))
            comp = scalar(cur)
            cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) RETURNING id",
                        (comp,))
            self.cs = scalar(cur)
            self.team: dict[int, int] = {}
            for n in range(1, 5):
                cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (league * 10 + n, f"T{n}"))
                self.team[n] = scalar(cur)

    def match(self, label: str, home: int, away: int, ko: datetime, *, created: datetime = CREATED) -> int:
        self.fx += 1
        with self.db.cursor() as cur:
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                        "round, status_short, status_group, created_at) VALUES (%s, %s, %s, %s, %s, %s, 'NS', 'scheduled', %s) RETURNING id",
                        (self.fx, self.cs, self.team[home], self.team[away], ko, label, created))
            return scalar(cur)

    def double_round_robin(self) -> dict[int, int]:
        """Six match days; returns the fixture id of each day's first match."""
        first: dict[int, int] = {}
        pairs = rr(list(self.team))
        for d, day_pairs in enumerate(pairs + [[(a, h) for h, a in p] for p in pairs], 1):
            for k, (h, a) in enumerate(day_pairs):
                fid = self.match(f"Regular Season - {d}", h, a, START + (d - 1) * WEEK + timedelta(minutes=k))
                first.setdefault(d, fid)
        return first

    def snapshot(self, at: datetime, home: dict[int, tuple[int, int, int, int, int]], away: dict[int, tuple[int, int, int, int, int]]) -> None:
        """home/away: team -> (wins, draws, losses, goals for, goals against) of that side."""
        with self.db.cursor() as cur:
            for rank, n in enumerate(sorted(self.team), 1):
                hw, hd, hl, hgf, hga = home[n]
                aw, ad, al, agf, aga = away[n]
                cur.execute(
                    'INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, wins, draws, losses, '
                    'goals_for, goals_against, "group", home_played, home_wins, home_draws, home_losses, home_goals_for, '
                    "home_goals_against, away_played, away_wins, away_draws, away_losses, away_goals_for, away_goals_against) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Regular Season', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (self.cs, self.team[n], at, rank, 3 * (hw + aw) + hd + ad, hw + hd + hl + aw + ad + al, hw + aw, hd + ad, hl + al,
                     hgf + agf, hga + aga, hw + hd + hl, hw, hd, hl, hgf, hga, aw + ad + al, aw, ad, al, agf, aga))


def team_of(db: psycopg.Connection[Any], fixture: int) -> tuple[int, int]:
    row = db.execute("SELECT home_team_id, away_team_id FROM core.fixtures WHERE id = %s", (fixture,)).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_the_last_match_day_and_the_home_and_away_places_as_of_kick_off(db: psycopg.Connection[Any]) -> None:
    s = Season(db, 99781)
    first = s.double_round_robin()
    ko6 = START + 5 * WEEK
    # before day 6: team 1 strong at home, team 4 strong away
    s.snapshot(ko6 - timedelta(days=2),
               home={1: (2, 1, 0, 6, 1), 2: (1, 1, 1, 3, 3), 3: (1, 0, 2, 2, 4), 4: (0, 1, 2, 1, 5)},
               away={1: (0, 1, 1, 1, 2), 2: (1, 0, 1, 2, 2), 3: (0, 1, 1, 1, 3), 4: (2, 0, 0, 4, 1)})
    # a snapshot after kick-off that would change everything: never read
    s.snapshot(ko6 + timedelta(hours=3),
               home=dict.fromkeys(s.team, (0, 0, 3, 0, 9)), away=dict.fromkeys(s.team, (3, 0, 0, 9, 0)))
    fid = first[6]
    home, away = team_of(db, fid)
    facts = imp.facts_of(db, fid, at=ko6 - timedelta(hours=1))
    assert facts is not None
    got = facts.as_json()
    assert got["version"] == imp.VERSION and got["stage"]["kind"] == "league" and got["stage"]["name"] == "Regular Season"
    assert got["match_days"] == {"match_day": 6, "last_published": 6, "after": 0, "is_last": True,
                                 "matches_left_after": {"home": 0, "away": 0}, "schedule": "publicado"}
    assert got["table_snapshot_at"] == (ko6 - timedelta(days=2)).isoformat()
    places = {s.team[n]: n for n in s.team}
    ht, at_ = got["home_table"], got["away_table"]
    assert ht["team_id"] == home and at_["team_id"] == away and ht["of"] == 4 and at_["of"] == 4
    expected_home = {1: 1, 2: 2, 3: 3, 4: 4}[places[home]]
    expected_away = {4: 1, 2: 2, 1: 3, 3: 4}[places[away]]
    assert (ht["position"], at_["position"]) == (expected_home, expected_away)

    # the day before the last: one day after it, one match left for each team
    five = imp.facts_of(db, first[5], at=START + 4 * WEEK - timedelta(hours=1))
    assert five is not None and five.match_days is not None
    assert (five.match_days.after, five.match_days.is_last, five.match_days.left_home, five.match_days.left_away) == (1, False, 1, 1)
    # no table taken before day 5: no place is said
    assert five.home_place is None and five.away_place is None


def test_a_fixture_created_after_the_moment_is_not_part_of_the_schedule(db: psycopg.Connection[Any]) -> None:
    s = Season(db, 99782)
    first = s.double_round_robin()
    # a seventh day announced later (a play-off for the title): unknown before it was created
    late = datetime(2026, 4, 20, tzinfo=UTC)
    s.match("Regular Season - 7", 1, 2, START + 6 * WEEK, created=late)
    before = imp.facts_of(db, first[6], at=late - timedelta(days=1))
    after = imp.facts_of(db, first[6], at=late + timedelta(days=1))
    assert before is not None and before.match_days is not None and before.match_days.is_last
    assert after is not None and after.match_days is not None and after.match_days.last_published == 7


def test_a_knock_out_round_says_its_place_in_the_bracket(db: psycopg.Connection[Any]) -> None:
    s = Season(db, 99783)
    fid = s.match("Quarter-finals", 1, 2, START)
    facts = imp.facts_of(db, fid, at=START - timedelta(hours=2))
    assert facts is not None
    stage = facts.as_json()["stage"]
    assert (stage["kind"], stage["role"], stage["teams"], stage["rounds_to_final"]) == ("knockout", "knockout", 8, 2)
    assert facts.match_days is None and imp.facts_of(db, -1, at=START) is None
