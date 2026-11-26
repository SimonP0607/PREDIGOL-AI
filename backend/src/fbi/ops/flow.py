"""The state of the stages of «El camino de un pick», computed in the server (plan RP-1.2, finding H29): ``flow-v1``.

The panel drew each stage from ``GET /admin/ops/jobs`` in the browser and got three things wrong: it painted a stage red for a job whose last
run was ``aborted`` while its counter said «0 con error» (the counter summed ``failed`` only), it showed Valor and Calibración «Sin datos»
because 46 jobs never wrote a row (RP-1.1 gave them one) and it read Aprendizaje from a report that was ``not_configured``. This module is the
ONE computation, over the book of runs (``raw.ingestion_runs``) and the worker's heartbeat, and the console (C-11, ``flow.panel``) carries it:

* the stage's state is the worst state of its jobs, with the reason in code that put it there;
* **the single rule:** the visible error counter is ``failed + aborted + interrupted + stale``, every status that can put a stage in error, so
  the counter and the colour never disagree;
* a job type the map does not know is counted apart (``unmapped``), never hidden;
* it reads and writes nothing else, and decides nothing.

The grouping of the job types is the owner's reading of the ledger, the same eleven stages as ``web/src/live/flowStages.ts``; a test keeps the
two maps from drifting, and the three stages the plan re-associates (Calibración with the calibrators' night, Aprendizaje with the learning and
the research jobs, none with the AI's report) are written here, in one place, with the difference to the web's map spelled out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.ops.job_book import job_type_of

VERSION: Final = "flow-v1"

Stage = Literal["sources", "ingest", "validation", "models", "calibration", "value", "intelligence", "selection", "publication",
                "settlement", "learning"]
STAGES: Final[tuple[Stage, ...]] = ("sources", "ingest", "validation", "models", "calibration", "value", "intelligence", "selection",
                                    "publication", "settlement", "learning")
State = Literal["ok", "late", "error", "none", "closed"]

STAGE_JOBS: Final[Mapping[Stage, tuple[str, ...]]] = {
    "sources": ("fixtures_sync", "results_sync", "odds_capture", "live_odds_capture", "live_match_capture", "reference_refresh",
                "catalogue_refresh", "post_match_detail", "historical_backfill", "signals_ingest"),
    "ingest": ("odds_quotes_extract", "odds_book_build", "odds_book_refresh", "stats_documents", "player_history", "referee_identity",
               "competition_structure", "availability_refresh", "availability_shadow", "period_stats", "period_backfill", "lineup_watch",
               "context_refresh", "context_due", "results_repair", "final_prematch"),
    "validation": ("quality_sweep", "historical_validation", "synthetic_journey"),
    "models": ("feature_build", "elo_refresh", "family_forecasts", "match_knowledge", "player_forecast_shadow", "lineup_estimate_shadow",
               "scenarios_shadow"),
    "calibration": ("eval_cycle_shadow", "eval_cycle_e3", "intel_nightly"),
    "value": ("decision_v2_shadow", "parlay_v6_shadow"),
    "intelligence": ("research_monitor", "research_v2", "news_stories", "council_reduced_shadow", "source_credibility_shadow",
                     "chronicle_v4", "chronicle_update", "chronicle_review", "chronicle_review_v2", "user_narrative", "lifecycle_shadow"),
    "selection": ("pick_pipeline", "selection_eval_shadow"),
    "publication": (),
    "settlement": ("pick_settlement", "selection_settle_shadow"),
    "learning": ("ai_learn", "intel_weekly", "research_v2_weekly", "stall_check"),
}
"""The web's map (``flowStages.ts``) with exactly two differences, both asked by RP-1.2: Calibración also holds ``intel_nightly`` (the night
that calibrates and evaluates the calibrators) and Aprendizaje holds the four jobs that learn and watch the cycle (it had none, and read the AI's
report instead). ``PLAN_ADDITIONS`` names them so the test of the two maps can say what the difference must be."""
PLAN_ADDITIONS: Final[Mapping[Stage, tuple[str, ...]]] = {"calibration": ("intel_nightly",),
                                                          "learning": ("ai_learn", "intel_weekly", "research_v2_weekly", "stall_check")}

LATE_MINUTES: Final = 15
ERROR_MINUTES: Final = 60
BAD_STATUSES: Final = ("failed", "aborted", "interrupted", "stale")
"""Every status that puts a job, and so its stage, in error: the counter sums all of them."""
WINDOW: Final = timedelta(hours=24)
LOOK_BACK: Final = timedelta(days=30)

REASONS: Final = ("al_dia", "ultima_fallida", "ultima_abortada", "ultima_interrumpida", "ultima_obsoleta", "atrasada_mas_de_60_min",
                  "atrasada_mas_de_15_min", "fallos_en_24h", "parciales_en_24h", "sin_ejecuciones_registradas", "cerrada_por_decision")
_RANK: Final[Mapping[str, int]] = {"none": 0, "closed": 0, "ok": 1, "late": 2, "error": 3}

JOBS_SQL: Final = """
SELECT job_type,
       count(*) FILTER (WHERE started_at > %(lo)s) AS runs,
       count(*) FILTER (WHERE started_at > %(lo)s AND status = 'completed') AS completed,
       count(*) FILTER (WHERE started_at > %(lo)s AND status = 'partial') AS partial,
       count(*) FILTER (WHERE started_at > %(lo)s AND status = 'failed') AS failed,
       count(*) FILTER (WHERE started_at > %(lo)s AND status = 'aborted') AS aborted,
       count(*) FILTER (WHERE started_at > %(lo)s AND status = 'interrupted') AS interrupted,
       count(*) FILTER (WHERE started_at > %(lo)s AND status = 'stale') AS stale,
       (array_agg(status ORDER BY started_at DESC, id DESC))[1] AS last_status,
       max(started_at) AS last_started_at
  FROM raw.ingestion_runs
 WHERE job_type <> 'unspecified' AND started_at > %(back)s AND started_at <= %(at)s
 GROUP BY job_type
