"""The table of a match's own stage, as the AI packet read it before the match (plan F2).

The packet used to take each team's newest row across ALL the season's tables and keep, per team, the table whose name sorted last
(``DISTINCT ON (team, group)`` and then a dict by team): in a season with a regular season and a championship round, the
championship match was described with the REGULAR SEASON table ("Championship Round" < "Regular Season"). The Match Center had the
same bug until 4 Oct 2026 and was fixed by ``fbi.competitions.phases``; the packet now reads the same mapping, cut at the packet's
moment: a snapshot taken after it is never seen."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.packet import PacketBuilder
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_competition_phases_db import rr

pytestmark = pytest.mark.integration

START = datetime(2026, 3, 1, 20, tzinfo=UTC)
WEEK = timedelta(days=7)


class Season:
    """Six teams, the matches of every round written as played or to come, and the snapshots the provider took."""

    def __init__(self, db: psycopg.Connection[Any], league: int, name: str = "Liga") -> None:
        self.db = db
        self.fx = league * 1000
        with db.cursor() as cur:
            cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                        "VALUES (%s, %s, 'league', 'club', 'domestic_league') RETURNING id", (league, name))
            comp = scalar(cur)
            cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                        "RETURNING id", (comp,))
            self.cs = scalar(cur)
            self.team: dict[int, int] = {}
            for n in range(1, 7):
                cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                            (league * 10 + n, f"Team {league}-{n}"))
                self.team[n] = scalar(cur)

    def match(self, label: str, home: int, away: int, ko: datetime, *, played: bool, goals: tuple[int, int] = (1, 0)) -> int:
        self.fx += 1
        with self.db.cursor() as cur:
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                        "kickoff_at, round, status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (self.fx, self.cs, self.team[home], self.team[away], ko, label, "FT" if played else "NS",
                         "finished" if played else "scheduled"))
            fid = scalar(cur)
            if played:
                cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) "
                            "VALUES (%s, %s, %s, %s)", (fid, goals[0], goals[1], ko + timedelta(hours=2)))
        return fid

    def rounds(self, stage: str, start: datetime, count: int, played: int) -> dict[int, int]:
        """``count`` round-robin rounds of ``stage`` from ``start``, the first ``played`` of them played. Returns each team's
        games played."""
        games = dict.fromkeys(self.team, 0)
        for r, pairs in enumerate(rr(list(self.team))[:count], 1):
            for h, a in pairs:
                done = r <= played
                self.match(f"{stage} - {r}", h, a, start + (r - 1) * WEEK, played=done)
                if done:
                    games[h] += 1
                    games[a] += 1
        return games

    def snapshot(self, at: datetime, tables: dict[str, dict[int, int]]) -> None:
        """One snapshot holding these tables: group name -> games played by each team (points are 3 per game)."""
        with self.db.cursor() as cur:
            for group, played in tables.items():
                for rank, n in enumerate(sorted(played), 1):
                    p = played[n]
                    cur.execute('INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, '
                                'played, wins, draws, losses, goals_for, goals_against, "group", home_played, home_wins, '
                                'home_draws, home_losses, home_goals_for, home_goals_against) '
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, 0, %s, 0, 0, 0, 0, 0, 0)",
                                (self.cs, self.team[n], at, rank, 3 * p, p, p, p, group))


def packet(db: psycopg.Connection[Any], fixture_id: int, ko: datetime) -> Any:
    got = PacketBuilder(db).build(fixture_id, at=ko - timedelta(hours=3))
    assert got is not None
    return got


def championship(db: psycopg.Connection[Any], league: int) -> tuple[Season, int, datetime]:
    """A regular season (5 rounds, all played) and then a championship round (2 played, the third to come). The snapshot
    taken after the second championship round holds both tables, as the provider serves them."""
    s = Season(db, league)
    regular = s.rounds("Regular Season", START, 5, 5)
    champ_start = START + 6 * WEEK
    champ = s.rounds("Championship Round", champ_start, 3, 2)
    third = champ_start + 2 * WEEK
    match = next(fid for fid, h, a in db.execute(
        "SELECT id, home_team_id, away_team_id FROM core.fixtures WHERE competition_season_id = %s "
        "AND round = 'Championship Round - 3' ORDER BY id", (s.cs,)).fetchall())
    s.snapshot(champ_start + 2 * WEEK - timedelta(days=2), {"Regular Season": regular, "Championship Round": champ})
    return s, int(match), third


def test_a_championship_round_match_is_described_with_the_championship_round_table(db: psycopg.Connection[Any],
                                                                                   seed: Seed) -> None:
    _s, match, ko = championship(db, 99951)

    got = packet(db, match, ko)

    standings = got.content["standings"]
    assert {standings[side]["group"] for side in ("home", "away")} == {"Championship Round"}
    assert {standings[side]["played"] for side in ("home", "away")} == {2}, "the stage's games, not the regular season's 5"
    assert {standings[side]["stage"] for side in ("home", "away")} == {"Championship Round"}
    assert {standings[side]["selection"] for side in ("home", "away")} == {"fixture_stage"}
    assert got.content["stakes"]["home"] is not None
    assert "standings" not in got.missing


def test_a_snapshot_taken_after_the_packets_moment_is_never_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    s, match, ko = championship(db, 99952)
    before = packet(db, match, ko)

    s.snapshot(ko - timedelta(hours=1), {"Regular Season": dict.fromkeys(s.team, 5), "Championship Round": dict.fromkeys(s.team, 3)})
    s.snapshot(ko + timedelta(days=1), {"Regular Season": dict.fromkeys(s.team, 5), "Championship Round": dict.fromkeys(s.team, 9)})
    after = packet(db, match, ko)

    assert after.content == before.content and after.hash == before.hash, "later snapshots change nothing the packet said"


def test_a_clausura_match_reads_the_clausura_table(db: psycopg.Connection[Any], seed: Seed) -> None:
    s = Season(db, 99953)
    apertura = s.rounds("Apertura", START, 5, 5)
    clausura = s.rounds("Clausura", START + 8 * WEEK, 4, 3)
    ko = START + 8 * WEEK + 3 * WEEK
    s.snapshot(ko - timedelta(days=3), {"Apertura": apertura, "Clausura": clausura})
    match = int(scalar(db.execute("SELECT id FROM core.fixtures WHERE competition_season_id = %s AND round = 'Clausura - 4' "
                                  "ORDER BY id LIMIT 1", (s.cs,))))

    got = packet(db, match, ko)

    standings = got.content["standings"]
    assert {standings[side]["group"] for side in ("home", "away")} == {"Clausura"}
    assert {standings[side]["played"] for side in ("home", "away")} == {3}


def test_a_stage_with_no_table_of_its_own_says_so_instead_of_borrowing_another(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Only the Apertura table was ever stored: a Clausura match has no table, and the packet says it."""
    s = Season(db, 99954)
    apertura = s.rounds("Apertura", START, 5, 5)
    s.rounds("Clausura", START + 8 * WEEK, 4, 3)
    ko = START + 8 * WEEK + 3 * WEEK
    s.snapshot(ko - timedelta(days=3), {"Apertura": apertura})
    match = int(scalar(db.execute("SELECT id FROM core.fixtures WHERE competition_season_id = %s AND round = 'Clausura - 4' "
                                  "ORDER BY id LIMIT 1", (s.cs,))))

    got = packet(db, match, ko)

    assert got.content["standings"] is None and got.content["stakes"] is None
    assert "standings" in got.missing


