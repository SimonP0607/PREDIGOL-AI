"""Close ledger runs whose process can no longer exist.

A run row is written 'running' when a job starts and closed when it ends. If
the process dies with the machine (shutdown, sleep that kills WSL, a crash of
Docker Desktop) the row stays 'running' for ever and the health check reports
the worker as degraded for ever.

The rule here is deliberately narrow: a run that STARTED BEFORE THIS MACHINE
LAST BOOTED cannot still be running on it. Everything that writes the ledger
(worker, CLI scripts) runs on one machine, so this never closes a live run -
unlike an age cut-off, which would close a long historical backfill started
from the command line an hour ago.

What the run managed to write before it died stays: only its status changes,
to 'interrupted', with the reason in last_error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

REASON = "interrupted: its process ended before the run finished (machine restart); closed at worker startup"


def boot_time(proc_stat: Path = Path("/proc/stat")) -> datetime | None:
    """When this kernel booted, from /proc/stat's ``btime``. None where it cannot be read."""
    try:
        for line in proc_stat.read_text().splitlines():
            if line.startswith("btime "):
                return datetime.fromtimestamp(int(line.split()[1]), tz=UTC)
    except (OSError, ValueError):
        return None
    return None


def reap_interrupted_runs(conn: psycopg.Connection[Any], booted_at: datetime | None) -> list[int]:
    """Mark 'running' rows that began before ``booted_at`` as 'interrupted'. Returns their ids."""
    if booted_at is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE raw.ingestion_runs
               SET status = 'interrupted',
                   finished_at = COALESCE(finished_at, now()),
                   last_error = COALESCE(last_error || ' | ', '') || %s
             WHERE status = 'running' AND started_at < %s
         RETURNING id
            """,
            (REASON, booted_at),
        )
        ids = [int(r[0]) for r in cur.fetchall()]
    conn.commit()
    return sorted(ids)
