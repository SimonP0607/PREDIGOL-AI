"""Is THIS host's worker alive? Exit 0 yes, 1 no - for a container healthcheck and the server's monitor.

    python -m scripts.worker_alive              # this host's worker (<hostname>:worker)
    python -m scripts.worker_alive --any        # any worker writing to this database

Alive means what the Admin Console means by it (fbi.ops.heartbeat.Heartbeat.is_alive): it beat within two tick
intervals plus a grace, and did not announce a clean stop after that beat. Read-only; one short query.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from fbi.core.config import settings
from fbi.ops.heartbeat import Heartbeat, default_worker_id, latest_heartbeat

HEARTBEAT_SQL = (
    "SELECT worker_id, hostname, pid, code_version, started_at, last_beat_at, last_tick_at, last_tick_outcome, "
    "last_tick_duration_ms, scheduler_lag_ms, ticks, tick_interval_s, jobs, stopped_at "
    "FROM raw.worker_heartbeats WHERE worker_id = %s"
)


def this_hosts(conn: psycopg.Connection) -> Heartbeat | None:
    with conn.cursor() as cur:
        cur.execute(HEARTBEAT_SQL, (default_worker_id(),))
        r = cur.fetchone()
    if r is None:
        return None
    return Heartbeat(worker_id=str(r[0]), hostname=str(r[1]), pid=int(r[2]), code_version=str(r[3]),
                     started_at=r[4], last_beat_at=r[5], last_tick_at=r[6], last_tick_outcome=r[7],
                     last_tick_duration_ms=r[8], scheduler_lag_ms=r[9], ticks=int(r[10]),
                     tick_interval_s=int(r[11]), jobs=dict(r[12] or {}), stopped_at=r[13])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worker_alive", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--any", action="store_true", help="any worker of this database, not only this host's")
    args = parser.parse_args(argv)
    try:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=5) as conn:
            beat = latest_heartbeat(conn) if args.any else this_hosts(conn)
    except psycopg.Error as exc:
        print(f"worker: database unreachable ({exc.__class__.__name__})")
        return 1
    if beat is None:
        print(f"worker: {'none' if args.any else default_worker_id()} has never beaten")
        return 1
    alive = beat.is_alive()
    print(f"worker {beat.worker_id}: {'alive' if alive else 'NOT alive'}; last beat {beat.last_beat_at.isoformat()}, "
          f"{beat.ticks} ticks, code {beat.code_version}")
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(main())
