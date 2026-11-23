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

After the pass, once a day while ``FBI_AVAILABILITY_SHADOW`` is on (the default), the same process runs the shadow comparison of PM-02-06
(``fbi.api.services.availability_shadow``: what Mercados, Cuotas, the model's figure and the statistics show today against what the matrix
would say, 500 matches still to be played, into ``analytics.availability_discrepancies``), with its own ledger row (``availability_shadow``).
``--no-shadow`` skips it; ``--shadow-only`` runs only it.

Last, only while ``FBI_MARKET_LEAGUE_STATS`` is on (off by default: PM-05-07), the same process measures the market's margin and dispersion
by competition, market and day (``fbi.market.league_daily``, into ``market.league_daily_stats``) with its own ledger row
(``market_league_stats``), inside what is left of the time the scheduler gives the process. ``--no-market`` skips it; ``--market-only``
runs only it. A measure: nothing reads it to price, pick or decide.

Then, once a week (the first night of the ISO week that finds it not done, so Mondays) and only while ``FBI_MODEL_SEGMENTS`` is on (off by
default: PM-12-06), the same process scores the stored forecasts against the results by competition and by coverage level
(``fbi.coverage.model_segments``, into ``analytics.evaluation_reports`` and ``analytics.evaluation_segments``) with its own ledger row
(``model_segments``); and, only while ``FBI_EVALUATION_BOARD`` is on (off by default: PM-12-01), the weekly board of the last whole
week (``fbi.coverage.weekly_board``: model, market and provider on the same matches, into ``analytics.evaluation_reports``) with its
own row (``evaluation_board``). ``--no-evaluation`` skips both; ``--evaluation-only`` runs only them. They change no pick, model or
forecast.

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
from datetime import datetime
from typing import Any

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
    parser.add_argument("--no-shadow", action="store_true", help="skip the shadow comparison (PM-02-06) after the pass")
    parser.add_argument("--shadow-only", action="store_true", help="only the shadow comparison (PM-02-06)")
    parser.add_argument("--no-market", action="store_true", help="skip the market's margin and dispersion (PM-05-07)")
    parser.add_argument("--market-only", action="store_true", help="only the market's margin and dispersion (PM-05-07)")
    parser.add_argument("--no-evaluation", action="store_true", help="skip the weekly evaluation by competition (PM-12-06)")
    parser.add_argument("--evaluation-only", action="store_true", help="only the weekly evaluation by competition (PM-12-06)")
    args = parser.parse_args(argv)
    process_started = time.monotonic()
    cap_memory(args.max_memory_mib)

    import psycopg
    from psycopg.types.json import Json

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.coverage import job
    from fbi.ingestion.ledger import RunCounters, RunLedger

    if args.shadow_only:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="availability_shadow") as conn:
            shadow_phase(conn, at=now(), started=time.monotonic(), scheduled=args.scheduled)
        return 0
    if args.market_only:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="market_league_stats") as conn:
            market_phase(conn, at=now(), process_started=process_started, scheduled=args.scheduled)
        return 0
    if args.evaluation_only:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="model_segments") as conn:
            evaluation_phase(conn, at=now(), process_started=process_started, scheduled=args.scheduled)
        return 0
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
        if not args.no_shadow:
            shadow_phase(conn, at=at, started=time.monotonic(), scheduled=args.scheduled)
        if not args.no_market:
            market_phase(conn, at=at, process_started=process_started, scheduled=args.scheduled)
        if not args.no_evaluation:
            evaluation_phase(conn, at=at, process_started=process_started, scheduled=args.scheduled)
    return 1 if counters.status == "failed" else 0


SHADOW_DONE_SQL = ("SELECT 1 FROM raw.ingestion_runs WHERE job_type = %s AND status = 'completed' "
                   "AND started_at >= date_trunc('day', %s::timestamptz AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' LIMIT 1")


def shadow_phase(conn: Any, *, at: datetime, started: float, scheduled: bool) -> None:
    """PM-02-06: the day's shadow comparison (``fbi.api.services.availability_shadow``), once a day, with its own ledger row."""
    import psycopg
    from psycopg.types.json import Json

    from fbi.core.version import code_version
    from fbi.coverage import shadow
    from fbi.ingestion.ledger import RunCounters, RunLedger

    if shadow.mode() != "on":
        return
    db = conn
    if db.execute(SHADOW_DONE_SQL, (shadow.JOB, at)).fetchone() is not None:
        db.commit()
        return
    db.commit()
    from fbi.api.services import availability_shadow

    ledger = RunLedger(db)
    run_id = ledger.open(shadow.JOB, params={"scheduled": scheduled, "sample": shadow.SAMPLE})
    counters = RunCounters()
    report = None
    try:
        report = availability_shadow.run(db, at=at, code_version=code_version())
        counters.rows_inserted = report.written
        counters.rows_normalized = report.matches
        if report.stopped:
            counters.stopped_early = report.stopped
    except Exception as exc:
        counters.errors.append(f"{type(exc).__name__}: {exc}"[:300])
    finally:
        if db.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            db.rollback()
        ledger.close(run_id, counters)
        measured = {"memory_peak_mib": peak_mib(), "seconds": round(time.monotonic() - started, 1),
                    "report": None if report is None else report.as_json()}
        db.execute("UPDATE raw.ingestion_runs SET params = params || %s::jsonb WHERE id = %s", (Json(measured), run_id))
        db.commit()
        print({"run_id": run_id, "job": shadow.JOB, "status": counters.status, **measured})


