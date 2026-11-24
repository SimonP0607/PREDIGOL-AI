"""OPS-017: the in-play count of the server's health check (deploy/vps/bin/healthcheck.sh), run on PostgreSQL as the script runs it."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import count

import psycopg
import pytest

from tests.unit.test_vps_healthcheck import in_play_query

pytestmark = pytest.mark.integration
_ids = count(930_000)


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        yield c
        c.rollback()


def _one(c: psycopg.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def _fixture(c: psycopg.Connection, cs: int, status: str, kickoff_sql: str) -> None:
    home = _one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'A') RETURNING id", (next(_ids),))
    away = _one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'B') RETURNING id", (next(_ids),))
    c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
              f"status_short, status_group) VALUES (%s, %s, %s, %s, {kickoff_sql}, %s, %s)",
              (next(_ids), cs, home, away, status, "finished" if status == "FT" else "live"))


def test_only_a_match_that_kicked_off_in_the_last_three_and_a_half_hours_counts_as_in_play(conn: psycopg.Connection) -> None:
    """24 Nov 2026 in production: three fixtures stored 'live' - INT since 31 Aug and since 14 Oct, and HT with its kick-off on 22 May
    2027 (a provider's error) - and nothing on the pitch. The count must be 0, and 1 once a real match is in its first half."""
    c = conn
    c.execute("UPDATE core.fixtures SET status_group = 'finished' WHERE status_group = 'live'")  # this test's own rows only count
    comp = _one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                   "VALUES (%s, 'Premier League', 'league', 'club', 'domestic_league', true) RETURNING id", (next(_ids),))
    cs = _one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
    _fixture(c, cs, "INT", "now() - interval '85 days'")
    _fixture(c, cs, "INT", "now() - interval '41 days'")
    _fixture(c, cs, "HT", "now() + interval '179 days'")
    _fixture(c, cs, "FT", "now() - interval '2 hours'")
    query = in_play_query()
    assert _one(c, query) == 0
    _fixture(c, cs, "1H", "now() - interval '20 minutes'")
    assert _one(c, query) == 1
