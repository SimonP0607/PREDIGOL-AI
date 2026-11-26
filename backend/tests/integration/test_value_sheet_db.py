"""RP-12.1 against a real database: the readers run on the migrated schema, read only, and the whole sheet builds from them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from scripts import ia_value_sheet

from fbi.ai import value_sheet, value_sheet_readers

pytestmark = pytest.mark.integration


def test_the_readers_and_the_sheet_run_on_the_migrated_schema(migrated_database: str) -> None:
    now = datetime.now(UTC)
    with psycopg.connect(migrated_database) as conn:
        c = value_sheet_readers.counts(conn, since=now - timedelta(days=7), until=now)
        assert isinstance(c, value_sheet.Counts)
        doc = ia_value_sheet.build(conn, now=now, days=7)
        conn.rollback()
    assert doc["version"] == "value-sheet-v1" and doc["decides"] is False and len(doc["processes"]) == len(value_sheet.PROCESSES)
    assert doc["days"] == 7 and doc["since"] < doc["until"]