def test_a_knockout_round_shows_the_table_of_the_stage_before_it_and_no_stakes_from_it(db: psycopg.Connection[Any],
                                                                                      seed: Seed) -> None:
    """A Round of 16 is worth the round, not the zones of a group stage that is over: the table is shown with the stage it
    ranks and why it was chosen, and nothing is computed from its zones."""
    s = Season(db, 99955)
    groups = s.rounds("Group Stage", START, 5, 5)
    ko = START + 12 * WEEK
    match = s.match("Round of 16", 1, 2, ko, played=False)
    s.snapshot(START + 6 * WEEK, {"Group A": groups})

    got = packet(db, match, ko)

    standings = got.content["standings"]
    assert {standings[side]["stage"] for side in ("home", "away")} == {"Group Stage"}
    assert {standings[side]["selection"] for side in ("home", "away")} == {"previous_stage"}
    assert got.content["stakes"] == {"home": None, "away": None}


def test_only_the_newest_snapshot_taken_by_the_moment_is_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The provider stores a table every time it changes. The packet reads ONE of them - the newest by its moment - so the table
    it describes has six teams, not the rows of every snapshot ever taken."""
    s, match, ko = championship(db, 99956)
    s.snapshot(START + 8 * WEEK - timedelta(days=30), {"Regular Season": dict.fromkeys(s.team, 3),
                                                       "Championship Round": dict.fromkeys(s.team, 1)})

    got = packet(db, match, ko)

    standings = got.content["standings"]
    assert {standings[side]["teams"] for side in ("home", "away")} == {6}
    assert {standings[side]["played"] for side in ("home", "away")} == {2}


def test_what_is_left_to_play_is_what_the_stage_of_the_table_has_left(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The Clausura matches are already scheduled, but they are not points the Apertura table can still give."""
    s = Season(db, 99957)
    apertura = s.rounds("Apertura", START, 3, 2)
    s.rounds("Clausura", START + 8 * WEEK, 3, 0)
    ko = START + 2 * WEEK
    s.snapshot(ko - timedelta(days=2), {"Apertura": apertura})
    match = int(scalar(db.execute("SELECT id FROM core.fixtures WHERE competition_season_id = %s AND round = 'Apertura - 3' "
                                  "ORDER BY id LIMIT 1", (s.cs,))))

    got = packet(db, match, ko)

    stakes = got.content["stakes"]
    assert {stakes[side]["remaining"] for side in ("home", "away")} == {1}, "this match is all that is left of the Apertura"
