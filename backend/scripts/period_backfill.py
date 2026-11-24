"""PM-05-02: fill the statistics by half of the finished matches since 1-jan-2024, a night at a time, in a process of its own.

    python -m scripts.period_backfill plan                  # what is left, by competition, and the nights it takes (no request)
    python -m scripts.period_backfill from-raw              # keep the PM-01-05 probe's answers from the RAW store (no request)
    python -m scripts.period_backfill run --scheduled       # one night's pass: at most 5,000 requests, between 22:30 and 03:25 UTC

The worker's scheduler starts ``run --scheduled`` at 22:30 UTC, only while ``FBI_STATS_BY_PERIOD_FILL`` is on (off by default), and only
when the container has the room (``fbi.coverage.job.HEADROOM_MIB``). The process:

* caps its address space (``--max-memory-mib``, 384 by default), asks the kernel to kill it first and lowers its priority, like the
  availability matrix's process;
* asks the matches of the eligible competitions (the matrix grades their corners A or B) newest first, once each, 1.5 s apart, and
  leaves alone a competition whose decision is taken and builds nothing (``fbi.core.period_rules``);
* stops by itself at 03:25 UTC (the copies start at 03:50), at ``--max-requests``, when the day's total passes 60 % of the budget
  (``PAUSE_FILLS``, where the plan pauses the fills) or when the ``historicos`` lane is within 100 requests of its ceiling - so
  the Monday's weekly players round, which is that lane's top, always goes first;
* is the ``period_backfill`` job of the lane ``historicos`` (``fbi.providers.lanes``): the client counts what it asks there;
* writes one ledger row (``raw.ingestion_runs``) with what it asked and the peak of its memory (``params.memory_peak_mib``).

Exit 0 when the pass ran (also stopped at its time or its cap: the next night goes on), 1 when it failed, 2 when the switch is off.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import resource
import sys
import time as clock
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any

MIB = 1024 * 1024
DEFAULT_CAP_MIB = 384
NIGHT_MAX = 5_000
"""Requests of one night. The fill is about 53,500 requests once (PM-05-02's ficha): ten nights at this pace, fewer once the competitions
whose decision is 'closed' are left out."""
PACE_SECONDS = 1.5
"""40 requests a minute at most: a fifth of the plan's per-minute limit."""
WINDOW_START = time(22, 30)
STOP_AT = time(3, 25)
"""The scheduled pass runs between these two times (UTC) and stops by itself at the second."""
LANE = "historicos"
LANE_MARGIN = 100
BUDGET_SHARE = 0.60
"""The day's total, as a share of the budget, past which the fills pause (``fbi.providers.lanes.PAUSE_FILLS``)."""
CHECK_SECONDS = 60.0

LEAN_ENV: dict[str, str] = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def cap_memory(mib: int) -> None:
    """The process's own limits, set before the heavy imports (the same as ``scripts.availability_refresh``). Best effort each."""
    for name, value in LEAN_ENV.items():
        os.environ.setdefault(name, value)
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (mib * MIB, mib * MIB))
    with contextlib.suppress(OSError), open("/proc/self/oom_score_adj", "w", encoding="ascii") as fh:
        fh.write("1000")
    with contextlib.suppress(OSError):
        os.nice(10)


def peak_mib(status: str = "/proc/self/status") -> float:
    with contextlib.suppress(OSError, ValueError), open(status, encoding="ascii") as fh:
        for line in fh:
            if line.startswith("VmHWM:"):
                return round(int(line.split()[1]) / 1024, 1)
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def in_window(at: datetime) -> bool:
    """True from 22:30 to 03:25 UTC (the window crosses midnight)."""
    t = at.astimezone(UTC).time()
    return t >= WINDOW_START or t < STOP_AT


def stop_time(at: datetime) -> datetime:
    """The next 03:25 UTC at or after ``at``."""
    moment = at.astimezone(UTC)
    stop = moment.replace(hour=STOP_AT.hour, minute=STOP_AT.minute, second=0, microsecond=0)
    return stop if stop > moment else stop + timedelta(days=1)


def nights_needed(requests: int, per_night: int = NIGHT_MAX) -> int:
    return math.ceil(requests / per_night) if requests > 0 else 0


class Guard:
    """What ``keep_going`` asks before each request: the clock, the quiet window, the day's total and the lane's room. The two reads of
    the database are repeated at most once a minute (``CHECK_SECONDS``)."""

    def __init__(self, conn: Any, *, until: datetime, budget: int, lane_ceiling: int, scheduled: bool, clock_fn: Any = None) -> None:
        self.conn = conn
        self.until = until
        self.budget = budget
        self.lane_ceiling = lane_ceiling
        self.scheduled = scheduled
        self._now = clock_fn or (lambda: datetime.now(UTC))
        self._checked = float("-inf")
        self._ok = True
        self.reason: str | None = None

    def __call__(self) -> bool:
        from fbi.ingestion.period_stats import in_quiet_window

        moment = self._now()
        if moment >= self.until:
            self.reason = "hora de parada"
            return False
        if in_quiet_window(moment):
            self.reason = "ventana de copias"
            return False
        if clock.monotonic() - self._checked >= CHECK_SECONDS:
            self._checked = clock.monotonic()
            self._ok = self._read_ok()
        return self._ok

    def _read_ok(self) -> bool:
        day = self._now().date()
        with self.conn.cursor() as cur:
            cur.execute("SELECT spent FROM raw.provider_quota WHERE provider = 'api_football' AND quota_date = %s", (day,))
            row = cur.fetchone()
            cur.execute("SELECT coalesce(sum(requests), 0)::bigint FROM raw.provider_endpoint_usage "
                        "WHERE provider = 'api_football' AND usage_date = %s AND lane = %s", (day, LANE))
            lane = cur.fetchone()
        self.conn.commit()
        total = int(row[0]) if row else 0
        spent = int(lane[0]) if lane else 0
        if total >= BUDGET_SHARE * self.budget:
            self.reason = f"total del dia {total} >= {int(BUDGET_SHARE * 100)} % del presupuesto"
            return False
        if spent + LANE_MARGIN >= self.lane_ceiling:
            self.reason = f"carril {LANE} {spent}/{self.lane_ceiling}"
            return False
        return True


