"""The fixes the first truth audit called for: corrected sides, the season list, post-match
detail, and an Elo history that keeps up with the results."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.features.elo_refresh import JOB, refresh_elo
from fbi.ingestion.catalogue_refresh import refresh_catalogue
from fbi.ingestion.fixtures import FixtureRepository, PayloadLineage
from fbi.ingestion.live_match import post_match_to_refresh
from fbi.providers.api_football.details import iter_coverage
from fbi.providers.base import FixtureRef, RawResponse
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        yield c
        c.rollback()


def test_a_fixture_whose_sides_the_provider_corrects_follows_it_and_says_so(conn: psycopg.Connection,
                                                                           seed: Seed) -> None:
    repo = FixtureRepository(conn)
    teams = repo.ensure_teams([FixtureRef(1001, 39, 2025, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 77,
                                          "NS")], {33: "Manchester United", 77: "Corrected FC"})
    ref = FixtureRef(1001, 39, 2025, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 77, "NS")
    inserted, updated = repo.upsert_fixtures([ref], {(39, 2025): seed.season_id}, teams,
                                             lineage=PayloadLineage(seed.payload_hash, NOW))
    assert (inserted, updated) == (0, 1)
    away = conn.execute("SELECT away_team_id FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert away is not None and away[0] == teams[77]
    repair = conn.execute("SELECT rule, before_value, after_value FROM audit.data_repairs "
                          "WHERE entity_id = %s ORDER BY id DESC LIMIT 1", (seed.fixture_id,)).fetchone()
    assert repair is not None and repair[0] == "fixture_sides" and repair[1] != repair[2]


def test_a_fixture_the_provider_moves_to_another_tracked_season_goes_with_it_and_says_so(
        conn: psycopg.Connection, seed: Seed) -> None:
    repo = FixtureRepository(conn)
    other = conn.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) "
                         "RETURNING id", (seed.competition_id,)).fetchone()
    assert other is not None
    ref = FixtureRef(1001, 39, 2026, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 40, "NS")
    teams = repo.ensure_teams([ref], {33: "Manchester United", 40: "Liverpool"})
    inserted, updated = repo.upsert_fixtures([ref], {(39, 2025): seed.season_id, (39, 2026): other[0]}, teams,
                                             lineage=PayloadLineage(seed.payload_hash, NOW))
    assert (inserted, updated) == (0, 1)
    held = conn.execute("SELECT competition_season_id FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert held == (other[0],), "until 5 Oct 2026 the update never touched the competition season"
    repair = conn.execute("SELECT before_value, after_value, evidence FROM audit.data_repairs "
                          "WHERE entity_id = %s AND rule = 'fixture_competition'", (seed.fixture_id,)).fetchone()
    assert repair == (str(seed.season_id), str(other[0]), seed.payload_hash)


def test_a_fixture_moved_out_of_the_tracked_set_stays_where_it_was_and_is_flagged(
        conn: psycopg.Connection, seed: Seed) -> None:
    repo = FixtureRepository(conn)
    moved = FixtureRef(1001, 916, 2026, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 40, "PEN")
    stranger = FixtureRef(99_123, 916, 2026, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 40, "NS")
    assert repo.note_left_tracked([moved, stranger], {(39, 2025): seed.season_id},
                                  payload_hash=seed.payload_hash) == 1, "only a fixture we hold is ours to flag"
    held = conn.execute("SELECT competition_season_id FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert held == (seed.season_id,), "no season row is invented for a competition we do not track"
    issue = conn.execute("SELECT code, observed, expected, payload_hash FROM audit.data_quality_issues "
                         "WHERE entity_type = 'fixture' AND entity_id = %s AND field = 'competition'",
                         (seed.fixture_id,)).fetchone()
    assert issue == ("STALE_DATA", "league 916 season 2026", "league 39 season 2025", seed.payload_hash)
    same = FixtureRef(1001, 39, 2025, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 40, "NS")
    assert repo.note_left_tracked([same], {}) == 0, "a competition we stopped tracking is not a move"


def test_a_moved_kick_off_is_kept_with_both_times(conn: psycopg.Connection, seed: Seed) -> None:
    repo = FixtureRepository(conn)
    old = conn.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert old is not None
    moved = old[0] - timedelta(hours=3, minutes=30)
    ref = FixtureRef(1001, 39, 2025, moved, 33, 40, "NS")
    teams = repo.ensure_teams([ref], {33: "Manchester United", 40: "Liverpool"})
    repo.upsert_fixtures([ref], {(39, 2025): seed.season_id}, teams,
                         lineage=PayloadLineage(seed.payload_hash, NOW + timedelta(minutes=1)))
    row = conn.execute("SELECT before_kickoff, after_kickoff, payload_hash FROM core.fixture_kickoff_changes "
                       "WHERE fixture_id = %s", (seed.fixture_id,)).fetchone()
    assert row == (old[0], moved, seed.payload_hash)


class CatalogueProvider:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    async def fetch_coverage(self, *, league_id: int | None = None) -> Any:
        raw = RawResponse(endpoint="/leagues", params={}, fetched_at=NOW, http_status=200, results_count=1,
                          payload_hash="h1", file_path="x", bytes_written=1, body=self.body)
        return list(iter_coverage(self.body)), raw


async def test_the_daily_catalogue_refresh_learns_a_new_current_season(conn: psycopg.Connection,
                                                                       seed: Seed) -> None:
    body = {"response": [{
        "league": {"id": 39, "name": "Premier League", "type": "League"}, "country": {"name": "England"},
        "seasons": [
            {"year": 2025, "current": False, "start": "2025-08-15", "end": "2026-05-24",
             "coverage": {"fixtures": {"events": True}, "standings": True, "odds": True}},
            {"year": 2026, "current": True, "start": "2026-08-14", "end": "2027-05-23",
             "coverage": {"fixtures": {"events": True}, "standings": True, "odds": True}},
        ]}]}
    before = conn.execute("SELECT season, is_current, start_date, end_date, has_odds, has_fixtures, listed_at "
                          "FROM core.competition_seasons WHERE competition_id = %s", (seed.competition_id,)).fetchall()
    conn.commit()
    try:
        counters = await refresh_catalogue(conn, CatalogueProvider(body), at=NOW)
        assert counters.api_calls == 1 and not counters.errors
        rows = conn.execute("SELECT season, is_current FROM core.competition_seasons WHERE competition_id = %s "
                            "ORDER BY season", (seed.competition_id,)).fetchall()
        assert (2026, True) in rows and (2025, False) in rows
        flags = conn.execute("SELECT standings, odds FROM raw.league_coverage WHERE provider_league_id = 39 "
                             "AND season = 2026").fetchone()
        assert flags == (True, True)
    finally:
        # refresh_catalogue commits: put the shared seed back exactly as it was.
        conn.rollback()
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s AND season <> ALL(%s)",
                     (seed.competition_id, [r[0] for r in before]))
        for season, current, start, end, odds, has_fixtures, listed in before:
            conn.execute("UPDATE core.competition_seasons SET is_current = %s, start_date = %s, end_date = %s, "
                         "has_odds = %s, has_fixtures = %s, listed_at = %s WHERE competition_id = %s AND season = %s",
                         (current, start, end, odds, has_fixtures, listed, seed.competition_id, season))
        conn.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = 39 AND payload_hash = 'h1'")
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'catalogue_refresh'")
        conn.commit()


def test_a_finished_match_read_only_at_the_whistle_is_read_again(conn: psycopg.Connection, seed: Seed) -> None:
    kickoff = NOW - timedelta(hours=5)
    conn.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    conn.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished', kickoff_at = %s "
                 "WHERE id = %s", (kickoff, seed.fixture_id))
    conn.execute("INSERT INTO core.fixture_detail_coverage (fixture_id, source, dataset, block_present, "
                 "rows_written, payload_hash, fetched_at) VALUES (%s, 'api-football', 'team_statistics', true, 2, "
                 "%s, %s)", (seed.fixture_id, seed.payload_hash, kickoff + timedelta(minutes=112)))
    assert (seed.fixture_id, 1001) in post_match_to_refresh(conn, at=NOW)
    conn.execute("UPDATE core.fixture_detail_coverage SET fetched_at = %s WHERE fixture_id = %s",
                 (kickoff + timedelta(hours=3), seed.fixture_id))
    assert (seed.fixture_id, 1001) not in post_match_to_refresh(conn, at=NOW), "read after it settled"


def test_the_elo_history_is_recomputed_and_older_refreshes_pruned(conn: psycopg.Connection, seed: Seed) -> None:
    conn.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                 (seed.fixture_id,))
    conn.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away) "
                 "VALUES (%s, 2, 0, 2, 0) ON CONFLICT (fixture_id) DO NOTHING", (seed.fixture_id,))
    conn.commit()
    try:
        first = refresh_elo(conn)
        second = refresh_elo(conn)
        third = refresh_elo(conn, keep=1)
        assert first.matches >= 1 and first.rows == 2 * first.matches
        runs = {r[0] for r in conn.execute("SELECT DISTINCT run_id FROM features.elo_ratings").fetchall()}
        assert third.run_id in runs and first.run_id not in runs and second.run_id not in runs
        home = conn.execute("SELECT rating_after FROM features.elo_ratings WHERE run_id = %s AND team_id = %s",
                            (third.run_id, seed.home_team_id)).fetchone()
        assert home is not None and home[0] > 1500, "the 2-0 winner gains"
    finally:
        conn.execute("DELETE FROM features.elo_ratings")
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = %s", (JOB,))
        conn.execute("DELETE FROM core.fixture_results WHERE fixture_id = %s", (seed.fixture_id,))
        conn.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s",
                     (seed.fixture_id,))
        conn.commit()


# ── people: profiles and squads ─────────────────────────────────────────────

def test_a_profile_fills_the_player_we_know_and_skips_the_one_we_do_not(conn: psycopg.Connection) -> None:
    from datetime import date

    from fbi.ingestion.people import apply_player_profiles
    from fbi.providers.api_football.details import iter_player_profiles

    conn.execute("INSERT INTO core.players (provider_player_id, name, position) VALUES (777001, 'K. Known', 'G')")
    body = {"response": [
        {"player": {"id": 777001, "name": "K. Known", "firstname": "Kay", "lastname": "Known", "age": 30,
                    "birth": {"date": "1996-02-03", "place": "Lima", "country": "Peru"}, "nationality": "Peru",
                    "height": "181", "weight": None, "number": 1, "position": "Goalkeeper", "photo": "https://x/1.png"}},
        {"player": {"id": 777002, "name": "U. Unknown", "birth": {"date": "2001-01-01"}}},
    ]}
    at = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
    out = apply_player_profiles(conn, iter_player_profiles(body), payload_hash="h1", fetched_at=at)
    assert (out.updated, out.unknown) == (1, 1), "the catalogue stays the players of our competitions"
    row = conn.execute("SELECT birth_date, nationality, height_cm, weight_kg, birth_place, profile_fetched_at "
                       "FROM core.players WHERE provider_player_id = 777001").fetchone()
    assert row == (date(1996, 2, 3), "Peru", 181, None, "Lima", at)
    older = {"response": [{"player": {"id": 777001, "nationality": "Chile"}}]}
    apply_player_profiles(conn, iter_player_profiles(older), payload_hash="h1", fetched_at=at - timedelta(days=1))
    nat = conn.execute("SELECT nationality FROM core.players WHERE provider_player_id = 777001").fetchone()
    assert nat == ("Peru",), "an older profile changes nothing"
    blank = {"response": [{"player": {"id": 777001, "nationality": None}}]}
    apply_player_profiles(conn, iter_player_profiles(blank), payload_hash="h1", fetched_at=at + timedelta(days=1))
    nat = conn.execute("SELECT nationality FROM core.players WHERE provider_player_id = 777001").fetchone()
    assert nat == ("Peru",), "an empty value does not erase a known one"


def test_a_squad_keeps_who_left_and_knows_who_is_current(conn: psycopg.Connection, seed: Seed) -> None:
    from fbi.ingestion.people import apply_squad
    from fbi.providers.api_football.details import iter_squad

    def body(*ids: int) -> dict[str, Any]:
        return {"response": [{"team": {"id": 33, "name": "Manchester United"},
                              "players": [{"id": i, "name": f"P{i}", "age": 25, "number": n, "position": "Defender"}
                                          for n, i in enumerate(ids, 2)]}]}

    t1, t2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC)
    [(team, members)] = list(iter_squad(body(9001, 9002, 9003)))
    assert apply_squad(conn, team, members, payload_hash="h1", fetched_at=t1).members == 3
    [(team, members)] = list(iter_squad(body(9001, 9002, 9004)))
    out = apply_squad(conn, team, members, payload_hash="h1", fetched_at=t2)
    assert (out.members, out.left) == (3, 1)
    current = {r[0] for r in conn.execute(
        "SELECT m.provider_player_id FROM core.squad_members m JOIN core.teams t ON t.id = m.team_id "
        "WHERE t.provider_team_id = 33 AND m.last_seen_at = t.squad_checked_at").fetchall()}
    assert current == {9001, 9002, 9004}
    gone = conn.execute("SELECT last_seen_at FROM core.squad_members WHERE provider_player_id = 9003").fetchone()
    assert gone == (t1,), "a player who left stays on record"


def test_the_people_refresh_is_seeded_once_per_month_and_week(conn: psycopg.Connection, seed: Seed) -> None:
    from fbi.ingestion.people import seed_people_refresh

    conn.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    conn.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    conn.commit()
    try:
        first = seed_people_refresh(conn, at=NOW)
        again = seed_people_refresh(conn, at=NOW + timedelta(hours=1))
        assert (first.profile_units, first.squad_units) == (1, 2), "page 1, and both teams of the seeded fixture"
        assert (again.profile_units, again.squad_units) == (0, 0), "the same month and week add nothing"
        later = seed_people_refresh(conn, at=NOW + timedelta(days=7))
        assert later.squad_units == 2 and later.profile_units == 0, "a new week, a new squad round"
    finally:
        conn.execute("DELETE FROM raw.backfill_tasks WHERE kind IN ('player_profiles', 'team_squad')")
        conn.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
        conn.execute("UPDATE core.competition_seasons SET is_current = false WHERE id = %s", (seed.season_id,))
        conn.commit()
