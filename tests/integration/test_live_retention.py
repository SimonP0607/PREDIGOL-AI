"""Retiring a live partition: archived, verified, and only then dropped.

The thing being guarded is the order. An archive written after the drop is no
archive at all, and an archive nobody has read back is a hope - the same lesson
the database backup learned when a restore test first ran against it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from fbi.odds.live_archive import (
    archive,
    months_before,
    partitions,
    plan,
    sha256_file,
    verify,
)
from tests.integration.conftest import Seed

OLD = datetime(2025, 3, 15, 20, 0, tzinfo=UTC)
PARTITION = "live_odds_snapshots_2025_03"


@pytest.fixture()
def old_partition(db: psycopg.Connection, seed: Seed) -> Iterator[int]:
    """A month of live data from long enough ago to be retired."""
    with db.cursor() as cur:
        cur.execute(
            "CREATE TABLE market.live_odds_snapshots_2025_03 "
            "PARTITION OF market.live_odds_snapshots "
            "FOR VALUES FROM ('2025-03-01') TO ('2025-04-01')"
        )
        for n in range(50):
            cur.execute(
                "INSERT INTO market.live_odds_snapshots "
                "(fixture_id, provider_bet_id, market_key, selection, line, "
                " odds_decimal, is_suspended, elapsed_minute, score_home, "
                " score_away, status_long, captured_at, payload_hash) "
                "VALUES (%s, 59, '1X2', 'Home', 0, %s, false, %s, 0, 0, "
                "        'First Half', %s, 'h1')",
                (seed.fixture_id, Decimal("2.00") + Decimal(n) / 100,
                 10 + n % 80, OLD.replace(minute=n % 60)),
            )
    db.commit()
    yield 50
    with db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS market.live_odds_snapshots_2025_03")
    db.commit()


# --- the boundary -----------------------------------------------------------


def test_months_before_crosses_a_year_without_tripping() -> None:
    assert months_before(date(2026, 10, 1), 12) == date(2025, 10, 1)
    assert months_before(date(2026, 1, 15), 1) == date(2025, 12, 1)
    assert months_before(date(2026, 1, 15), 13) == date(2024, 12, 1)
    assert months_before(date(2026, 10, 1), 0) == date(2026, 10, 1)


def test_the_plan_separates_what_stays_from_what_goes(
    db: psycopg.Connection, old_partition: int
) -> None:
    p = plan(db, today=date(2026, 10, 1), retention_months=12)
    assert p.cutoff == date(2025, 10, 1)
    assert PARTITION in {x.name for x in p.retire}
    assert PARTITION not in {x.name for x in p.keep}
    assert p.rows_to_retire >= old_partition


def test_a_recent_partition_is_never_retired(
    db: psycopg.Connection, old_partition: int
) -> None:
    """The live capture is writing into this month. Retiring it would drop rows
    while they were being written."""
    p = plan(db, today=date(2025, 4, 1), retention_months=12)
    assert p.retire == []
    assert PARTITION in {x.name for x in p.keep}


def test_the_row_count_is_counted_not_estimated(
    db: psycopg.Connection, old_partition: int
) -> None:
    """reltuples is an estimate and this decides what gets deleted."""
    found = next(p for p in partitions(db) if p.name == PARTITION)
    assert found.rows == old_partition
    assert found.year == 2025 and found.month == 3


# --- the archive ------------------------------------------------------------


def test_an_archive_is_written_checksummed_and_read_back(
    db: psycopg.Connection, old_partition: int, tmp_path: Path
) -> None:
    part = next(p for p in partitions(db) if p.name == PARTITION)
    result = archive(db, part, tmp_path, drop=False)

    assert result.verified
    assert result.rows_expected == result.rows_written == result.rows_read_back
    assert result.path.exists()
    assert result.sha256 == sha256_file(result.path)
    assert verify(tmp_path) == []
    assert not result.dropped, "drop=False must leave the table alone"

    with db.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM market.{PARTITION}")
        row = cur.fetchone()
    assert row is not None and row[0] == old_partition


def test_parquet_is_much_smaller_than_the_postgres_pages(
    db: psycopg.Connection, old_partition: int, tmp_path: Path
) -> None:
    """The series is a column store's best case: most of every row is a repeated
    fixture id, bet id, selection and match state."""
    part = next(p for p in partitions(db) if p.name == PARTITION)
    result = archive(db, part, tmp_path, drop=False)
    assert result.bytes < part.bytes


def test_the_archived_month_is_still_queryable_without_postgres(
    db: psycopg.Connection, old_partition: int, tmp_path: Path
) -> None:
    """Which is the point of Parquet over a pg_dump of one table: an archived
    month can be read where it lies."""
    import duckdb

    part = next(p for p in partitions(db) if p.name == PARTITION)
    result = archive(db, part, tmp_path, drop=False)
    rows = duckdb.sql(
        f"SELECT count(*), min(odds_decimal), max(odds_decimal) "
        f"FROM read_parquet('{result.path}')"
    ).fetchone()
    assert rows is not None
    assert rows[0] == old_partition


# --- the drop ---------------------------------------------------------------


def test_the_partition_is_dropped_only_after_the_archive_verifies(
    db: psycopg.Connection, old_partition: int, tmp_path: Path
) -> None:
    part = next(p for p in partitions(db) if p.name == PARTITION)
    result = archive(db, part, tmp_path, drop=True)
    assert result.verified and result.dropped

    assert PARTITION not in {p.name for p in partitions(db)}
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace "
            "WHERE n.nspname='market' AND c.relname = %s",
            (PARTITION,),
        )
        row = cur.fetchone()
    assert row is not None and row[0] == 0, "the table is gone, not just detached"
    assert verify(tmp_path) == [], "and its archive is still sound"


def test_an_empty_partition_is_not_treated_as_a_successful_archive(
    db: psycopg.Connection, seed: Seed, tmp_path: Path
) -> None:
    """Zero rows read back from a partition that should have had some is
    indistinguishable from a failed read, so it never licenses a drop."""
    with db.cursor() as cur:
        cur.execute(
            "CREATE TABLE market.live_odds_snapshots_2025_02 "
            "PARTITION OF market.live_odds_snapshots "
            "FOR VALUES FROM ('2025-02-01') TO ('2025-03-01')"
        )
    db.commit()
    try:
        part = next(
            p for p in partitions(db) if p.name == "live_odds_snapshots_2025_02"
        )
        result = archive(db, part, tmp_path, drop=True)
        assert not result.verified
        assert not result.dropped
        assert "live_odds_snapshots_2025_02" in {p.name for p in partitions(db)}
    finally:
        with db.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS market.live_odds_snapshots_2025_02")
        db.commit()


def test_a_tampered_archive_is_caught_by_verify(
    db: psycopg.Connection, old_partition: int, tmp_path: Path
) -> None:
    part = next(p for p in partitions(db) if p.name == PARTITION)
    result = archive(db, part, tmp_path, drop=False)
    result.path.write_bytes(result.path.read_bytes() + b"junk")
    problems = verify(tmp_path)
    assert problems and "checksum" in problems[0]


def test_verify_says_so_when_there_is_no_manifest(tmp_path: Path) -> None:
    assert verify(tmp_path) == [f"{tmp_path / 'manifest.json'} is missing"]
