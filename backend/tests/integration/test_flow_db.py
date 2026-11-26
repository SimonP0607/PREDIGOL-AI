"""RP-1.2 against a real database: the stages are read from the book of runs and the worker's heartbeat, the counters equal the ones
``GET /admin/ops/jobs`` gives for the same book, and the console carries the panel."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services import intelligence_console as console
from fbi.ops import flow

pytestmark = pytest.mark.integration

JOBS = ("elo_refresh", "feature_build", "period_backfill", "decision_v2_shadow", "tfl_unmapped")


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[Any]:
    c = psycopg.connect(migrated_database, autocommit=True)
    c.execute("DELETE FROM raw.ingestion_runs WHERE job_type = ANY(%s)", (list(JOBS),))
    try:
        yield c
    finally:
        c.execute("DELETE FROM raw.ingestion_runs WHERE job_type = ANY(%s)", (list(JOBS),))
        c.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = 'tfl-worker'")
        c.close()


def run(conn: Any, job: str, status: str, ago: timedelta, at: datetime) -> None:
    conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at, finished_at, params) "
                 "VALUES (%s, %s, %s, %s, %s, '{}'::jsonb)", (job, job, status, at - ago, at - ago + timedelta(seconds=5)))


def by_stage(conn: Any, at: datetime) -> dict[str, flow.StageFlow]:
    stages, _ = flow.read(conn, at=at)
    return {s.stage: s for s in stages}


def test_the_counters_and_the_colour_come_from_one_rule(conn: Any) -> None:
    at = datetime.now(UTC)
    for _ in range(2):
        run(conn, "period_backfill", "aborted", timedelta(hours=2), at)
    run(conn, "period_backfill", "interrupted", timedelta(hours=3), at)
    run(conn, "period_backfill", "completed", timedelta(hours=26), at)           # outside the window
    run(conn, "elo_refresh", "completed", timedelta(hours=1), at)
    run(conn, "feature_build", "failed", timedelta(hours=5), at)
    run(conn, "feature_build", "completed", timedelta(hours=1), at)
    run(conn, "tfl_unmapped", "completed", timedelta(hours=1), at)
    got = by_stage(conn, at)
    ingest, models = got["ingest"], got["models"]
    assert (ingest.state, ingest.reason, ingest.worst_job) == ("error", "ultima_abortada", "period_backfill")
    assert (ingest.aborted, ingest.interrupted, ingest.failed, ingest.errors, ingest.runs) == (2, 1, 0, 3, 3)
    assert (models.state, models.reason, models.failed, models.errors, models.completed) == ("late", "fallos_en_24h", 1, 1, 2)
    assert got["publication"].state == "closed" and got["value"].state == "none"
    assert flow.read(conn, at=at)[1] == ["tfl_unmapped"]


def test_the_counts_equal_the_ones_of_the_jobs_endpoint_for_the_same_book(conn: Any) -> None:
    from fbi.api.routers.system import JOBS_SQL

    at = datetime.now(UTC)
    for status, ago in (("completed", 1), ("failed", 2), ("partial", 3), ("completed", 30)):
        run(conn, "elo_refresh", status, timedelta(hours=ago), at)
    rows = {r[0]: r for r in conn.execute(JOBS_SQL).fetchall()}
    runs_24h, failed_24h, partial_24h = rows["elo_refresh"][1:4]
    got = next(r for r in flow.read_rows(conn, at=at) if r.job_type == "elo_refresh")
    assert (got.runs, got.failed, got.partial) == (runs_24h, failed_24h, partial_24h) == (3, 1, 1)
    assert got.last_status == rows["elo_refresh"][5]


def test_a_run_that_began_after_the_moment_asked_is_not_read(conn: Any) -> None:
    at = datetime.now(UTC)
    run(conn, "elo_refresh", "completed", timedelta(hours=1), at)
    run(conn, "elo_refresh", "failed", -timedelta(hours=1), at)
    assert by_stage(conn, at)["models"].state == "ok"


def test_the_next_run_of_the_heartbeat_makes_a_stage_late(conn: Any) -> None:
    at = datetime.now(UTC)
    run(conn, "decision_v2_shadow", "completed", timedelta(hours=1), at)
    nxt = (at - timedelta(minutes=20)).isoformat()
    conn.execute("INSERT INTO raw.worker_heartbeats (worker_id, hostname, pid, code_version, started_at, last_beat_at, tick_interval_s, jobs) "
                 "VALUES ('tfl-worker', 'h', 1, 'x', %s, %s, 60, %s::jsonb)", (at - timedelta(hours=2), at, f'{{"decision_v2_shadow": "{nxt}"}}'))
    got = by_stage(conn, at)["value"]
    assert (got.state, got.reason) == ("late", "atrasada_mas_de_15_min")


def test_the_console_carries_the_panel_and_the_cycle(conn: Any) -> None:
    at = datetime.now(UTC)
    run(conn, "elo_refresh", "completed", timedelta(hours=1), at)
    with psycopg.connect(conn.info.dsn) as reader:
        built = console.build(reader, at=at)
    assert built.flow is not None and not hasattr(built.flow, "read_failed")
    panel = built.flow.panel  # type: ignore[union-attr]
    assert panel is not None and [s.stage for s in panel.stages] == list(flow.STAGES)
    assert len(built.flow.cycle.stages) == 12  # type: ignore[union-attr]
    dumped = built.model_dump(mode="json")
    assert dumped["flow"]["panel"]["rule_version"] == flow.VERSION
