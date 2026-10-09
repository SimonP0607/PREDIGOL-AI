"""A worker that stops part-way through an AI cycle leaves nothing 'running' after it starts again (9 Oct 2026).

The 13:00 UTC restart on the server stopped analysis cycle 87 mid-way; its row stayed 'running' and the dashboard
showed a cycle in progress for hours. At start the worker now closes, as failed, every cycle and "run now" request
opened before it - only the worker runs them, so none of them can still be running - and leaves what it pays for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai.cycle import recover_interrupted

from .conftest import Seed
from .test_ai_decision_layer import Savepoints

START = datetime(2032, 8, 1, 13, 0, tzinfo=UTC)


def test_cycles_and_requests_left_running_by_a_stopped_worker_are_closed_at_start(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    conn: Any = Savepoints(db)
    rows = conn.execute(
        "INSERT INTO ai.cycles (kind, started_at, mode, budget_state, cost_usd) VALUES "
        "('analysis', %s, 'shadow', 'NORMAL', 0.42), ('analysis', %s, 'shadow', 'NORMAL', 0) RETURNING id",
        (START - timedelta(minutes=2), START + timedelta(seconds=5))).fetchall()
    stale, current = (int(r[0]) for r in rows)
    req = conn.execute("INSERT INTO ai.run_requests (kind, requested_at, status, picked_at) VALUES "
                       "('analysis', %s, 'running', %s) RETURNING id",
                       (START - timedelta(minutes=3), START - timedelta(minutes=2))).fetchone()[0]

    assert recover_interrupted(conn, before=START, at=START + timedelta(seconds=1)) == (1, 1)

    got = {int(i): (s, f is not None, e, c) for i, s, f, e, c in conn.execute(
        "SELECT id, status, finished_at, error, cost_usd FROM ai.cycles WHERE id IN (%s, %s)", (stale, current))}
    assert got[stale][0] == "failed" and got[stale][1] and "interrupted" in got[stale][2]
    assert float(got[stale][3]) == 0.42, "what the cycle paid for stays on the record"
    assert got[current][:2] == ("running", False), "a cycle this worker opened is left alone"
    assert conn.execute("SELECT status FROM ai.run_requests WHERE id = %s", (req,)).fetchone() == ("failed",)
    assert recover_interrupted(conn, before=START, at=START) == (0, 0), "nothing twice"
