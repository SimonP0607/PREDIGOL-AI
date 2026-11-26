"""PM-05-02: fill the statistics by half of the finished matches since 1-jan-2024, a night at a time, in a process of its own.

    python -m scripts.period_backfill plan                  # what is left, by competition, the nights it takes and the date it ends (no request)
    python -m scripts.period_backfill report                # what came back, by competition: asked, with both halves, the percentage (no request)
    python -m scripts.period_backfill from-raw              # keep the PM-01-05 probe's answers from the RAW store (no request)
    python -m scripts.period_backfill run --scheduled       # one night's pass: at most 5,000 requests, between 22:30 and 03:25 UTC

The worker's scheduler starts ``run --scheduled`` at 22:30 UTC and again every hour until 02:10 (a deploy restarts the worker, and the
process with it, several times a day: the pass is resumable because every match is asked once and remembered), plus once four minutes
after each start of the worker inside the window, only while ``FBI_STATS_BY_PERIOD_FILL`` is on (off by default), and only when the
container has the room the process needs (``fbi.ingestion.period_stats.FILL_HEADROOM_MIB``, 128 MiB: its measured peak was 61.7 MiB in three passes). The
process:

* caps its address space (``--max-memory-mib``, 384 by default), asks the kernel to kill it first and lowers its priority, like the
  availability matrix's process; its database session has its own ``statement_timeout``;
* asks the matches of the eligible competitions (the matrix grades their corners A or B) newest first, once each, 1.5 s apart, and
  leaves alone a competition whose decision is taken and builds nothing (``fbi.core.period_rules``);
* keeps two caps whatever the number of starts: 5,000 requests a NIGHT (from 22:30 UTC, counted in ``core.fixture_period_asks``) and 5,000
  a UTC DAY (``raw.provider_endpoint_usage``, job ``period_backfill``), and stops by itself at 03:25 UTC (the copies start at 03:50), at
  ``--max-requests``, when the day's total passes 60 % of the budget (``PAUSE_FILLS``) - or comes within the emergency reserve of it,
  whichever is first - or when the ``historicos`` lane is within 100 requests of its ceiling. On Mondays it also keeps the room the
  weekly players round of that lane needs (6,700 requests, measured 6,616 on 23-nov-2026; that round starts at 00:10 UTC);
* obeys a STOP ORDER, with no restart: ``touch <raw store>/PARAR_period_backfill`` (in the worker's container: ``/app/data/raw``) or a
  ``SIGTERM`` to the process; it finishes the request in flight, writes its ledger row and ends. The next start does nothing while the
  file is there; remove it to go on. Nothing already kept is touched;
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
import signal
import sys
import time as clock
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

MIB = 1024 * 1024
DEFAULT_CAP_MIB = 384
NIGHT_MAX = 5_000
"""Requests of one night, whichever number of starts asked them. The fill is about 53,500 requests once (PM-05-02's ficha): ten nights at
this pace, fewer once the competitions whose decision is 'closed' are left out."""
DAY_MAX = 5_000
"""Requests of the fill in one UTC day (a night spans two): the lane ceiling (8,000) less what the lane's other jobs need on an ordinary
day (1,200 measured the 25 and 26-nov, 3,000 with the expansions' history) and a margin."""
WEEKLY_ROUND = 6_700
"""What the weekly players round (``historical_backfill``: /players/squads and /players, from 00:10 UTC on Mondays) takes of the lane: 6,616
on Monday 23-nov-2026, the largest day of the lane in 36 days. On Mondays the fill leaves it that room first."""
WEEKLY_WEEKDAY = 0
SUNDAY_NIGHT = 3_700
"""What the night that starts on a Sunday can ask: about 90 minutes before midnight at the measured 28 a minute (2,500) and what the lane
leaves the Monday before its weekly round (8,000 - 100 - 6,700 = 1,200)."""
STOP_FILE = "PARAR_period_backfill"
"""The stop order: a file of this name in the RAW store's directory. Its presence stops the fill at the next request; its removal lets it
go on at the next start."""
STATEMENT_TIMEOUT = "60s"
PLAN_STATEMENT_TIMEOUT = "300s"
STOP_REQUESTED = False
"""Set by SIGTERM: the pass ends at the next request, closes its ledger row, and exits."""
PACE_SECONDS = 1.5
"""40 requests a minute at most: a fifth of the plan's per-minute limit."""
WINDOW_START = time(22, 30)
STOP_AT = time(3, 25)
"""The scheduled pass runs between these two times (UTC) and stops by itself at the second."""
LANE = "historicos"
FILL_JOB = "period_backfill"
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


def finish_estimate(left: int, first_night: date) -> dict[str, Any]:
    """The nights the ``left`` requests take, night by night from the one that starts on ``first_night`` at 22:30 UTC (a Sunday's night
    asks less, see ``SUNDAY_NIGHT``), and the UTC date the last of them ends on. An upper bound on the pace: a night a deploy cuts short
    asks the rest in the next start, and a night with the budget's pause asks less."""
    nights = 0
    day = first_night
    remaining = left
    while remaining > 0 and nights < 400:
        remaining -= SUNDAY_NIGHT if day.weekday() == 6 else NIGHT_MAX
        nights += 1
        day += timedelta(days=1)
    return {"nights": nights, "first_night": first_night.isoformat(),
            "ends_on": (first_night + timedelta(days=nights)).isoformat() if nights else None}


def night_room(done: int, requested: int) -> int:
    """What a start may still ask tonight: ``requested`` (the pass's own cap) less nothing, but never past ``NIGHT_MAX`` in all."""
    return max(0, min(requested, NIGHT_MAX - done))


def night_start(at: datetime) -> datetime:
    """The 22:30 UTC that opened the night ``at`` belongs to (the last one at or before ``at``)."""
    moment = at.astimezone(UTC)
    start = moment.replace(hour=WINDOW_START.hour, minute=WINDOW_START.minute, second=0, microsecond=0)
    return start if start <= moment else start - timedelta(days=1)


def stop_file(raw_store_dir: str) -> Path:
    return Path(raw_store_dir) / STOP_FILE


def request_stop(*_: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


class Guard:
    """What ``keep_going`` asks before each request: the stop order, the clock, the quiet window, the day's total and the lane's room. The
    stop order is read every time (a file's existence); the two reads of the database are repeated at most once a minute
    (``CHECK_SECONDS``)."""

    def __init__(self, conn: Any, *, until: datetime, budget: int, lane_ceiling: int, scheduled: bool, clock_fn: Any = None,
                 reserve: int = 0, stop_path: Path | None = None) -> None:
        self.conn = conn
        self.until = until
        self.budget = budget
        self.lane_ceiling = lane_ceiling
        self.scheduled = scheduled
        self.reserve = reserve
        self.stop_path = stop_path
        self._now = clock_fn or (lambda: datetime.now(UTC))
        self._checked = float("-inf")
        self._ok = True
        self.reason: str | None = None

    def stop_ordered(self) -> bool:
        if STOP_REQUESTED:
            self.reason = "orden de parada (senal)"
            return True
        if self.stop_path is not None and self.stop_path.exists():
            self.reason = f"orden de parada ({STOP_FILE})"
            return True
        return False

    def __call__(self) -> bool:
        from fbi.ingestion.period_stats import in_quiet_window

        if self.stop_ordered():
            return False
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

    def total_limit(self) -> int:
        """The day's total at which the fill stops: 60 % of the budget, or the budget less the emergency reserve if that comes first."""
        return int(min(BUDGET_SHARE * self.budget, self.budget - self.reserve))

    def lane_reserve(self, day: date, other: int) -> int:
        """What the lane keeps for others today: on Mondays what the weekly players round still needs (its 6,700 less what the lane's
        other jobs have spent), nothing otherwise."""
        return max(0, WEEKLY_ROUND - other) if day.weekday() == WEEKLY_WEEKDAY else 0

    def _read_ok(self) -> bool:
        day = self._now().date()
        with self.conn.cursor() as cur:
            cur.execute("SELECT spent FROM raw.provider_quota WHERE provider = 'api_football' AND quota_date = %s", (day,))
            row = cur.fetchone()
            cur.execute("SELECT job, coalesce(sum(requests), 0)::bigint FROM raw.provider_endpoint_usage "
                        "WHERE provider = 'api_football' AND usage_date = %s AND lane = %s GROUP BY job", (day, LANE))
            jobs = {str(j): int(n) for j, n in cur.fetchall()}
        self.conn.commit()
        total = int(row[0]) if row else 0
        spent = sum(jobs.values())
        mine = jobs.get(FILL_JOB, 0)
        limit = self.total_limit()
        if total >= limit:
            self.reason = f"total del dia {total} >= {limit} (60 % del presupuesto o la reserva de emergencia)"
            return False
        if mine >= DAY_MAX:
            self.reason = f"tope del dia {mine}/{DAY_MAX}"
            return False
        left_for_others = self.lane_reserve(day, spent - mine)
        if spent + left_for_others + LANE_MARGIN >= self.lane_ceiling:
            self.reason = (f"carril {LANE} {spent}/{self.lane_ceiling}" if not left_for_others
                           else f"carril {LANE} {spent}/{self.lane_ceiling}, con {left_for_others} para la ronda semanal de jugadores")
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
    first_night = night_start(at).date() if in_window(at) else at.astimezone(UTC).date()
    return {"left": len(wanted), "nights_at_cap": nights_needed(len(wanted)), "night_max": NIGHT_MAX, "day_max": DAY_MAX,
            "finish": finish_estimate(len(wanted), first_night), "closed_competitions": len(closed),
            "asked_in_total": sum(s.asked for s in states.values()), "competitions": rows}


REPORT_SQL = """
SELECT c.id, c.name, count(*) AS asked, count(*) FILTER (WHERE a.outcome = 'with_halves') AS with_halves,
       count(*) FILTER (WHERE a.outcome = 'without_halves') AS without_halves, count(*) FILTER (WHERE a.outcome = 'empty') AS empty,
       (SELECT count(*) FROM core.fixtures f2 JOIN core.competition_seasons s2 ON s2.id = f2.competition_season_id
         WHERE s2.competition_id = c.id AND f2.status_group = 'finished' AND f2.kickoff_at >= %(since)s) AS finished_since_2024
  FROM core.fixture_period_asks a
  JOIN core.fixtures f ON f.id = a.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 GROUP BY c.id, c.name ORDER BY asked DESC, c.id
"""
"""What came back by competition: the success of the fill, to publish in the availability matrix (PM-05-02's acceptance)."""


def by_competition(conn: Any, *, at: datetime) -> dict[str, Any]:
    """Asked, with both halves and the percentage of success by competition, and the share of the matches since 2024 already asked. No request."""
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REPORT_SQL, {"since": datetime(2024, 1, 1, tzinfo=UTC)})
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        asked, ok, total = int(r["asked"]), int(r["with_halves"]), int(r["finished_since_2024"])
        out.append({"competition_id": int(r["id"]), "name": str(r["name"]), "asked": asked, "with_halves": ok,
                    "without_halves": int(r["without_halves"]), "empty": int(r["empty"]),
                    "success_pct": round(100.0 * ok / asked, 1) if asked else None, "finished_since_2024": total,
                    "asked_pct_of_finished": round(100.0 * asked / total, 1) if total else None})
    asked_all = sum(int(r["asked"]) for r in out)
    ok_all = sum(int(r["with_halves"]) for r in out)
    return {"at": at.isoformat(), "asked": asked_all, "with_halves": ok_all,
            "success_pct": round(100.0 * ok_all / asked_all, 1) if asked_all else None, "competitions": out}


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
    stop_path = stop_file(settings.runtime.raw_store_dir)
    if STOP_REQUESTED or stop_path.exists():
        return {"stopped": f"orden de parada ({STOP_FILE})", "requests": 0}
    max_requests = args.max_requests
    if args.scheduled:
        # The night's cap holds whatever the number of starts: a restart of the worker, a second slot of the scheduler, a pass that
        # ended at its time. What this night asked already is in core.fixture_period_asks.
        done = ps.asked_since(conn, since=night_start(at), channel="backfill")
        max_requests = night_room(done, max_requests)
        if max_requests <= 0:
            return {"stopped": f"tope de la noche {done}/{NIGHT_MAX}", "requests": 0}
    until = stop_time(at) if args.scheduled else at + timedelta(minutes=args.max_minutes)
    until = min(until, at + timedelta(minutes=args.max_minutes))
    ceiling = next(lane.ceiling for lane in DEFAULT_LANES if lane.name == LANE)
    guard = Guard(conn, until=until, budget=settings.provider_plan.effective_budget, lane_ceiling=ceiling, scheduled=args.scheduled,
                  reserve=settings.provider_plan.emergency_reserve, stop_path=stop_path)
    states = ps.competition_state(conn)
    wanted = ps.targets(conn, since=ps.FILL_SINCE, until=at - ps.SETTLE, limit=max_requests + 500, newest_first=True,
                        skip=ps.closed_competitions(states))
    provider = ApiFootballProvider(_client(max_requests=max_requests))
    try:
        report = await ps.ask_targets(conn, provider, wanted, job_type=ps.FILL_JOB, channel="backfill", max_requests=max_requests,
                                      at=at, states=states, pace_seconds=PACE_SECONDS, keep_going=guard)
    finally:
        await provider.aclose()
    out = report.as_json()
    out["guard"] = guard.reason
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=("plan", "report", "from-raw", "run"))
    parser.add_argument("--max-requests", type=int, default=NIGHT_MAX)
    parser.add_argument("--max-minutes", type=int, default=300)
    parser.add_argument("--max-memory-mib", type=int, default=DEFAULT_CAP_MIB)
    parser.add_argument("--scheduled", action="store_true", help="started by the worker's scheduler: only inside 22:30-03:25 UTC")
    args = parser.parse_args(argv)
    cap_memory(args.max_memory_mib)
    signal.signal(signal.SIGTERM, request_stop)  # the stop order by signal: the request in flight ends, the ledger row is written

    import psycopg
    from psycopg.types.json import Json

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.ingestion import period_stats as ps

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name=ps.FILL_JOB) as conn:
        # Its own session limit (the availability matrix's process has the same): no read of this process may hold the database.
        conn.execute(f"SET statement_timeout = '{PLAN_STATEMENT_TIMEOUT if args.mode in ('plan', 'report') else STATEMENT_TIMEOUT}'")
        conn.commit()
        if args.mode == "plan":
            print(json.dumps(plan(conn, at=now()), indent=1, default=str))
            return 0
        if args.mode == "report":
            print(json.dumps(by_competition(conn, at=now()), indent=1, default=str))
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
