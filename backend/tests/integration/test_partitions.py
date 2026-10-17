"""Monthly partitions of the odds time series.

Without them every price lands in the DEFAULT partition and the RANGE pruning
that makes this table survivable does nothing.
"""

from __future__ import annotations

from datetime import date

import psycopg

from fbi.odds.partitions import ensure_partitions


def _partitions(conn: psycopg.Connection, parent: str = "odds_snapshots") -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = %s",
            (parent,),
        )
        return {row[0] for row in cur.fetchall()}


def test_partitions_are_created_ahead_of_time(db: psycopg.Connection) -> None:
    created = ensure_partitions(db, today=date(2026, 11, 20), months_ahead=3)
    try:
        assert created == [
            "market.odds_snapshots_2026_11",
            "market.odds_snapshots_2026_12",
            "market.odds_snapshots_2027_01",
            "market.odds_snapshots_2027_02",
        ], "the pre-match series is maintained, and the year boundary must not be skipped"
        assert "odds_snapshots_2027_01" in _partitions(db)
        # The in-play series is not: since revision 0068 in-play odds are a bounded current book, and
        # nothing is partitioned for a history that is no longer kept.
        assert not any("live_odds" in name for name in created)
    finally:
        with db.cursor() as cur:
            for name in created:
                cur.execute(f"DROP TABLE IF EXISTS {name}")
        db.commit()


def test_running_it_twice_creates_nothing_new(db: psycopg.Connection) -> None:
    created = ensure_partitions(db, today=date(2026, 11, 20), months_ahead=1)
    try:
        assert ensure_partitions(db, today=date(2026, 11, 20), months_ahead=1) == []
    finally:
        with db.cursor() as cur:
            for name in created:
                cur.execute(f"DROP TABLE IF EXISTS {name}")
        db.commit()


def test_the_default_partition_exists_so_nothing_is_ever_rejected(db: psycopg.Connection) -> None:
    """A price arriving for a month with no partition must still be stored.
    Losing a row because of housekeeping would be the same class of failure the
    rebuild exists to prevent."""
    assert "odds_snapshots_default" in _partitions(db)