"""
"""Read only: one grouped pass over the book. A run that began after the moment asked is not read (the console asks for «now»)."""
HEARTBEAT_SQL: Final = "SELECT jobs FROM raw.worker_heartbeats ORDER BY last_beat_at DESC LIMIT 1"


@dataclass(frozen=True, slots=True)
class JobRow:
    job_type: str
    runs: int = 0
    completed: int = 0
    partial: int = 0
    failed: int = 0
    aborted: int = 0
    interrupted: int = 0
    stale: int = 0
    last_status: str | None = None
    last_started_at: datetime | None = None
    next_run_at: datetime | None = None

    @property
    def errors(self) -> int:
        return self.failed + self.aborted + self.interrupted + self.stale


@dataclass(frozen=True, slots=True)
class StageFlow:
    stage: Stage
    state: State
    reason: str
    last_run_at: datetime | None
    jobs: int
    runs: int
    completed: int
    partial: int
    failed: int
    aborted: int
    interrupted: int
    stale: int
    worst_job: str | None

    @property
    def errors(self) -> int:
        """The visible counter: every status that can put the stage in error (the single rule)."""
        return self.failed + self.aborted + self.interrupted + self.stale


def job_state(job: JobRow, at: datetime) -> tuple[State, str]:
    """The state of one job and the reason that decides it. Error: its last run did not end well, or it is long overdue; late: it failed or was
    partial in the day, or is a little overdue; otherwise ok. The order is the web's, so the colours do not change."""
    if job.last_status in BAD_STATUSES:
        return "error", {"failed": "ultima_fallida", "aborted": "ultima_abortada", "interrupted": "ultima_interrumpida",
                         "stale": "ultima_obsoleta"}[str(job.last_status)]
    if job.next_run_at is not None:
        overdue = (at - job.next_run_at).total_seconds() / 60
        if overdue > ERROR_MINUTES:
            return "error", "atrasada_mas_de_60_min"
        if overdue > LATE_MINUTES:
            return "late", "atrasada_mas_de_15_min"
    if job.failed > 0:
        return "late", "fallos_en_24h"
    if job.partial > 0:
        return "late", "parciales_en_24h"
    return "ok", "al_dia"


