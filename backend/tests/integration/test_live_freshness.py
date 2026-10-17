"""Live freshness: a match in play counts as read when the follower asked for it, not only when its answer changed."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.truth.freshness import measure
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 5, 15, 58, tzinfo=UTC)
KICKOFF = NOW - timedelta(minutes=58)
LABEL = "Half-time League 2026"


@pytest.fixture
def conn(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                         "competition_type, is_tracked) VALUES (9931, 'Half-time League', 'league', 'club', "
                         "'domestic_league', true) RETURNING id").fetchone()
        assert comp is not None
        season = c.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
                           "VALUES (%s, 2026, true) RETURNING id", (comp[0],)).fetchone()
        assert season is not None
        # The last answer that changed anything was indexed 6 minutes ago (the whistle for half-time).
        c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                  "kickoff_at, status_short, status_group, source_payload_hash, source_fetched_at) "
                  "VALUES (99_310, %s, %s, %s, %s, 'HT', 'live', %s, %s)",
                  (season[0], seed.home_team_id, seed.away_team_id, KICKOFF, seed.payload_hash,
                   NOW - timedelta(minutes=6)))
        yield c
        c.rollback()


def live(conn: psycopg.Connection) -> dict[str, int]:
    found = {f.dataset: f for f in measure(conn, at=NOW)}["live"]
    return {k: v for k, v in found.by_competition[LABEL].items() if v}


def pass_at(conn: psycopg.Connection, started: datetime, status: str) -> None:
    conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at, finished_at) "
                 "VALUES ('live', 'live_match_capture', %s, %s, %s)", (status, started, started))


def test_a_match_asked_every_minute_at_half_time_is_fresh_though_its_answer_did_not_change(
        conn: psycopg.Connection) -> None:
    assert live(conn) == {"STALE": 1}, "nothing says it was asked since its last change"
    pass_at(conn, NOW - timedelta(minutes=1), "completed")
    assert live(conn) == {"FRESH": 1}


def test_a_capped_or_failed_pass_does_not_vouch_for_a_match(conn: psycopg.Connection) -> None:
    pass_at(conn, NOW - timedelta(minutes=1), "aborted")
    pass_at(conn, NOW - timedelta(seconds=30), "partial")
    assert live(conn) == {"STALE": 1}, "a capped pass may not have reached it; a pass with errors may have lost it"


def test_a_pass_outside_the_follow_window_does_not_vouch_for_a_match(conn: psycopg.Connection) -> None:
    conn.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE provider_fixture_id = 99310",
                 (NOW - timedelta(hours=3, minutes=5),))
    pass_at(conn, NOW - timedelta(minutes=1), "completed")
    assert live(conn) == {"STALE": 1}, "three hours after kick-off the follower no longer asks for it"
