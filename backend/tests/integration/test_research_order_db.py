"""RP-5.4 against a real database: the script reads the universe of the days and the passes kept, and counts by level."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import ia_research_order as script

pytestmark = pytest.mark.integration


def test_an_empty_database_gives_an_empty_sheet(db: psycopg.Connection[Any]) -> None:
    doc = script.build(db, now=datetime(2031, 3, 10, 12, tzinfo=UTC), days=3, slots=10)
    assert doc["matches"] == 0 and doc["level_a_left_out"] == []
    assert set(doc["levels"]) == {"A", "B", "C", "D"} and all(c["matches"] == 0 for c in doc["levels"].values())
