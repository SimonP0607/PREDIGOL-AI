"""The sheet of resources of a wave: does the plan still fit the machine and the budget? (plan RP-13.3, finding H30): ``resource-sheet-v1``.

The worker sat at 2.77 of its 3 GB, 117 runs ended ``aborted`` and 65 ``interrupted`` in a week, and the AI had spent 142.89 of its 185 USD in the
month. Every piece the plan deploys can make one of those worse. This sheet measures four things over a window of days, read from the book of
runs (``raw.ingestion_runs``: its memory per run, its status, its calls to the data provider) and the AI ledger (``ai.usage``):

    memory ...... the highest resident memory a run reached (MiB), the process's high-water mark, and the jobs that reached the most
    aborted ..... the runs that did not end well (failed, aborted, interrupted, stale) per day
    requests .... the calls to the data provider per day: the busiest day and the mean
    spend ....... the AI's spend in the window and in the month, against its cap

``judge`` compares the window BEFORE a deploy with the window AFTER it and says which rule of section 20 of the plan the deployed piece breaks:
more than 3,000 provider requests a day over the day it was before, a spend that reached the cap, a worker that now sits near its limit or
a peak that rose by a visible step, or more runs aborted a day. The plan asks for the alarm and for the piece to be switched off: this module
raises the alarm in code and leaves the switching to the audited kit and to the owner. It reads; it changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "resource-sheet-v1"

WORKER_LIMIT_MIB: Final = 3072
"""The worker's memory limit in the deployed stack (3 GB)."""
NEAR_LIMIT_SHARE: Final = 0.9
"""This code's own choice (written here, not in the plan): from 90 % of the limit the worker is «near» it."""
PEAK_STEP_MIB: Final = 128
"""This code's own choice: a peak that rises by this much between the two windows is new resident load worth an alarm."""
EXTRA_REQUESTS_PER_DAY: Final = 3000
"""Section 20 of the plan: more than 3,000 provider requests a day over what it was before."""
BAD_STATUSES: Final = ("failed", "aborted", "interrupted", "stale")

ALARMS: Final = ("peticiones_adicionales", "tope_de_gasto", "memoria_cerca_del_limite", "memoria_sube", "abortadas_empeoran")

RUNS_SQL: Final = """
SELECT CASE WHEN job_type = 'unspecified' THEN job_name ELSE job_type END AS job,
       status, started_at::date AS day, api_calls,
       NULLIF(params->'_mem'->>'rss_max_mib', '')::float8 AS rss_max_mib,
       NULLIF(params->'_mem'->>'hwm_mib', '')::float8 AS hwm_mib
  FROM raw.ingestion_runs
 WHERE started_at >= %(since)s AND started_at < %(until)s
"""
SPEND_SQL: Final = "SELECT coalesce(sum(cost_usd), 0) AS spent FROM ai.usage WHERE at >= %(since)s AND at < %(until)s"


@dataclass(frozen=True, slots=True)
class Sheet:
    """One window, measured."""

    since: datetime
    until: datetime
    days: int
    runs: int = 0
    runs_with_memory: int = 0
    peak_mib: float | None = None
    hwm_mib: float | None = None
    top_jobs: tuple[tuple[str, float], ...] = ()
    bad_runs: int = 0
    bad_by_status: dict[str, int] = field(default_factory=dict)
    api_calls: int = 0
    busiest_day_calls: int = 0
    spend_usd: Decimal = Decimal(0)
    month_spend_usd: Decimal | None = None

    @property
    def bad_per_day(self) -> float:
        return round(self.bad_runs / self.days, 2) if self.days else 0.0

    @property
    def calls_per_day(self) -> float:
        return round(self.api_calls / self.days, 1) if self.days else 0.0


@dataclass(frozen=True, slots=True)
class Alarm:
    code: str
    detail: str


def sheet_of(rows: list[dict[str, Any]], *, since: datetime, until: datetime, spend: Decimal = Decimal(0),
             month_spend: Decimal | None = None, top: int = 5) -> Sheet:
    """The sheet from the rows of the book of runs in the window. Pure."""
    days = max(1, round((until - since).total_seconds() / 86400))
    peaks: dict[str, float] = {}
    hwm: float | None = None
    with_memory = 0
    bad: dict[str, int] = {}
    per_day: dict[Any, int] = {}
    calls = 0
    for r in rows:
        n = int(r["api_calls"] or 0)
        calls += n
        per_day[r["day"]] = per_day.get(r["day"], 0) + n
        if r["status"] in BAD_STATUSES:
            bad[str(r["status"])] = bad.get(str(r["status"]), 0) + 1
        if r["rss_max_mib"] is not None:
            with_memory += 1
            job = str(r["job"])
            peaks[job] = max(peaks.get(job, 0.0), float(r["rss_max_mib"]))
        if r["hwm_mib"] is not None:
            hwm = float(r["hwm_mib"]) if hwm is None else max(hwm, float(r["hwm_mib"]))
    ranked = tuple(sorted(peaks.items(), key=lambda kv: (-kv[1], kv[0]))[:top])
    return Sheet(since, until, days, len(rows), with_memory, ranked[0][1] if ranked else None, hwm, ranked, sum(bad.values()), bad, calls,
                 max(per_day.values(), default=0), spend, month_spend)


