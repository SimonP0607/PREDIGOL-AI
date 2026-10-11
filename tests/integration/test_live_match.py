"""Following matches in play: states append on change, detail and status go through
the monotonic writers, and nothing is followed that is not ours."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ingestion import live_match
from fbi.ingestion.live_match import (
    capture_live_matches,
    fixtures_to_follow,
    iter_live_states,
    post_match_to_refresh,
    prematch_lineups_due,
    refresh_post_match,
    refresh_prematch_lineups,
    repair_stale_results,
    stale_to_repair,
    write_states,
)
from fbi.providers.api_football.details import iter_fixture_details
from fbi.providers.base import RawResponse
from tests.integration.conftest import Seed


def _body(pid: int, league: int, season: int, home: int, away: int, *, short: str, elapsed: int | None,
          gh: int | None, ga: int | None, kickoff: datetime) -> dict[str, Any]:
    return {"response": [{
        "fixture": {"id": pid, "date": kickoff.isoformat(), "timestamp": int(kickoff.timestamp()),
                    "status": {"short": short, "long": short, "elapsed": elapsed, "extra": None},
                    "venue": {"id": None, "name": None, "city": None}},
        "league": {"id": league, "season": season, "round": "Regular Season - 1"},
        "teams": {"home": {"id": home, "name": "Home FC"}, "away": {"id": away, "name": "Away FC"}},
        "goals": {"home": gh, "away": ga},
        "score": {"halftime": {"home": None, "away": None}, "fulltime": {"home": gh if short == "FT" else None,
                                                                         "away": ga if short == "FT" else None},
                  "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
        "events": [{"time": {"elapsed": 12, "extra": None}, "team": {"id": home}, "player": {"id": 1, "name": "A"},
                    "assist": {"id": None, "name": None}, "type": "Goal", "detail": "Normal Goal", "comments": None}],
        "lineups": [], "statistics": [], "players": [],
    }]}


class FakeProvider:
    def __init__(self, conn: psycopg.Connection, bodies: list[dict[str, Any]]) -> None:
        from fbi.providers.api_football import ApiFootballProvider
        self._parser = ApiFootballProvider.__new__(ApiFootballProvider)
        self.conn = conn
        self.bodies = bodies
        self.calls: list[list[int]] = []

    def parse_fixtures(self, body: dict[str, Any]) -> Any:
        return self._parser.parse_fixtures(body)

    def parse_results(self, body: dict[str, Any]) -> Any:
        return self._parser.parse_results(body)

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> Any:
        self.calls.append(provider_fixture_ids)
        body = self.bodies.pop(0)
        at = datetime.now(UTC)
        h = f"live-match-{len(self.calls)}-{at.timestamp()}"
        raw = RawResponse(endpoint="/fixtures", params={}, fetched_at=at, http_status=200, results_count=1,
                          payload_hash=h, file_path="x", bytes_written=1, body=body)
        return list(iter_fixture_details(body)), raw


_PIDS = itertools.count(8800001)


@pytest.fixture
def fixture_in_play(migrated_database: str, seed: Seed) -> Iterator[tuple[int, int, dict[str, int]]]:
    kickoff = datetime.now(UTC) - timedelta(minutes=30)
    pid = next(_PIDS)
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("SELECT c.provider_league_id, cs.season FROM core.competition_seasons cs "
                    "JOIN core.competitions c ON c.id = cs.competition_id WHERE cs.id = %s", (seed.season_id,))
        league, season = cur.fetchone()  # type: ignore[misc]
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (77001,'Home FC'),(77002,'Away FC') "
                    "ON CONFLICT (provider_team_id) DO UPDATE SET name = EXCLUDED.name RETURNING id")
        home, away = (r[0] for r in cur.fetchall())
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                    "away_team_id, kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,'NS',"
                    "'scheduled') RETURNING id", (pid, seed.season_id, home, away, kickoff))
        fid = cur.fetchone()[0]  # type: ignore[index]
    yield fid, pid, {"league": int(league), "season": int(season), "kickoff": int(kickoff.timestamp())}
    # Leave the shared test database as it was: other suites count runs, quota and live states.
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM raw.ingestion_runs WHERE job_type IN ('live_match_capture', 'results_repair', "
                    "'post_match_detail', 'prematch_lineups') OR job_name = 't'")
        runs = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM core.fixtures WHERE id = %s", (fid,))
        if runs:
            cur.execute("DELETE FROM core.fixture_live_states WHERE payload_hash IN "
                        "(SELECT hash FROM raw.ingestion_payloads WHERE run_id = ANY(%s))", (runs,))
            cur.execute("DELETE FROM audit.data_quality_issues WHERE run_id = ANY(%s)", (runs,))
            cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id = ANY(%s)", (runs,))
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (runs,))
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))


def test_iter_live_states_reads_status_minute_and_score() -> None:
    body = {"response": [{"fixture": {"id": 5, "status": {"short": "2H", "elapsed": 63, "extra": None}},
                          "goals": {"home": 2, "away": 1}},
                         {"fixture": {"id": 6, "status": {}}, "goals": {}},
                         {"fixture": {"status": {"short": "1H"}}}]}
    states = list(iter_live_states(body))
    assert len(states) == 1
    assert states[0].key() == ("2H", 63, None, 2, 1)


async def test_a_match_in_play_is_followed_and_its_state_recorded_once_per_change(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    fid, pid, meta = fixture_in_play
    ko = datetime.fromtimestamp(meta["kickoff"], tz=UTC)
    with psycopg.connect(migrated_database) as conn:
        assert (fid, pid) in fixtures_to_follow(conn, at=datetime.now(UTC))
        provider = FakeProvider(conn, [
            _body(pid, meta["league"], meta["season"], 77001, 77002, short="1H", elapsed=30, gh=1, ga=0, kickoff=ko),
            _body(pid, meta["league"], meta["season"], 77001, 77002, short="1H", elapsed=30, gh=1, ga=0, kickoff=ko),
            _body(pid, meta["league"], meta["season"], 77001, 77002, short="FT", elapsed=90, gh=2, ga=0, kickoff=ko),
        ])
        first = await capture_live_matches(conn, provider)
        second = await capture_live_matches(conn, provider)  # unchanged: no new state row
        assert first.ended == [] and second.ended == [], "in play: nothing to settle yet"
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM core.fixture_live_states WHERE fixture_id = %s", (fid,))
            assert cur.fetchone()[0] == 1  # type: ignore[index]
            cur.execute("SELECT status_group FROM core.fixtures WHERE id = %s", (fid,))
            assert cur.fetchone()[0] == "live"  # type: ignore[index]
            cur.execute("SELECT count(*) FROM core.fixture_events WHERE fixture_id = %s", (fid,))
            assert cur.fetchone()[0] == 1  # type: ignore[index]
        third = await capture_live_matches(conn, provider)
        assert third.ended == [fid], "the pass that sees the final whistle hands the match to the fast settlement"
        with conn.cursor() as cur:
            cur.execute("SELECT status_short, goals_home FROM core.fixture_live_states WHERE fixture_id = %s "
                        "ORDER BY observed_at DESC LIMIT 1", (fid,))
            assert cur.fetchone() == ("FT", 2)
            cur.execute("SELECT status_group FROM core.fixtures WHERE id = %s", (fid,))
            assert cur.fetchone()[0] == "finished"  # type: ignore[index]
            cur.execute("SELECT goals_home, goals_away FROM core.fixture_results WHERE fixture_id = %s", (fid,))
            assert cur.fetchone() == (2, 0)
        # finished: no longer followed, so the next pass spends nothing
        assert (fid, pid) not in fixtures_to_follow(conn, at=datetime.now(UTC))
        assert len(provider.calls) == 3


def test_an_older_state_never_lands_after_a_newer_one(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    from fbi.ingestion.live_match import LiveMatchState
    _, pid, _ = fixture_in_play
    t1 = datetime.now(UTC)
    with psycopg.connect(migrated_database) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type) VALUES ('t','t') RETURNING id")
            run = cur.fetchone()[0]  # type: ignore[index]
            for h in ("lm-a", "lm-b"):
                cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, "
                            "fetched_at, http_status, results_count, file_path, bytes) VALUES (%s,%s,"
                            "'api_football','/fixtures','{}'::jsonb,now(),200,1,'x',1) ON CONFLICT DO NOTHING",
                            (h, run))
        assert write_states(conn, [LiveMatchState(pid, "2H", 70, None, 1, 1)], observed_at=t1, payload_hash="lm-a") == 1
        assert write_states(conn, [LiveMatchState(pid, "2H", 50, None, 1, 0)],
                            observed_at=t1 - timedelta(minutes=20), payload_hash="lm-b") == 0


async def test_a_match_the_date_sweep_missed_is_repaired_by_id(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    fid, pid, meta = fixture_in_play
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    with psycopg.connect(migrated_database) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (two_days_ago, fid))
        conn.commit()
        assert (fid, pid) in stale_to_repair(conn, at=datetime.now(UTC))
        assert (fid, pid) not in fixtures_to_follow(conn, at=datetime.now(UTC))
        provider = FakeProvider(conn, [
            _body(pid, meta["league"], meta["season"], 77001, 77002, short="FT", elapsed=90, gh=0, ga=3,
                  kickoff=two_days_ago),
        ])
        report = await repair_stale_results(conn, provider)
        assert report.requests == 1 and report.results_written == 1
        assert report.ended == [fid]
        with conn.cursor() as cur:
            cur.execute("SELECT status_group FROM core.fixtures WHERE id = %s", (fid,))
            assert cur.fetchone()[0] == "finished"  # type: ignore[index]
        assert (fid, pid) not in stale_to_repair(conn, at=datetime.now(UTC))


async def test_a_late_read_is_asked_once_even_when_the_answer_did_not_change(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    fid, pid, meta = fixture_in_play
    yesterday = datetime.now(UTC) - timedelta(hours=30)
    body = _body(pid, meta["league"], meta["season"], 77001, 77002, short="FT", elapsed=90, gh=1, ga=0,
                 kickoff=yesterday)
    with psycopg.connect(migrated_database) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = 'FT', status_group = 'finished' "
                        "WHERE id = %s", (yesterday, fid))
        conn.commit()
        provider = FakeProvider(conn, [body, body])
        first = await refresh_post_match(conn, provider)
        assert first.requests == 1 and provider.calls == [[pid]]
        stage = conn.execute("SELECT stage FROM core.detail_asks WHERE fixture_id = %s", (fid,)).fetchone()
        assert stage == ("late",)
        assert (fid, pid) not in post_match_to_refresh(conn, at=datetime.now(UTC)), "the late stage is done"
        again = await refresh_post_match(conn, provider)
        assert again.requests == 0 and len(provider.calls) == 1


def test_a_suspended_match_is_still_followed(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    """SUSP is stored in the 'postponed' group, but the match has kicked off and may resume within minutes: the
    live follow keeps asking for it (fbi.core.match_state), and past three hours the results repair does."""
    fid, pid, _ = fixture_in_play
    with psycopg.connect(migrated_database) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET status_short = 'SUSP', status_group = 'postponed' WHERE id = %s",
                        (fid,))
        conn.commit()
        assert (fid, pid) in fixtures_to_follow(conn, at=datetime.now(UTC))
        assert (fid, pid) in stale_to_repair(conn, at=datetime.now(UTC) + timedelta(hours=4))
        with conn.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET status_short = 'PST' WHERE id = %s", (fid,))
        conn.commit()
        assert (fid, pid) not in fixtures_to_follow(conn, at=datetime.now(UTC)), "postponed: not being played"


def test_the_repair_asks_the_match_read_longest_ago_first_and_a_fresh_read_waits(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    """REVIEW 11 Oct 2026 (Rayo Vallecano - Athletic, "INT" for a day): a match the provider has not closed is asked
    again, but a match read recently waits its turn (REPAIR_BACKOFF) and the one read longest ago goes first, so a
    request cap cannot starve an old match behind the newest ones."""
    fid, pid, _ = fixture_in_play
    at = datetime.now(UTC)
    with psycopg.connect(migrated_database) as conn:
        run = conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type) VALUES ('t','t') RETURNING id").fetchone()[0]  # type: ignore[index]
        conn.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, fetched_at, http_status, "
                     "results_count, file_path, bytes) VALUES ('rp-1', %s, 'api_football', '/fixtures', '{}'::jsonb, now(), "
                     "200, 1, 'x', 1) ON CONFLICT DO NOTHING", (run,))
        conn.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = 'INT', status_group = 'live', "
                     "source_payload_hash = 'rp-1', source_fetched_at = %s WHERE id = %s",
                     (at - timedelta(days=2), at - timedelta(minutes=30), fid))
        other_pid = pid + 500_000
        other = conn.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group, source_payload_hash, source_fetched_at) "
            "SELECT %s, competition_season_id, home_team_id, away_team_id, %s, 'NS', 'scheduled', 'rp-1', %s "
            "FROM core.fixtures WHERE id = %s RETURNING id",
            (other_pid, at - timedelta(days=4), at - timedelta(days=3), fid)).fetchone()[0]  # type: ignore[index]
        conn.commit()
        try:
            due = stale_to_repair(conn, at=at)
            assert (fid, pid) not in due, "read 30 minutes ago: at two days old it waits two hours"
            assert (other, other_pid) in due, "read three days ago: due"
            conn.execute("UPDATE core.fixtures SET source_fetched_at = %s WHERE id = %s", (at - timedelta(hours=3), fid))
            conn.commit()
            due = stale_to_repair(conn, at=at)
            assert due.index((other, other_pid)) < due.index((fid, pid)), "the one read longest ago first"
        finally:
            conn.execute("DELETE FROM core.fixtures WHERE id = %s", (other,))
            conn.commit()


def _lineups(home: int, away: int) -> list[dict[str, Any]]:
    def side(team: int, base: int) -> dict[str, Any]:
        xi = [{"player": {"id": base + k, "name": f"P{base + k}", "number": k + 1, "pos": "G" if k == 0 else "D",
                          "grid": f"{1 + (k > 0)}:{1 + k % 4}"}} for k in range(11)]
        return {"team": {"id": team, "name": "T"}, "formation": "4-4-2", "coach": {"id": None, "name": None},
                "startXI": xi, "substitutes": []}
    return [side(home, 600), side(away, 700)]


async def test_the_lineups_of_the_next_75_minutes_are_asked_every_10_minutes_until_they_are_in(
        migrated_database: str, fixture_in_play: tuple[int, int, dict[str, int]]) -> None:
    """REVIEW 11 Oct 2026, point 7: 13 minutes before Barcelona - Getafe the line-ups were not on the page - the
    follow starts only 2 minutes before kick-off. Upcoming matches are now asked from 75 minutes before."""
    fid, pid, meta = fixture_in_play
    live_match._lineups_asked.clear()
    t0 = datetime.now(UTC)
    kickoff = t0 + timedelta(minutes=30)
    without = _body(pid, meta["league"], meta["season"], 77001, 77002, short="NS", elapsed=None, gh=None, ga=None,
                    kickoff=kickoff)
    without["response"][0]["events"] = []
    with_lineups = {"response": [dict(without["response"][0], lineups=_lineups(77001, 77002))]}
    with psycopg.connect(migrated_database) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (kickoff, fid))
        conn.commit()
        assert (fid, pid) in prematch_lineups_due(conn, at=t0)
        assert (fid, pid) not in fixtures_to_follow(conn, at=t0), "30 minutes before: not the follow's yet"
        provider = FakeProvider(conn, [without, with_lineups])
        first = await refresh_prematch_lineups(conn, provider, at=t0)
        assert first.requests == 1 and provider.calls == [[pid]]
        assert (fid, pid) not in prematch_lineups_due(conn, at=t0 + timedelta(minutes=9)), "asked: wait 10 minutes"
        assert (fid, pid) in prematch_lineups_due(conn, at=t0 + timedelta(minutes=10))
        second = await refresh_prematch_lineups(conn, provider, at=t0 + timedelta(minutes=10))
        assert second.requests == 1
        sides = conn.execute("SELECT count(*) FROM core.fixture_lineups WHERE fixture_id = %s", (fid,)).fetchone()
        assert sides == (2,)
        assert (fid, pid) not in prematch_lineups_due(conn, at=t0 + timedelta(minutes=25)), "both in: done"
        assert (fid, pid) not in prematch_lineups_due(conn, at=kickoff - timedelta(minutes=1)), (
            "inside 2 minutes the follow asks every minute anyway")
        assert prematch_lineups_due(conn, at=kickoff - timedelta(hours=2)) == [], "too early: not yet"
        # the line-up players the answer introduced reference its payload: gone before the fixture's teardown
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.fixture_lineups WHERE fixture_id = %s", (fid,))
            cur.execute("DELETE FROM core.players WHERE provider_player_id BETWEEN 600 AND 720")
        conn.commit()
