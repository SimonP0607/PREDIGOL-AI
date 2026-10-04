"""Regression for the P0 standings bug against the real schema: a season with an Apertura and a Clausura table.

Until 4 Oct 2026 the Match Center took each team's newest row across ALL the season's tables
(``DISTINCT ON (team)``): Llaneros v America de Cali showed one side's Clausura row (11 games) and the
other's Apertura row (19 games). The competition page flattened every table into one list. Both now
read ``fbi.competitions``: a match gets its own stage's table, the page keeps each table apart.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.api.services import center
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

LEAGUE, SEASON = 99239, 2026
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
APERTURA = datetime(2026, 1, 16, 20, tzinfo=UTC)
CLAUSURA = datetime(2026, 7, 24, 20, tzinfo=UTC)
WEEK = timedelta(days=7)


def rr(teams: list[int]) -> list[list[tuple[int, int]]]:
    t = list(teams)
    out = []
    for _ in range(len(t) - 1):
        out.append([(t[i], t[len(t) - 1 - i]) for i in range(len(t) // 2)])
        t = [t[0], t[-1], *t[1:-1]]
    return out


@pytest.fixture()
def clock() -> Iterator[None]:
    set_clock(FrozenClock(NOW))
    yield
    set_clock(SystemClock())


def build(db: psycopg.Connection) -> dict[str, int]:
    """Six teams; the Apertura (5 rounds, all played) and its final; the Clausura's first 3 rounds played,
    round 4 to come. One snapshot holds both tables, as the provider serves them."""
    ids: dict[str, int] = {}
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                    "VALUES (%s, 'Primera A', 'league', 'club', 'domestic_league') RETURNING id", (LEAGUE,))
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, %s, true) "
                    "RETURNING id", (ids["competition"], SEASON))
        cs = ids["cs"] = scalar(cur)
        team = {}
        for n in range(1, 7):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                        (992390 + n, f"Team {n}"))
            team[n] = scalar(cur)
        played = {"Apertura": dict.fromkeys(team, 0), "Clausura": dict.fromkeys(team, 0)}
        fx = 99239000

        def fixture(round_label: str, h: int, a: int, ko: datetime, finished: bool) -> int:
            nonlocal fx
            fx += 1
            cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, round, status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (fx, cs, team[h], team[a], ko, round_label, "FT" if finished else "NS",
                 "finished" if finished else "scheduled"))
            fid = scalar(cur)
            if finished:
                cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 1, 0)",
                            (fid,))
            return fid

        for phase, start, rounds in (("Apertura", APERTURA, 5), ("Clausura", CLAUSURA, 4)):
            for r, pairs in enumerate(rr(list(team))[:rounds], 1):
                for h, a in pairs:
                    done = r <= (5 if phase == "Apertura" else 3)
                    fid = fixture(f"{phase} - {r}", h, a, start + (r - 1) * WEEK, done)
                    if done:
                        played[phase][h] += 1
                        played[phase][a] += 1
                    if phase == "Clausura" and r == 4 and (h, a) == pairs[0]:
                        ids["clausura_match"], ids["home"], ids["away"] = fid, team[h], team[a]
        ids["final"] = fixture("Apertura - Final", 1, 2, datetime(2026, 6, 3, tzinfo=UTC), True)
        snap = CLAUSURA + 2 * WEEK + timedelta(days=3)  # after Clausura round 3, before round 4
        for phase in ("Apertura", "Clausura"):
            for rank, n in enumerate(sorted(team), 1):
                p = played[phase][n]
                cur.execute(
                    'INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, '
                    'wins, draws, losses, goals_for, goals_against, "group", home_played, home_wins, home_draws, '
                    'home_losses, home_goals_for, home_goals_against) '
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, 0, %s, 1, 1, 0, 0, 1, 0)",
                    (cs, team[n], snap, rank, 3 * p, p, p, p, phase))
        ids["snapshot_epoch"] = int(snap.timestamp())
    return ids


def test_a_clausura_match_shows_both_teams_from_the_clausura_table(db: psycopg.Connection, seed: Seed,
                                                                    clock: None) -> None:
    ids = build(db)
    body = center.match_center(db, ids["clausura_match"]).data
    assert body is not None and body.standings.status == "ok"
    lines = body.standings.data or []
    assert [s.side for s in lines] == ["home", "away"]
    assert {s.table for s in lines} == {"Clausura"}, "one table for both teams, the match's own phase"
    assert {s.played for s in lines} == {3}, "Clausura games, not the Apertura's 5"
    assert all(s.stage == "Clausura" and s.phase == "Clausura" and s.fixture_stage == "Clausura"
               and s.selection == "fixture_stage" and s.table_kind == "full" and s.table_teams == 6 for s in lines)
    assert all(s.before_kickoff for s in lines)
    assert [(t.label, t.stage, t.kind, len(t.rows)) for t in body.standings_tables] == [("Clausura", "Clausura", "full", 6)]


def test_a_knockout_final_shows_its_phase_league_table(db: psycopg.Connection, seed: Seed, clock: None) -> None:
    ids = build(db)
    body = center.match_center(db, ids["final"]).data
    assert body is not None
    lines = body.standings.data or []
    assert {(s.table, s.selection, s.played) for s in lines} == {("Apertura", "phase_league_stage", 5)}
    assert not any(s.before_kickoff for s in lines), "the only snapshot was taken after the final: said so"


def test_the_competition_page_keeps_apertura_and_clausura_apart(db: psycopg.Connection, seed: Seed,
                                                                clock: None) -> None:
    ids = build(db)
    env = center.competition_table(db, ids["competition"])
    t = env.data
    assert t is not None and t.season == SEASON and t.seasons == [SEASON] and t.mapping_version
    assert [(x.label, x.stage, x.kind, x.method, x.agreement, x.is_current, len(x.rows)) for x in t.tables] == [
        ("Apertura", "Apertura", "full", "label", "6/6", False, 6),
        ("Clausura", "Clausura", "full", "label", "6/6", True, 6)]
    assert [(s.name, s.kind, s.tables, s.is_current) for s in t.stages] == [
        ("Apertura", "league", 1, False), ("Apertura - Final", "knockout", 0, False), ("Clausura", "league", 1, True)]
    row = t.tables[1].rows[0]
    assert row.home is not None and row.home.played == 1 and row.away is None
    assert len(t.rows) == 12, "the deprecated flat list still carries every row"


def test_a_match_awarded_off_the_pitch_counts_in_its_group(db: psycopg.Connection, seed: Seed, clock: None) -> None:
    """Libertadores 2026: Medellin v Flamengo was awarded (AWD; core.fixtures keeps it as 'cancelled').
    The provider's group table counts it; so must the games-played check, or the group goes unmapped."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                    "VALUES (99013, 'Libertadores', 'cup', 'club', 'continental') RETURNING id")
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                    "RETURNING id", (comp,))
        cs = scalar(cur)
        team = {}
        for n in range(1, 5):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                        (990130 + n, f"Club {n}"))
            team[n] = scalar(cur)
        start = datetime(2026, 4, 7, tzinfo=UTC)
        for r, pairs in enumerate(rr([1, 2, 3, 4]), 1):
            for i, (h, a) in enumerate(pairs):
                awarded = (r, i) == (2, 0)
                cur.execute(
                    "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at, round, status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (99013000 + 10 * r + i, cs, team[h], team[a], start + (r - 1) * WEEK, f"Group Stage - {r}",
                     "AWD" if awarded else "FT", "cancelled" if awarded else "finished"))
        snap = start + 3 * WEEK
        for rank, n in enumerate(sorted(team), 1):
            cur.execute('INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, '
                        'wins, draws, losses, goals_for, goals_against, "group") '
                        "VALUES (%s, %s, %s, %s, 3, 3, 1, 0, 2, 1, 2, 'Group A')", (cs, team[n], snap, rank))
    t = center.competition_table(db, comp).data
    assert t is not None
    assert [(x.label, x.stage, x.method, x.agreement) for x in t.tables] == [("Group A", "Group Stage", "games", "4/4")]
