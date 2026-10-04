"""The data truth audit V2 against a real, migrated database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from fbi.truth.baseline import TABLES, baseline, markdown
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def test_the_baseline_reads_every_table_it_names(migrated_database: str, seed: Seed) -> None:
    with psycopg.connect(migrated_database) as conn:
        conn.execute("SET default_transaction_read_only = on")
        b: dict[str, Any] = baseline(conn, at=NOW)
    assert [t["table"] for t in b["tables"]] == [s.table for s in TABLES]
    by_table = {t["table"]: t for t in b["tables"]}
    assert by_table["core.fixtures"]["rows"] >= 1
    assert by_table["core.fixtures"]["span_from"] is not None
    assert by_table["raw.ingestion_payloads"]["rows"] >= 1
    assert {e["endpoint"] for e in b["endpoints"]} >= {"/odds"}
    assert set(b["extra"]) == {"fixtures_by_status", "competitions", "current_seasons", "teams_national", "repairs",
                               "validation"}
    md = markdown(b)
    assert "| `core.fixtures` (fixtures) |" in md
    assert "| `/odds` |" in md