def read(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, month_since: datetime | None = None) -> Sheet:
    """One window from the database. Read only: two SELECTs."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RUNS_SQL, {"since": since, "until": until})
        rows = cur.fetchall()
        cur.execute(SPEND_SQL, {"since": since, "until": until})
        spent = Decimal(str((cur.fetchone() or {}).get("spent", 0)))
        month = None
        if month_since is not None:
            cur.execute(SPEND_SQL, {"since": month_since, "until": until})
            month = Decimal(str((cur.fetchone() or {}).get("spent", 0)))
    return sheet_of(rows, since=since, until=until, spend=spent, month_spend=month)


def judge(before: Sheet, after: Sheet, *, cap_usd: Decimal) -> list[Alarm]:
    """The rules of section 20 between the window before a deploy and the window after it. Pure."""
    out: list[Alarm] = []
    extra = after.busiest_day_calls - before.busiest_day_calls
    if extra > EXTRA_REQUESTS_PER_DAY:
        out.append(Alarm("peticiones_adicionales", f"el día de más carga pasó de {before.busiest_day_calls} a {after.busiest_day_calls} peticiones "
                                                    f"(+{extra}; el límite del plan es +{EXTRA_REQUESTS_PER_DAY})"))
    month = after.month_spend_usd if after.month_spend_usd is not None else after.spend_usd
    if month >= cap_usd:
        out.append(Alarm("tope_de_gasto", f"el gasto de IA del mes ({month} USD) alcanzó el tope ({cap_usd} USD)"))
    if after.peak_mib is not None and after.peak_mib >= NEAR_LIMIT_SHARE * WORKER_LIMIT_MIB:
        out.append(Alarm("memoria_cerca_del_limite", f"el pico del trabajador fue {after.peak_mib:.0f} MiB de {WORKER_LIMIT_MIB} "
                                                      f"(desde el {NEAR_LIMIT_SHARE:.0%} se considera cerca)"))
    if after.peak_mib is not None and before.peak_mib is not None and after.peak_mib - before.peak_mib >= PEAK_STEP_MIB:
        out.append(Alarm("memoria_sube", f"el pico subió de {before.peak_mib:.0f} a {after.peak_mib:.0f} MiB (escalón de {PEAK_STEP_MIB} MiB)"))
    if after.bad_per_day > before.bad_per_day and after.bad_runs > 0:
        out.append(Alarm("abortadas_empeoran", f"las ejecuciones sin buen fin por día pasaron de {before.bad_per_day} a {after.bad_per_day}"))
    return out


def as_dict(s: Sheet) -> dict[str, Any]:
    return {"since": s.since.isoformat(), "until": s.until.isoformat(), "days": s.days, "runs": s.runs,
            "memory": {"runs_with_memory": s.runs_with_memory, "peak_mib": s.peak_mib, "hwm_mib": s.hwm_mib, "limit_mib": WORKER_LIMIT_MIB,
                       "top_jobs": [{"job": j, "peak_mib": p} for j, p in s.top_jobs]},
            "bad_runs": {"total": s.bad_runs, "per_day": s.bad_per_day, "by_status": dict(s.bad_by_status)},
            "provider_requests": {"total": s.api_calls, "per_day": s.calls_per_day, "busiest_day": s.busiest_day_calls},
            "ai_spend_usd": {"window": str(s.spend_usd), "month": None if s.month_spend_usd is None else str(s.month_spend_usd)}}


def window(moment: datetime, days: int) -> tuple[datetime, datetime, datetime, datetime]:
    """The two windows around a deploy: ``days`` before ``moment`` and ``days`` after it."""
    d = timedelta(days=days)
    return moment - d, moment, moment, moment + d


__all__ = ["ALARMS", "EXTRA_REQUESTS_PER_DAY", "NEAR_LIMIT_SHARE", "PEAK_STEP_MIB", "VERSION", "WORKER_LIMIT_MIB", "Alarm", "Sheet", "as_dict",
           "judge", "read", "sheet_of", "window"]