def plan(conn: Any, *, at: datetime) -> dict[str, Any]:
    """What is left to ask, by competition, with no request: the matches of the eligible competitions not asked, since the fill's start,
    minus the competitions whose decision is taken and builds nothing."""
    from fbi.ingestion import period_stats as ps

    states = ps.competition_state(conn)
    closed = ps.closed_competitions(states)
    wanted = ps.targets(conn, since=ps.FILL_SINCE, until=at - ps.SETTLE, limit=1_000_000, newest_first=True, skip=closed)
    by_comp: dict[int, int] = {}
    for t in wanted:
        by_comp[t.competition_id] = by_comp.get(t.competition_id, 0) + 1
    names: dict[int, str] = {}
    if by_comp:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM core.competitions WHERE id = ANY(%s)", (list(by_comp),))
            names = {int(i): str(n) for i, n in cur.fetchall()}
    rows = [{"competition_id": cid, "name": names.get(cid, ""), "left": n, "asked": states.get(cid, ps.CompetitionState()).asked,
             "gate": states.get(cid, ps.CompetitionState()).gate()} for cid, n in sorted(by_comp.items(), key=lambda kv: -kv[1])]
    return {"left": len(wanted), "nights_at_cap": nights_needed(len(wanted)), "night_max": NIGHT_MAX, "closed_competitions": len(closed),
            "asked_in_total": sum(s.asked for s in states.values()), "competitions": rows}


async def run_night(args: argparse.Namespace, conn: Any) -> dict[str, Any]:
    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.ingestion import period_stats as ps
    from fbi.providers.api_football import ApiFootballProvider
    from fbi.providers.lanes import DEFAULT_LANES
    from scripts.capture_odds import _client

    at = now()
    if args.scheduled and not in_window(at):
        return {"stopped": "fuera de la ventana 22:30-03:25 UTC", "requests": 0}
    until = stop_time(at) if args.scheduled else at + timedelta(minutes=args.max_minutes)
    until = min(until, at + timedelta(minutes=args.max_minutes))
    ceiling = next(lane.ceiling for lane in DEFAULT_LANES if lane.name == LANE)
    guard = Guard(conn, until=until, budget=settings.provider_plan.effective_budget, lane_ceiling=ceiling, scheduled=args.scheduled)
    states = ps.competition_state(conn)
    wanted = ps.targets(conn, since=ps.FILL_SINCE, until=at - ps.SETTLE, limit=args.max_requests + 500, newest_first=True,
                        skip=ps.closed_competitions(states))
    provider = ApiFootballProvider(_client(max_requests=args.max_requests))
    try:
        report = await ps.ask_targets(conn, provider, wanted, job_type=ps.FILL_JOB, channel="backfill", max_requests=args.max_requests,
                                      at=at, states=states, pace_seconds=PACE_SECONDS, keep_going=guard)
    finally:
        await provider.aclose()
    out = report.as_json()
    out["guard"] = guard.reason
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=("plan", "from-raw", "run"))
    parser.add_argument("--max-requests", type=int, default=NIGHT_MAX)
    parser.add_argument("--max-minutes", type=int, default=300)
    parser.add_argument("--max-memory-mib", type=int, default=DEFAULT_CAP_MIB)
    parser.add_argument("--scheduled", action="store_true", help="started by the worker's scheduler: only inside 22:30-03:25 UTC")
    args = parser.parse_args(argv)
    cap_memory(args.max_memory_mib)

    import psycopg
    from psycopg.types.json import Json

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.ingestion import period_stats as ps

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name=ps.FILL_JOB) as conn:
        if args.mode == "plan":
            print(json.dumps(plan(conn, at=now()), indent=1, default=str))
            return 0
        if args.mode == "from-raw":
            from fbi.storage.payload_store import PayloadStore

            print(json.dumps(ps.load_probe_answers(conn, PayloadStore(settings.runtime.raw_store_dir)), indent=1))
            return 0
        if ps.fill_mode() != "on":
            print(f"{ps.BACKFILL_SWITCH} is off: nothing is asked")
            return 2
        started = clock.monotonic()
        try:
            result = asyncio.run(run_night(args, conn))
        except Exception as exc:
            print({"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]})
            return 1
        measured = {"memory_peak_mib": peak_mib(), "seconds": round(clock.monotonic() - started, 1), "scheduled": args.scheduled}
        run_id = result.get("run_id")
        if run_id:
            conn.execute("UPDATE raw.ingestion_runs SET params = params || %s::jsonb WHERE id = %s", (Json({**measured, "report": result}), run_id))
            conn.commit()
        print(json.dumps({**result, **measured}, default=str))
    return 1 if result.get("errors") and not result.get("requests") else 0


if __name__ == "__main__":
    sys.exit(main())
