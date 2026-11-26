"""RP-13.3 against a real database: the sheet adds up to what the book of runs and the AI ledger hold for the window."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from scripts import ia_resource_sheet as script

from fbi.ops import resource_sheet as rs

pytestmark = pytest.mark.integration

AT = datetime(2031, 3, 10, 12, tzinfo=UTC)
"""Far in the future: nothing else in the test database sits in this window."""


def _run(db: psycopg.Connection[Any], job: str, status: str, at: datetime, calls: int, mem: dict[str, float] | None) -> None:
    db.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, started_at, finished_at, status, api_calls, params) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
               (f"{job}_t", job, at, at + timedelta(minutes=1), status, calls, json.dumps({"_mem": mem} if mem else {})))


def test_the_sheet_adds_up_to_the_book_and_the_ledger(db: psycopg.Connection[Any]) -> None:
    since, until = AT - timedelta(days=3), AT
    _run(db, "fixtures_sync", "completed", AT - timedelta(days=1), 500, {"rss_max_mib": 900.0, "hwm_mib": 1000.0})
    _run(db, "period_backfill", "aborted", AT - timedelta(days=1, hours=2), 40, {"rss_max_mib": 2700.0, "hwm_mib": 2750.0})
    _run(db, "period_backfill", "interrupted", AT - timedelta(days=2), 10, None)
    _run(db, "results_sync", "failed", AT - timedelta(days=2), 0, {"rss_max_mib": 800.0})
    _run(db, "fixtures_sync", "completed", AT + timedelta(days=1), 99999, {"rss_max_mib": 9999.0})
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status) VALUES (%s, 'pick_review', 'bulk', 'anthropic', 'm', %s, 'ok')",
               (AT - timedelta(days=1), Decimal("1.25")))
    s = rs.read(db, since=since, until=until, month_since=AT.replace(day=1, hour=0))
    assert s.runs == 4 and s.runs_with_memory == 3 and s.api_calls == 550
    assert s.peak_mib == 2700.0 and s.hwm_mib == 2750.0 and s.top_jobs[0] == ("period_backfill", 2700.0)
    assert (s.bad_runs, s.bad_by_status) == (3, {"aborted": 1, "interrupted": 1, "failed": 1})
    assert s.busiest_day_calls == 540
    assert s.spend_usd == Decimal("1.25") and s.month_spend_usd == Decimal("1.25")


def test_the_script_builds_the_pair_of_windows_and_the_alarms(db: psycopg.Connection[Any]) -> None:
    _run(db, "fixtures_sync", "completed", AT - timedelta(days=2), 100, {"rss_max_mib": 1000.0})
    _run(db, "fixtures_sync", "completed", AT + timedelta(days=1), 100, {"rss_max_mib": 2900.0})
    doc = script.build(db, now=AT + timedelta(days=3), days=7, moment=AT, cap=Decimal(185))
    assert doc["after_window_complete"] is False
    assert {a["code"] for a in doc["alarms"]} == {"memoria_cerca_del_limite", "memoria_sube"}
    assert doc["before"]["memory"]["peak_mib"] == 1000.0 and doc["after"]["memory"]["peak_mib"] == 2900.0
    assert "Alarmas" in script.render(doc)
