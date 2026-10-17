"""PrediGol Intelligence's jobs and their record (``intel.runs``): what ran, when, how long, what it did, what failed.

    intel_decide   every 15 minutes (the first at 00:10 Bogotá, after the AI opens the day at 00:05): the decision
                   layer over the next 36 hours (``fbi.intel.decision.decide``); once the AI has read the day (its
                   first passes done, or 06:00 Bogotá), the PICKS DEL DÍA of daily-set-v6 and its parlays
    intel_nightly  07:50 Bogotá, after the AI's own learning (07:35): outcomes and closing-line value of the
                   decisions, post-mortems pm-v3, the longitudinal memory of yesterday (and the day before, whose late
                   matches may have settled), calibration (prospective evaluation, refits, promotions by the gates),
                   the leakage audit of yesterday's decisions, the DAILY LEARNING REPORT, and the hypotheses the
                   calibration experiment answers
    intel_weekly   Monday 04:40 Bogotá: the market discovery engine

One run of each kind at a time (advisory locks); a run that dies is closed as ``interrupted`` by the next worker
(``recover_interrupted``). Every step commits on its own, so a failure part-way keeps what was done and is written in
the run's ``errors``. Zero API-Football requests and zero language-model calls: everything here reads the database.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
import structlog
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.core.version import code_version

log = structlog.get_logger(__name__)

LOCKS = {"decide": 7310076, "nightly": 7310077, "weekly": 7310078, "calibrate": 7310077, "select": 7310076,
         "backfill": 7310079, "manual": 7310079}


@dataclass
class RunReport:
    run_id: int | None = None
    status: str = "ok"
    counts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def versions() -> dict[str, str]:
    from fbi.intel import (
        calibration,
        decision,
        discovery,
        leakage,
        memory,
        outcomes,
        postmortem,
        report,
        score,
        stake,
    )

    return {"decision": decision.VERSION, "score": score.VERSION, "stake": stake.VERSION,
            "calibration": calibration.VERSION, "calib_gate": calibration.GATE_VERSION,
            "edge_gate": calibration.EDGE_GATE_VERSION, "outcome": outcomes.VERSION, "postmortem": postmortem.VERSION,
            "memory": memory.VERSION, "report": report.VERSION, "discovery": discovery.VERSION,
            "leakage": leakage.VERSION, "selection": decision.RULE_V6}


def open_run(conn: psycopg.Connection[Any], job: str, *, at: datetime) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO intel.runs (job, started_at, status, code_version, versions) "
                    "VALUES (%s, %s, 'running', %s, %s) RETURNING id", (job, at, code_version(), Jsonb(versions())))
        row = cur.fetchone()
    conn.commit()
    assert row is not None
    return int(row[0])


def close_run(conn: psycopg.Connection[Any], run_id: int, report: RunReport, *, started: float) -> None:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("UPDATE intel.runs SET finished_at = clock_timestamp(), status = %s, duration_ms = %s, counts = %s, "
                    "errors = %s WHERE id = %s",
                    (report.status, int((time.monotonic() - started) * 1000), Jsonb(_jsonable(report.counts)),
                     Jsonb(report.errors[-20:]), run_id))
    conn.commit()


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (int, float, str, bool)) or x is None:
        return x
    return str(x)


def recover_interrupted(conn: psycopg.Connection[Any], *, before: datetime) -> int:
    """Close the runs a previous worker left open (it died with them)."""
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE intel.runs SET status = 'interrupted', finished_at = clock_timestamp(), "
                        "errors = errors || '[\"the worker stopped during the run\"]'::jsonb "
                        "WHERE status = 'running' AND started_at < %s", (before,))
            n = max(cur.rowcount, 0)
        conn.commit()
        return n
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return 0


def _locked(conn: psycopg.Connection[Any], job: str) -> bool:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCKS[job],))
        row = cur.fetchone()
    conn.commit()
    return bool(row and row[0])


def _unlock(conn: psycopg.Connection[Any], job: str) -> None:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (LOCKS[job],))
    conn.commit()


def _run(conn: psycopg.Connection[Any], job: str, at: datetime, steps: list[tuple[str, Callable[[], Any]]]) -> RunReport:
    report = RunReport()
    if not _locked(conn, job):
        report.status = "skipped"
        report.counts["busy"] = 1
        return report
    started = time.monotonic()
    try:
        report.run_id = open_run(conn, job, at=at)
        for name, fn in steps:
            t0 = time.monotonic()
            try:
                result = fn()
                conn.commit()
                report.counts[name] = result
            except Exception as exc:  # a step's failure is recorded; the others still run
                conn.rollback()
                report.status = "partial"
                report.errors.append(f"{name}: {type(exc).__name__}: {exc}"[:400])
                log.error("intel.step_failed", job=job, step=name, error=f"{type(exc).__name__}: {exc}"[:300])
            report.counts[f"{name}_ms"] = int((time.monotonic() - t0) * 1000)
        if report.errors and len(report.errors) == len(steps):
            report.status = "failed"
        close_run(conn, report.run_id, report, started=started)
    finally:
        _unlock(conn, job)
    return report


def run_decide(conn: psycopg.Connection[Any], *, at: datetime) -> RunReport:
    from fbi.intel.decision import decide, select_day
    from fbi.picks.daily import day_ready

    def _decide() -> dict[str, Any]:
        r, _ = decide(conn, at=at)
        return {"candidates": r.candidates, "evaluated": r.evaluated, "written": r.written, "by_state": r.by_state,
                "by_context": r.by_context}

    def _select() -> dict[str, int]:
        try:
            ready = day_ready(conn, at=at)
        except psycopg.Error:
            conn.rollback()
            ready = False
        picks, parlays = select_day(conn, at=at, ready=ready)
        return {"ready": int(ready), "picks": picks, "parlays": parlays}

    return _run(conn, "decide", at, [("decide", _decide), ("select", _select)])


def run_nightly(conn: psycopg.Connection[Any], *, at: datetime) -> RunReport:
    from fbi.intel.calibration import run_calibration
    from fbi.intel.leakage import audit_day
    from fbi.intel.memory import build_memory
    from fbi.intel.outcomes import settle_decisions
    from fbi.intel.postmortem import run_postmortems
    from fbi.intel.report import days_to_report, write_report

    today = local_day(at)
    calib: dict[str, Any] = {}

    def _calibration() -> dict[str, Any]:
        r = run_calibration(conn, at=at)
        calib.update({"fitted": r.fitted, "promoted": r.promoted, "retired": r.retired,
                      "edge_changes": r.edge_changes, "evaluations": r.evaluations, "summary": r.summary})
        return {k: v for k, v in calib.items() if k != "summary"}

    def _memory() -> dict[str, int]:
        return {d.isoformat(): build_memory(conn, day=d, at=at) for d in (today - timedelta(days=2),
                                                                          today - timedelta(days=1))}

    def _audit() -> dict[str, Any]:
        out = audit_day(conn, day=today - timedelta(days=1), at=at)
        return {k: v["violations"] for k, v in out.items()} | {"checked": sum(v["checked"] for v in out.values())}

    def _report() -> dict[str, Any]:
        return {d.isoformat(): write_report(conn, day=d, at=at) for d in days_to_report(at)}

    def _hypotheses() -> int:
        return link_hypotheses(conn, at=at, calibration=calib)

    return _run(conn, "nightly", at, [
        ("outcomes", lambda: settle_decisions(conn, at=at)),
        ("postmortems", lambda: run_postmortems(conn, at=at)),
        ("memory", _memory),
        ("calibration", _calibration),
        ("leakage_audit", _audit),
        ("hypotheses", _hypotheses),
        ("report", _report),
    ])


def run_weekly(conn: psycopg.Connection[Any], *, at: datetime) -> RunReport:
    from fbi.intel.discovery import run_discovery

    holder: dict[str, int] = {}

    def _discovery() -> dict[str, Any]:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT id FROM intel.runs WHERE job = 'weekly' AND status = 'running' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        holder["run"] = int(row[0]) if row else 0
        return run_discovery(conn, at=at, run_id=holder["run"])

    return _run(conn, "weekly", at, [("discovery", _discovery)])


# ── the hypotheses the calibration experiment answers ────────────────────────────────────────────────────────────

HYPOTHESIS_PATTERN = r"(sobreconfi|sobreestim|inflad|calibr|contraer p_model|por detr[aá]s del cierre|overconfid)"


def link_hypotheses(conn: psycopg.Connection[Any], *, at: datetime, calibration: dict[str, Any]) -> int:
    """The hypotheses about the model's overconfidence get the calibration experiment's evidence: an ACCEPTED or
    RUNNING one moves to SHADOW (the calibrators are measured prospectively) with the walk-forward outcome; a PROPOSED
    or INVESTIGATING one keeps its status (the owner decides) and gets the evidence appended to its history. Once per
    day per hypothesis."""
    from fbi.research.evolution import DecisionError, advance

    summary = calibration.get("summary") or {}
    if not summary:
        return 0
    evidence = {k: v.get("fits") for k, v in summary.items() if v.get("fits")}
    if not evidence:
        return 0
    outcome = {"experiment": "cal-logit2-v1 walk-forward", "at": at.isoformat(), "by_market_model": evidence,
               "gate_passed": False, "note": "calibration corrects the overconfidence; no market has validated edge"}
    n = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id, status, stage_history FROM analytics.research_hypotheses "
                    "WHERE (title ~* %(p)s OR hypothesis ~* %(p)s) AND status IN ('PROPOSED', 'INVESTIGATING', "
                    "'ACCEPTED', 'RUNNING', 'SHADOW')", {"p": HYPOTHESIS_PATTERN})
        rows = cur.fetchall()
    day = local_day(at).isoformat()
    for hid, status, history in rows:
        if any((h or {}).get("experiment") == "cal-logit2-v1" and str((h or {}).get("at", ""))[:10] == day
               for h in (history or [])):
            continue
        note = ("Experimento de calibración por mercado (cal-logit2-v1, walk-forward diario): ver outcome. "
                "La sobreconfianza se corrige; ningún mercado muestra edge validado contra el cierre.")
        if status in ("ACCEPTED", "RUNNING"):
            try:
                advance(conn, int(hid), stage="SHADOW", at=at, outcome=outcome, note=note)
                n += 1
                continue
            except DecisionError:
                conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE analytics.research_hypotheses SET stage_history = stage_history || "
                        "jsonb_build_array(jsonb_build_object('at', %s::timestamptz, 'by', 'system', "
                        "'experiment', 'cal-logit2-v1', 'note', %s::text, 'evidence', %s::jsonb)) WHERE id = %s",
                        (at, note, Jsonb(evidence), int(hid)))
            n += max(cur.rowcount, 0)
    return n
