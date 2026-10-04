"""The current season's tables and injury reports are refreshed, request by request, into the ledger."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.core.errors import ProviderError
from fbi.ingestion.context_refresh import refresh_context
from fbi.providers.api_football.details import StandingRef
from fbi.providers.base import RawResponse
from tests.integration.conftest import Seed


class FakeProvider:
    def __init__(self, league: int, season: int, home_pid: int, away_pid: int) -> None:
        self.league, self.season, self.home, self.away = league, season, home_pid, away_pid
        self.calls: list[str] = []

    def _raw(self, endpoint: str) -> RawResponse:
        at = datetime.now(UTC)
        return RawResponse(endpoint=endpoint, params={}, fetched_at=at, http_status=200, results_count=1,
                           payload_hash=f"ctx-{endpoint.strip('/')}-{at.timestamp()}", file_path="x",
                           bytes_written=1, body={})

    async def fetch_standings(self, *, league_id: int, season: int) -> Any:
        self.calls.append(f"standings {league_id}")
        if league_id != self.league:
            raise ProviderError("not this one")
        refs = [StandingRef(self.league, self.season, self.home, 1, 9, 3, 3, 0, 0, 7, 1, "WWW", None),
                StandingRef(self.league, self.season, self.away, 2, 6, 3, 2, 0, 1, 4, 3, "WLW", None)]
        return refs, self._raw("/standings")

    async def fetch_injuries(self, *, league_id: int, season: int) -> Any:
        self.calls.append(f"injuries {league_id}")
        return [], self._raw("/injuries")


@pytest.fixture
def current_league(migrated_database: str, seed: Seed) -> Iterator[dict[str, int]]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT is_tracked, type FROM core.competitions WHERE id = %s", (seed.competition_id,))
        tracked, kind = cur.fetchone()  # type: ignore[misc]
        cur.execute("SELECT is_current FROM core.competition_seasons WHERE id = %s", (seed.season_id,))
        current = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("UPDATE core.competitions SET is_tracked = true, type = 'league' WHERE id = %s",
                    (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
        cur.execute("SELECT c.provider_league_id, cs.season FROM core.competition_seasons cs JOIN core.competitions c "
                    "ON c.id = cs.competition_id WHERE cs.id = %s", (seed.season_id,))
        league, season = cur.fetchone()  # type: ignore[misc]
        cur.execute("SELECT provider_team_id FROM core.teams WHERE id IN (%s, %s) ORDER BY id = %s DESC",
                    (seed.home_team_id, seed.away_team_id, seed.home_team_id))
        home, away = (r[0] for r in cur.fetchall())
    yield {"league": int(league), "season": int(season), "home": int(home), "away": int(away)}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM core.standings WHERE competition_season_id = %s", (seed.season_id,))
        cur.execute("DELETE FROM core.context_checks WHERE competition_season_id = %s", (seed.season_id,))
        cur.execute("SELECT id FROM raw.ingestion_runs WHERE job_type = 'context_refresh'")
        runs = [r[0] for r in cur.fetchall()]
        if runs:
            cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id = ANY(%s)", (runs,))
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (runs,))
        cur.execute("UPDATE core.competitions SET is_tracked = %s, type = %s WHERE id = %s",
                    (tracked, kind, seed.competition_id))
        cur.execute("UPDATE core.competition_seasons SET is_current = %s WHERE id = %s", (current, seed.season_id))


async def test_tables_and_injuries_are_refreshed_and_counted(migrated_database: str, seed: Seed,
                                                              current_league: dict[str, int]) -> None:
    provider = FakeProvider(current_league["league"], current_league["season"], current_league["home"],
                            current_league["away"])
    with psycopg.connect(migrated_database) as conn:
        counters = await refresh_context(conn, provider)
        assert f"standings {current_league['league']}" in provider.calls
        assert f"injuries {current_league['league']}" in provider.calls
        assert counters.api_calls == len(provider.calls)
        with conn.cursor() as cur:
            cur.execute("SELECT rank, points FROM core.standings WHERE competition_season_id = %s ORDER BY rank",
                        (seed.season_id,))
            assert cur.fetchall() == [(1, 9), (2, 6)]
            cur.execute("SELECT status, api_calls FROM raw.ingestion_runs WHERE job_type = 'context_refresh' "
                        "ORDER BY id DESC LIMIT 1")
            status, calls = cur.fetchone()  # type: ignore[misc]
            assert calls == counters.api_calls and status in ("completed", "partial")


# ── the whole table row, and the job that follows matches ───────────────────

def _refs(league: int, season: int, team: int) -> list[StandingRef]:
    from fbi.providers.api_football.details import SplitRecord

    home = SplitRecord(2, 2, 0, 0, 5, 1)
    away = SplitRecord(1, 1, 0, 0, 2, 0)
    return [
        StandingRef(league, season, team, 1, 9, 3, 3, 0, 0, 7, 1, "WWW", "Western Conference", 6, "same",
                    "Promotion - Play Offs", datetime(2026, 10, 3, tzinfo=UTC), home, away),
        StandingRef(league, season, team, 4, 9, 3, 3, 0, 0, 7, 1, "WWW", "Supporters Shield"),
    ]


def test_a_team_in_two_tables_keeps_both_rows_and_the_whole_row(migrated_database: str, seed: Seed,
                                                                current_league: dict[str, int]) -> None:
    from fbi.ingestion.details import apply_standings_outcome

    at = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)
    with psycopg.connect(migrated_database) as conn:
        out = apply_standings_outcome(conn, [*_refs(current_league["league"], current_league["season"],
                                                    current_league["home"]),
                                             StandingRef(current_league["league"], current_league["season"],
                                                         987654, 2, 6, 3, 2, 0, 1, 4, 3, None, None)],
                                      fetched_at=at, payload_hash="h1")
        assert out.written == 2, "one team, two groups, two rows"
        assert out.unknown_teams == [987654], "a row for a team we do not know is counted, not dropped silently"
        rows = conn.execute(
            'SELECT "group", description, zone_status, goals_diff, home_played, away_goals_for, provider_updated_at '
            "FROM core.standings WHERE competition_season_id = %s AND snapshot_at = %s ORDER BY rank",
            (seed.season_id, at)).fetchall()
        assert rows[0][:6] == ("Western Conference", "Promotion - Play Offs", "same", 6, 2, 2)
        assert rows[0][6] == datetime(2026, 10, 3, tzinfo=UTC)
        assert rows[1][0] == "Supporters Shield" and rows[1][1] is None
        conn.rollback()


def test_a_check_moves_changed_at_only_when_the_answer_changes(migrated_database: str, seed: Seed) -> None:
    from fbi.ingestion.context_refresh import record_check

    t0 = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)
    with psycopg.connect(migrated_database) as conn:
        conn.execute("DELETE FROM core.context_checks WHERE competition_season_id = %s", (seed.season_id,))
        record_check(conn, competition_season_id=seed.season_id, dataset="standings", checked_at=t0,
                     payload_hash="a", rows_seen=20)
        record_check(conn, competition_season_id=seed.season_id, dataset="standings",
                     checked_at=t0 + timedelta(hours=1), payload_hash="a", rows_seen=20)
        got = conn.execute("SELECT checked_at, changed_at FROM core.context_checks WHERE competition_season_id = %s "
                           "AND dataset = 'standings'", (seed.season_id,)).fetchone()
        assert got == (t0 + timedelta(hours=1), t0), "asked again, nothing new"
        record_check(conn, competition_season_id=seed.season_id, dataset="standings",
                     checked_at=t0 + timedelta(hours=2), payload_hash="b", rows_seen=20)
        record_check(conn, competition_season_id=seed.season_id, dataset="standings",
                     checked_at=t0 + timedelta(minutes=30), payload_hash="z", rows_seen=1)
        got = conn.execute("SELECT checked_at, changed_at, payload_hash FROM core.context_checks "
                           "WHERE competition_season_id = %s AND dataset = 'standings'", (seed.season_id,)).fetchone()
        assert got == (t0 + timedelta(hours=2), t0 + timedelta(hours=2), "b"), "a late, older answer changes nothing"
        conn.rollback()


def test_a_finished_match_makes_its_table_due_until_the_table_changes(migrated_database: str, seed: Seed,
                                                                      current_league: dict[str, int]) -> None:
    from fbi.ingestion.context_refresh import due_seasons, record_check

    kickoff = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
    with psycopg.connect(migrated_database) as conn:
        conn.execute("DELETE FROM core.context_checks WHERE competition_season_id = %s", (seed.season_id,))
        conn.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                     (seed.fixture_id,))
        before_end = due_seasons(conn, at=kickoff + timedelta(hours=1))
        assert seed.season_id not in [s.competition_season_id for s in before_end["standings"]]
        after = due_seasons(conn, at=kickoff + timedelta(hours=3))
        assert seed.season_id in [s.competition_season_id for s in after["standings"]]
        # asked at +2h30 and the provider had not changed the table: due again only after the recheck interval
        record_check(conn, competition_season_id=seed.season_id, dataset="standings",
                     checked_at=kickoff + timedelta(hours=2, minutes=30), payload_hash="old", rows_seen=20)
        conn.execute("UPDATE core.context_checks SET changed_at = %s WHERE competition_season_id = %s",
                     (kickoff - timedelta(days=3), seed.season_id))
        assert seed.season_id not in [s.competition_season_id
                                      for s in due_seasons(conn, at=kickoff + timedelta(hours=3))["standings"]]
        assert seed.season_id in [s.competition_season_id
                                  for s in due_seasons(conn, at=kickoff + timedelta(hours=3, minutes=30))["standings"]]
        # the table changed after the match ended: nothing more to follow
        record_check(conn, competition_season_id=seed.season_id, dataset="standings",
                     checked_at=kickoff + timedelta(hours=3, minutes=30), payload_hash="new", rows_seen=20)
        assert seed.season_id not in [s.competition_season_id
                                      for s in due_seasons(conn, at=kickoff + timedelta(hours=5))["standings"]]
        conn.rollback()


async def test_a_cup_with_a_table_is_refreshed_and_one_without_is_not(migrated_database: str, seed: Seed,
                                                                      current_league: dict[str, int]) -> None:
    """Data truth audit V2: cups with a league phase or groups were never refreshed (type = 'league' only)."""
    from fbi.ingestion.context_refresh import due_seasons, table_seasons

    provider = FakeProvider(current_league["league"], current_league["season"], current_league["home"],
                            current_league["away"])
    with psycopg.connect(migrated_database) as conn:
        conn.execute("UPDATE core.competitions SET type = 'cup' WHERE id = %s", (seed.competition_id,))
        conn.execute("DELETE FROM core.standings WHERE competition_season_id = %s", (seed.season_id,))
        assert seed.season_id not in table_seasons(conn)  # a cup, no coverage flag, no table held
        await refresh_context(conn, provider)
        assert f"standings {current_league['league']}" not in provider.calls
        conn.execute("INSERT INTO raw.league_coverage (provider_league_id, season, standings, payload_hash, "
                     "observed_at) VALUES (%s, %s, true, %s, now()) ON CONFLICT DO NOTHING",
                     (current_league["league"], current_league["season"], seed.payload_hash))
        assert seed.season_id in table_seasons(conn)
        await refresh_context(conn, provider)
        assert f"standings {current_league['league']}" in provider.calls
        kickoff = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
        conn.execute("DELETE FROM core.context_checks WHERE competition_season_id = %s", (seed.season_id,))
        conn.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                     (seed.fixture_id,))
        due = due_seasons(conn, at=kickoff + timedelta(hours=3))
        assert seed.season_id in [s.competition_season_id for s in due["standings"]]
        conn.rollback()
        conn.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = %s AND season = %s",
                     (current_league["league"], current_league["season"]))
        conn.execute("UPDATE core.competitions SET type = 'league' WHERE id = %s", (seed.competition_id,))
        conn.commit()