MARKET_MARGIN_SECONDS = 60
"""What the market phase leaves of the time the scheduler gives the whole process (``fbi.coverage.job.PROCESS_TIMEOUT``)."""


def market_phase(conn: Any, *, at: datetime, process_started: float, scheduled: bool) -> None:
    """PM-05-07: the market's margin and dispersion by competition, market and day (``fbi.market.league_daily``), with its own ledger
    row, only while ``FBI_MARKET_LEAGUE_STATS`` is on, and stopping before the scheduler's limit on the whole process."""
    import psycopg
    from psycopg.types.json import Json

    from fbi.coverage import job
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.market import league_daily

    if league_daily.mode() != "on":
        return
    deadline = process_started + job.PROCESS_TIMEOUT - MARKET_MARGIN_SECONDS
    started = time.monotonic()
    if started >= deadline:
        print({"job": league_daily.JOB, "skipped": "sin_tiempo"})
        return
    ledger = RunLedger(conn)
    run_id = ledger.open(league_daily.JOB, params={"scheduled": scheduled, "method_version": league_daily.METHOD_VERSION})
    counters = RunCounters()
    report = None
    try:
        report = league_daily.run_pass(conn, now=at, deadline=deadline)
        counters.rows_inserted = report.rows
        counters.rows_normalized = report.prices
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
        print({"run_id": run_id, "job": league_daily.JOB, "status": counters.status, **measured})


WEEK_DONE_SQL = ("SELECT 1 FROM raw.ingestion_runs WHERE job_type = %s AND status = 'completed' "
                 "AND started_at >= date_trunc('week', %s::timestamptz AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' LIMIT 1")


def evaluation_phase(conn: Any, *, at: datetime, process_started: float, scheduled: bool) -> None:
    """PM-12-06 and PM-12-01: the week's evaluation by competition and coverage level (``fbi.coverage.model_segments``, only while
    ``FBI_MODEL_SEGMENTS`` is on) and the weekly board (``fbi.coverage.weekly_board``, only while ``FBI_EVALUATION_BOARD`` is on),
    each once per ISO week with its own ledger row, stopping before the scheduler's limit on the whole process."""
    from fbi.core.version import code_version
    from fbi.coverage import model_segments as segments
    from fbi.coverage import weekly_board

    def run_segments() -> tuple[int, dict[str, Any]]:
        rep = segments.report(conn, at=at)
        report_id = segments.store(conn, rep, code_version=code_version())
        return (0 if report_id is None else len(rep["segments"]),
                {"report_id": report_id, "reproduced": rep["reproduced"], "incomplete": rep["incomplete"]})

    def run_board() -> tuple[int, dict[str, Any]]:
        rep = weekly_board.report(conn, at=at)
        report_id = weekly_board.store(conn, rep, code_version=code_version())
        return (0 if report_id is None else 1, {"report_id": report_id, "week": [rep["period_from"], rep["period_to"]]})

    for name, on, version, work in ((segments.JOB, segments.mode() == "on", segments.VERSION, run_segments),
                                    (weekly_board.JOB, weekly_board.mode() == "on", weekly_board.VERSION, run_board)):
        if on:
            _weekly_job(conn, name, version, work, at=at, process_started=process_started, scheduled=scheduled)


def _weekly_job(conn: Any, name: str, version: str, work: Any, *, at: datetime, process_started: float, scheduled: bool) -> None:
    import psycopg
    from psycopg.types.json import Json

    from fbi.coverage import job
    from fbi.ingestion.ledger import RunCounters, RunLedger

    if conn.execute(WEEK_DONE_SQL, (name, at)).fetchone() is not None:
        conn.commit()
        return
    conn.commit()
    if time.monotonic() >= process_started + job.PROCESS_TIMEOUT - MARKET_MARGIN_SECONDS:
        print({"job": name, "skipped": "sin_tiempo"})
        return
    started = time.monotonic()
    ledger = RunLedger(conn)
    run_id = ledger.open(name, params={"scheduled": scheduled, "version": version})
    counters = RunCounters()
    measured: dict[str, Any] = {}
    try:
        conn.execute("SET statement_timeout = '120s'")
        rows, measured = work()
        conn.commit()
        counters.rows_inserted = rows
    except Exception as exc:
        counters.errors.append(f"{type(exc).__name__}: {exc}"[:300])
    finally:
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.rollback()
        ledger.close(run_id, counters)
        measured |= {"memory_peak_mib": peak_mib(), "seconds": round(time.monotonic() - started, 1)}
        conn.execute("UPDATE raw.ingestion_runs SET params = params || %s::jsonb WHERE id = %s", (Json(measured), run_id))
        conn.commit()
        print({"run_id": run_id, "job": name, "status": counters.status, **measured})

if __name__ == "__main__":
    raise SystemExit(main())
