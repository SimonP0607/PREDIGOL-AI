"""Monthly partition maintenance for the odds time series.

``market.odds_snapshots`` is RANGE partitioned on ``captured_at``. Without a partition for the
current month every row lands in the DEFAULT partition and the pruning that makes the table
survivable does nothing.

The in-play series (``market.live_odds_snapshots``) was maintained here too until revision 0068
made in-play odds a bounded current book: it receives no row since, and revision 0069 drops it.

Creating partitions AHEAD of time is the point: a partition created the moment
it is needed is a partition created during an incident.
"""

from __future__ import annotations

from datetime import date

import psycopg
import structlog

log = structlog.get_logger(__name__)

PARTITION_MONTHS_AHEAD = 3

PARTITIONED_TABLES: tuple[str, ...] = ("odds_snapshots",)
"""Every RANGE-partitioned odds table, so adding one here maintains it everywhere."""


def _month_bounds(table: str, year: int, month: int) -> tuple[str, str, str]:
    nxt_year, nxt_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return (
        f"market.{table}_{year}_{month:02d}",
        f"{year:04d}-{month:02d}-01",
        f"{nxt_year:04d}-{nxt_month:02d}-01",
    )


def ensure_partitions(conn: psycopg.Connection, *, today: date, months_ahead: int = PARTITION_MONTHS_AHEAD) -> list[str]:
    """Create the next N monthly partitions if they do not exist yet."""
    created: list[str] = []
    for table in PARTITIONED_TABLES:
        year, month = today.year, today.month
        for _ in range(months_ahead + 1):
            name, start, end = _month_bounds(table, year, month)
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (name,))
                row = cur.fetchone()
                if row is not None and row[0] is None:
                    cur.execute(
                        f"CREATE TABLE {name} PARTITION OF market.{table} "
                        f"FOR VALUES FROM ('{start}') TO ('{end}')"
                    )
                    created.append(name)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    conn.commit()
    if created:
        log.info("partitions.created", partitions=created)
    return created
