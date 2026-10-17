"""REVIEW PREDIGOL (11 Oct 2026), point 7: line-ups and absences say who the player is for his team - his season in
this competition, as the provider aggregates it, with the team's matches so a page can read "started 7 of 8".
A player of the other team, or of another competition, never lends his numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg

from fbi.api.services.center import match_center
from tests.integration.conftest import Seed

KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)


def _season(db: psycopg.Connection, seed: Seed, player: int, team_pid: int, league: int, *, apps: int,
            starts: int, goals: int, at: datetime) -> None:
    db.execute("INSERT INTO core.player_season_stats (provider_player_id, provider_league_id, season, provider_team_id, "
               "observed_at, appearances, lineups, minutes, goals, assists, yellow_cards, red_cards, payload_hash, "
               "normalizer_version) VALUES (%s, %s, 2025, %s, %s, %s, %s, %s, %s, 1, 2, 0, %s, 'test')",
               (player, league, team_pid, at, apps, starts, starts * 85, goals, seed.payload_hash))


def test_lineups_and_absences_carry_the_players_season(db: psycopg.Connection, seed: Seed) -> None:
    # the seed match as this run left it: other suites move its kick-off and re-file its teams
    pids = db.execute("SELECT th.provider_team_id, ta.provider_team_id, f.provider_fixture_id, f.kickoff_at, "
                      "f.home_team_id, f.competition_season_id FROM core.fixtures f "
                      "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id "
                      "WHERE f.id = %s", (seed.fixture_id,)).fetchone()
    assert pids is not None
    home_pid, away_pid, pfid = int(pids[0]), int(pids[1]), int(pids[2])
    ko, home_id, season_id = pids[3], int(pids[4]), int(pids[5])
    league = db.execute("SELECT c.provider_league_id FROM core.competition_seasons cs JOIN core.competitions c "
                        "ON c.id = cs.competition_id WHERE cs.id = %s", (season_id,)).fetchone()
    assert league is not None
    # two finished league matches of the home side before kick-off
    other = db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (9911, 'Rival') RETURNING id").fetchone()
    assert other is not None
    for k, days in enumerate((5, 12)):
        db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                   "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished')",
                   (99100 + k, season_id, home_id, int(other[0]), ko - timedelta(days=days)))
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, payload_hash, fetched_at) "
               "VALUES (%s, 'home', 'api-football', '4-3-3', %s, now())", (seed.fixture_id, seed.payload_hash))
    db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
               "player_name, shirt_number, position, is_starter) VALUES (%s, 'home', 'api-football', 501, 'Starter', 9, "
               "'F', true)", (seed.fixture_id,))
    db.execute("INSERT INTO core.player_absences (source, provider_fixture_id, provider_player_id, fixture_id, "
               "provider_team_id, player_name, absence_type, reason, payload_hash, fetched_at) VALUES "
               "('api-football', %s, 502, %s, %s, 'Injured Star', 'Missing Fixture', 'Knee Injury', %s, now())",
               (pfid, seed.fixture_id, away_pid, seed.payload_hash))
    lg = int(league[0])
    _season(db, seed, 501, home_pid, lg, apps=2, starts=2, goals=1, at=KO - timedelta(days=6))
    _season(db, seed, 501, home_pid, lg, apps=7, starts=7, goals=4, at=KO - timedelta(days=1))  # the newest wins
    _season(db, seed, 501, home_pid, lg + 1000, apps=3, starts=3, goals=9, at=KO - timedelta(days=1))  # another one
    _season(db, seed, 502, away_pid, lg, apps=8, starts=8, goals=6, at=KO - timedelta(days=1))
    _season(db, seed, 502, home_pid, lg, apps=1, starts=0, goals=0, at=KO - timedelta(days=1))  # another team

    c = match_center(db, seed.fixture_id).data
    assert c is not None
    starter = c.lineups.data[0].players[0]
    assert starter.season is not None
    assert (starter.season.appearances, starter.season.lineups, starter.season.goals,
            starter.season.team_matches) == (7, 7, 4, 2)
    star = c.absences.data[0]
    assert star.season is not None and (star.season.appearances, star.season.goals) == (8, 6), (
        "his numbers for the away side, not for the team he left")


def test_no_season_stored_is_null_not_zero(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
               "VALUES (%s, 'away', 'api-football', %s, now())", (seed.fixture_id, seed.payload_hash))
    db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
               "player_name, is_starter) VALUES (%s, 'away', 'api-football', 777, 'Unknown Lad', true)",
               (seed.fixture_id,))
    c = match_center(db, seed.fixture_id).data
    assert c is not None
    assert c.lineups.data[0].players[0].season is None


def test_the_admin_reads_one_matchs_postmortems_whatever_its_day(db: psycopg.Connection, seed: Seed) -> None:
    """REVIEW point 4: a finished match's Picks tab shows its post-mortems (admin), not only yesterday's."""
    from fbi.api.services.ai_v2 import postmortems
    db.execute("INSERT INTO ai.pick_postmortems (fixture_id, market_key, selection, line, created_at, version, roles, "
               "settled, verdict, answers) VALUES (%s, 'OU', 'Under', 2.5, now(), 'pm-test', '{shadow}', 'LOST', "
               "'unreviewed_lost', '{}'::jsonb)", (seed.fixture_id,))
    rows = postmortems(db, fixture_id=seed.fixture_id).data
    assert [(r.fixture_id, r.market_key, r.verdict) for r in rows] == [(seed.fixture_id, "OU", "unreviewed_lost")]
    assert postmortems(db).data == [], "without a fixture, still yesterday's (the seed match is in September)"
