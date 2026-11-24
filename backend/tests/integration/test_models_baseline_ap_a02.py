"""AP-A02 (plan de correcciones UX): the live baseline of ``GET /admin/models`` reads the consensus through its indexes.

In production ``count(DISTINCT fixture_id)`` and ``array_agg(DISTINCT devig_method)`` over millions of rows ran past the statement
timeout and the page answered 500. The figures are the same; only the way they are read changed, so this test fixes what they say.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg

from fbi.api.repositories import analytics as repo
from tests.integration.conftest import Seed

NOW = datetime.now(UTC)
EARLY = NOW - timedelta(hours=3)
LATE = NOW - timedelta(hours=1)


def _fixture(db: psycopg.Connection, seed: Seed, provider_id: int, kickoff: datetime = NOW) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,'NS','scheduled') RETURNING id",
            (provider_id, seed.season_id, seed.home_team_id, seed.away_team_id, kickoff),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def _consensus(db: psycopg.Connection, seed: Seed, fixture_id: int, method: str, as_of: datetime) -> None:
    db.execute(
        "INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,p_fair,n_bookmakers,"
        "overround,best_odds,best_bookmaker_id) VALUES (%s,'1X2','Home',0,%s,%s,0.5,3,1.05,1.90,%s)",
        (fixture_id, as_of, method, seed.bookmaker_id),
    )


def test_without_consensus_the_baseline_is_empty(db: psycopg.Connection, seed: Seed) -> None:
    _fixture(db, seed, 9101)
    base = repo.market_baseline(db)
    assert base["fixtures_with_consensus"] == 0
    assert base["methods"] == []
    assert base["last_as_of"] is None


def test_the_baseline_counts_fixtures_lists_methods_and_finds_the_last_time(db: psycopg.Connection, seed: Seed) -> None:
    one, two = _fixture(db, seed, 9102), _fixture(db, seed, 9103)
    _fixture(db, seed, 9104)  # a fixture with no consensus is not counted
    _consensus(db, seed, one, "shin", EARLY)
    _consensus(db, seed, one, "proportional", LATE)  # two rows of one fixture count once
    _consensus(db, seed, two, "shin", EARLY)
    base = repo.market_baseline(db)
    assert base["fixtures_with_consensus"] == 2
    assert base["methods"] == ["proportional", "shin"]
    assert base["last_as_of"] == LATE


def test_the_methods_are_those_of_the_consensus_in_use_not_of_every_row_ever_stored(db: psycopg.Connection, seed: Seed) -> None:
    """BE-093: ``EXISTS`` per method walked the whole table for a method no row holds (15 s in production). The methods come from
    the fixtures of the last 30 days and the next 7; a method only an old fixture holds is not listed."""
    recent, old = _fixture(db, seed, 9105), _fixture(db, seed, 9106, kickoff=NOW - timedelta(days=200))
    _consensus(db, seed, recent, "shin", EARLY)
    _consensus(db, seed, old, "power", EARLY - timedelta(days=200))
    base = repo.market_baseline(db)
    assert base["methods"] == ["shin"]
    assert base["fixtures_with_consensus"] == 2, "the fixtures count is of all of them, as before"