def stage_flow(stage: Stage, jobs: Sequence[JobRow], at: datetime) -> StageFlow:
    """One stage from the rows of the job types the ledger has seen for it. Publicación is closed by the owner's decision, whatever the ledger says."""
    if stage == "publication":
        return StageFlow(stage, "closed", "cerrada_por_decision", None, 0, 0, 0, 0, 0, 0, 0, 0, None)
    state: State = "none"
    reason, worst = "sin_ejecuciones_registradas", None
    for j in jobs:
        s, why = job_state(j, at)
        if _RANK[s] > _RANK[state]:
            state, reason, worst = s, why, (None if s == "ok" else j.job_type)
    started = [j.last_started_at for j in jobs if j.last_started_at is not None]
    return StageFlow(stage, state, reason, max(started) if started else None, len(jobs), sum(j.runs for j in jobs),
                     sum(j.completed for j in jobs), sum(j.partial for j in jobs), sum(j.failed for j in jobs), sum(j.aborted for j in jobs),
                     sum(j.interrupted for j in jobs), sum(j.stale for j in jobs), worst)


def flows(rows: Sequence[JobRow], at: datetime) -> tuple[list[StageFlow], list[str]]:
    """The eleven stages in order and the job types of the book that no stage claims (counted apart, never hidden)."""
    by_type = {r.job_type: r for r in rows}
    known = {t for types in STAGE_JOBS.values() for t in types}
    out = [stage_flow(s, [by_type[t] for t in STAGE_JOBS[s] if t in by_type], at) for s in STAGES]
    return out, sorted(t for t in by_type if t not in known and by_type[t].runs > 0)


def _next_runs(jobs: Mapping[str, str] | None) -> dict[str, datetime]:
    """The heartbeat's scheduler ids -> the job type's next run (the earliest of its ids: a sweep and a retry write under their type)."""
    found: dict[str, datetime] = {}
    for job_id, when in (jobs or {}).items():
        try:
            at = datetime.fromisoformat(str(when))
        except ValueError:
            continue
        t = job_type_of(job_id)
        if t not in found or at < found[t]:
            found[t] = at
    return found


def read_rows(conn: psycopg.Connection[Any], *, at: datetime) -> list[JobRow]:
    """The book of the last 30 days, grouped by job type, with the next run of the worker's last heartbeat. Read only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(JOBS_SQL, {"lo": at - WINDOW, "back": at - LOOK_BACK, "at": at})
        rows = cur.fetchall()
        cur.execute(HEARTBEAT_SQL)
        beat = cur.fetchone()
    upcoming = _next_runs((beat or {}).get("jobs") if isinstance((beat or {}).get("jobs"), dict) else None)
    return [JobRow(job_type=str(r["job_type"]), runs=int(r["runs"]), completed=int(r["completed"]), partial=int(r["partial"]),
                   failed=int(r["failed"]), aborted=int(r["aborted"]), interrupted=int(r["interrupted"]), stale=int(r["stale"]),
                   last_status=r["last_status"], last_started_at=r["last_started_at"], next_run_at=upcoming.get(str(r["job_type"])))
            for r in rows]


def read(conn: psycopg.Connection[Any], *, at: datetime) -> tuple[list[StageFlow], list[str]]:
    return flows(read_rows(conn, at=at), at)


__all__ = ["BAD_STATUSES", "ERROR_MINUTES", "LATE_MINUTES", "PLAN_ADDITIONS", "REASONS", "STAGES", "STAGE_JOBS", "VERSION", "JobRow",
           "StageFlow", "flows", "job_state", "read", "read_rows", "stage_flow"]
