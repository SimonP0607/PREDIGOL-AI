"""PM-02-03: one recalculation of the availability matrix (``fbi.coverage.job``), in a process of its own with a memory cap.

    python -m scripts.availability_refresh            # the night's pass: incremental, full on Sundays
    python -m scripts.availability_refresh --full     # every tracked competition (after an addition, or by hand)
    python -m scripts.availability_refresh --only 7 --only 9   # the competitions of these competition seasons

The worker's scheduler starts it at 08:00 UTC (``apps.worker.scheduler``: only the start); the owner may run it by hand inside the worker's
container (``docker exec predigol-worker python -m scripts.availability_refresh``), away from the copies (03:50-05:00 UTC), the statistics
pass (07:20 UTC) and the ``fixtures_sync``. Before anything else the process:

* caps its address space at ``--max-memory-mib`` (512 by default: the plan's cap) - past it an allocation fails and the run ends, it
  never grows into the worker's 3 GiB;
* asks the kernel to kill it first if the container runs out of memory (``oom_score_adj`` 1000: a process may always raise its own),
  so a shortage costs this run, never the worker;
* lowers its priority (``nice`` 10).

It records one row in the job ledger (``raw.ingestion_runs``, ``availability_refresh``) with what it did, how long it took and the peak
of its memory (``params.memory_peak_mib``: the acceptance asks seven nights with duration and memory). Exit 0 when the pass ran (even
stopped at its time budget: the next night goes on), 1 when it failed, 2 when the switch is off.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import resource
import time
from collections.abc import Sequence

MIB = 1024 * 1024
DEFAULT_CAP_MIB = 512


def cap_memory(mib: int) -> None:
    """The process's own limits, set before the heavy imports. Each step is best effort: where the kernel refuses, the run goes on."""
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (mib * MIB, mib * MIB))
    with contextlib.suppress(OSError), open("/proc/self/oom_score_adj", "w", encoding="ascii") as fh:
        fh.write("1000")
    with contextlib.suppress(OSError):
        os.nice(10)


def peak_mib() -> float:
    """The peak resident memory of this process (``ru_maxrss`` is in KiB on Linux)."""
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--full", action="store_true", help="every tracked competition, not only those with a match in 48 h")
    parser.add_argument("--only", type=int, action="append", help="a competition season (its competition is recalculated)")
    parser.add_argument("--max-memory-mib", type=int, default=DEFAULT_CAP_MIB)
    parser.add_argument("--scheduled", action="store_true", help="started by the worker's scheduler (recorded in the ledger)")
    args = parser.parse_args(argv)
    cap_memory(args.max_memory_mib)

    import psycopg
    from psycopg.types.json import Json

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.coverage import job
    from fbi.ingestion.ledger import RunCounters, RunLedger

    if job.mode() != "on":
        print(f"{job.SWITCH} is off: nothing is recalculated")
        return 2
    started = time.monotonic()
    at = now()
    full = True if args.full or args.only else None
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name=job.JOB) as conn:
        ledger = RunLedger(conn)
        run_id = ledger.open(job.JOB, params={"full": full, "only": args.only, "cap_mib": args.max_memory_mib,
                                              "scheduled": args.scheduled})
        counters = RunCounters()
        report: job.Report | None = None
        try:
            report = job.run_pass(conn, now=at, full=full, only=set(args.only) if args.only else None)
            counters.rows_inserted = report.cells + report.markets
            counters.rows_normalized = report.facts
            counters.errors.extend(report.errors)
            if report.stopped == "otro_pase_en_curso":
                counters.stopped_early = report.stopped
        except Exception as exc:
            counters.errors.append(f"{type(exc).__name__}: {exc}"[:300])
        finally:
            if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                conn.rollback()
            ledger.close(run_id, counters, notes=None if report is None else (report.stopped or None))
            measured = {"memory_peak_mib": peak_mib(), "seconds": round(time.monotonic() - started, 1),
                        "report": None if report is None else report.as_json()}
            conn.execute("UPDATE raw.ingestion_runs SET params = params || %s::jsonb WHERE id = %s", (Json(measured), run_id))
            conn.commit()
            print({"run_id": run_id, "status": counters.status, **measured})
    return 1 if counters.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
