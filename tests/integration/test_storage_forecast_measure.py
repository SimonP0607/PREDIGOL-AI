"""The storage forecast's measurements run against the real schema (every table and column it names exists)."""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg
from scripts import storage_forecast as sf


def test_measure_reads_every_growing_table_and_forecasts(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as conn:
        conn.read_only = True
        conn.execute("SET TIME ZONE 'UTC'")
        m = sf.measure(conn, datetime(2030, 1, 10, 12, tzinfo=UTC), days=7)
    assert {t["key"] for t in m["tables"]} == {g.key for g in sf.GROWERS} | {"reference"}, (
        "no table skipped by an SQL error")
    assert m["database_bytes"] > 0 and m["backups"]["dump_ratio"] > 0
    f = sf.forecast(m)
    assert set(f["scenarios"]) == {"current", "current_retention", "plus_50", "plus_50_retention"}
    assert sf.markdown({"at": "2030-01-10T12:00:00+00:00", "code_version": "t", "measured": m, "forecast": f})
