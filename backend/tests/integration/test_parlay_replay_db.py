"""RP-11.1 against a real PostgreSQL: the script's reading of the shadow's confirmed selections and their settlements is valid SQL over the real tables,
reads nothing it should not and writes nothing (``scripts.ia_parlay_replay``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import ia_parlay_replay as script

from fbi.parlays import replay

pytestmark = pytest.mark.integration


def test_the_reading_runs_over_the_real_tables_and_an_empty_history_says_so(db: psycopg.Connection[Any]) -> None:
    legs = script.read_legs(db, at=datetime(2026, 11, 27, 12, tzinfo=UTC), days=60)
    assert legs == []
    out = replay.report(legs)
    assert out["combinations"] == 0 and out["enough"] is False and out["within_bound"] is None
    text = script.render({**out, "days_back": 60})
    assert "NO se alcanza" in text and "0 combinaciones" in text
