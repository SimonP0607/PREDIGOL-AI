"""The chronicle's update after the official line-up, and the why of each selection, IN SHADOW (IA-116, plan piece AD-F03). Born OFF.

SWITCH ``FBI_CHRONICLE_LINEUP``: ``off`` (default, and any other word) - nothing is read or written; ``shadow`` - every two minutes
(``EVERY_MINUTES``) the worker takes each E3 of the evaluation cycle (``intel.eval_runs``, IA-106) of a match that has a chronicle in
``ai.chronicles`` and writes ONE new version of that chronicle: its verified sections as they were, the paragraph of the line-up
(``lineup-update-v1``) and the why of every selection E3 judged (``selection-why-v1``), by template (``fbi.chronicle.update``). No model, no
provider, no cost: E3's window has no model in it, and this pass has none at all.

WHAT IS WRITTEN: one row of ``ai.chronicles`` per E3 (``custom_id = 'lineup-update:<E3 run>'``, unique: never twice), ``route = 'none'``, cost
0, the base chronicle's plan and versions, its content plus ``actualizacion`` and ``selecciones``. The earlier version is never touched
(append-only): turned off, the earlier chronicle is simply the newest that is not an update. Nothing of PrediGol Intelligence is written; no
reader sees it (``FBI_MATCH_INTELLIGENCE`` is off and C-01's second delivery is another piece)."""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.chronicle import plan as cp
from fbi.chronicle import update as up
from fbi.chronicle.v4_job import INSERT_SQL

log = structlog.get_logger(__name__)

JOB: Final = "chronicle_update"
SWITCH: Final = "FBI_CHRONICLE_LINEUP"
EVERY_MINUTES: Final = 2
CUSTOM_PREFIX: Final = "lineup-update:"
WINDOW: Final = timedelta(hours=3)
"""E3 runs of the matches kicking off within three hours either side of now (``eval_runs_kickoff``)."""
LIMIT: Final = 50
NOTES_LIMIT: Final = 1000

Mode = Literal["off", "shadow"]


def mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = (os.environ if env is None else env).get(SWITCH, "")
    return "shadow" if raw.strip().lower() == "shadow" else "off"


DUE_SQL: Final = """
SELECT r.id, r.fixture_id, r.cause_key, r.trigger_at, r.known_at, r.lineup
  FROM intel.eval_runs r
 WHERE r.kickoff_at > %(start)s AND r.kickoff_at <= %(end)s AND r.evaluation = 'E3' AND r.status <> 'fallida' AND r.known_at <= %(at)s
   AND EXISTS (SELECT 1 FROM ai.chronicles c WHERE c.fixture_id = r.fixture_id AND c.created_at <= %(at)s)
   AND NOT EXISTS (SELECT 1 FROM ai.chronicles c WHERE c.custom_id = %(prefix)s || r.id::text)
 ORDER BY r.known_at, r.id
 LIMIT %(limit)s
"""
"""Every E3 of the window not yet told, of a match with a chronicle (``ai_chronicles_custom_id``, ``ai_chronicles_fixture``)."""
BASE_SQL: Final = """
SELECT id, status, plan, content, version, plan_version, classes_version, verify_version, figure_version, packet_id, plan_hash, plan_at
  FROM ai.chronicles
 WHERE fixture_id = %(f)s AND created_at <= %(at)s AND (custom_id IS NULL OR custom_id NOT LIKE 'lineup-update:%%')
 ORDER BY id DESC LIMIT 1
"""
"""The newest chronicle of the match that is not itself an update: the version the update is added to."""
PLAYERS_SQL: Final = """
SELECT team_side, provider_player_id, player_name, is_starter FROM core.fixture_lineup_players
 WHERE fixture_id = %(f)s AND source = 'api-football' AND provider_player_id > 0
"""
VERDICTS_SQL: Final = """
SELECT id, market_key, selection, line::float8 AS line, state, reason, verdict, decision_id
  FROM intel.eval_verdicts WHERE fixture_id = %(f)s AND run_id = %(run)s ORDER BY id
"""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def lineup_of(run: Mapping[str, Any], players: list[dict[str, Any]]) -> up.LineUp:
    found = run.get("lineup")
    doc: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    sides = tuple(sorted(s for s in (doc.get("sides") or []) if s in ("home", "away")))
    people = tuple(up.Player(str(p["team_side"]), int(p["provider_player_id"]), str(p.get("player_name") or ""), bool(p["is_starter"]))
                   for p in players if p["team_side"] in sides)
    return up.LineUp(int(run["id"]), str(run["cause_key"]), run["trigger_at"], run["known_at"], people, sides)


@dataclass
class RunReport:
    mode: str
    counts: Counter[str] = field(default_factory=Counter)
    written: list[int] = field(default_factory=list)
    latency_ms: list[int] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        lat = sorted(self.latency_ms)
        return {"version": up.VERSION, "mode": self.mode, "counts": dict(sorted(self.counts.items())), "written": len(self.written),
                "latency_ms_max": lat[-1] if lat else None}


def one(conn: psycopg.Connection[Any], run: Mapping[str, Any], *, at: datetime, code_version: str | None = None) -> int | None:
    """The new version of the chronicle of one E3, or None when it was already written."""
    fixture = int(run["fixture_id"])
    found = _rows(conn, BASE_SQL, {"f": fixture, "at": at})
    if not found:
        return None
    base = found[0]
    plan = cp.from_json(base["plan"])
    lineup = lineup_of(run, _rows(conn, PLAYERS_SQL, {"f": fixture}))
    chronicle = base["content"] if base["status"] in ("ok", "partial") and isinstance(base["content"], Mapping) else None
    update = up.paragraph(plan, lineup, chronicle, chronicle_id=int(base["id"]))
    selections = [up.Selection(int(r["id"]), str(r["market_key"]), str(r["selection"]), float(r["line"]), str(r["state"]),
                               str(r["reason"]), str(r["verdict"]), None if r["decision_id"] is None else int(r["decision_id"]))
                  for r in _rows(conn, VERDICTS_SQL, {"f": fixture, "run": int(run["id"])})]
    whys = [up.why(s, plan, chronicle, update, chronicle_id=int(base["id"]), at=at) for s in selections]
    orphans = up.without_origin(whys)
    if orphans:  # never written: a phrase without its origin is the one thing this piece may not say
        raise ValueError(f"{len(orphans)} phrases without an origin")
    content = up.content_of(chronicle, update, whys)
    status = str(base["status"]) if base["status"] in ("ok", "partial") else "ok"
    latency = None if run["trigger_at"] is None else max(0, int((at - run["trigger_at"]).total_seconds() * 1000))
    metrics = {"version": up.VERSION, "why_version": up.WHY_VERSION, "kind": "lineup_update", "base_chronicle_id": int(base["id"]),
               "base_status": base["status"], "e3_run_id": int(run["id"]), "sentences": len(update.content["sentences"]),
               "superseded": len(update.superseded), "unplaced": len(update.content["unplaced"]), "selections": len(whys),
               "without_origin": 0, "latency_from_lineup_ms": latency}
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {
            "fixture": fixture, "at": at, "plan_at": base["plan_at"], "version": base["version"], "plan_version": base["plan_version"],
            "classes_version": base["classes_version"], "verify_version": base["verify_version"], "figure_version": base["figure_version"],
            "packet": base["packet_id"], "plan_hash": base["plan_hash"], "input_hash": up.input_hash(int(base["id"]), lineup, whys),
            "plan": Jsonb(base["plan"]), "status": status, "abstention": None, "content": Jsonb(content), "dropped": Jsonb([]),
            "metrics": Jsonb(metrics), "route": "none", "provider": None, "model": None, "usage_id": None,
            "custom_id": f"{CUSTOM_PREFIX}{int(run['id'])}", "cost": 0, "error": None, "code": code_version})
        row = cur.fetchone()
    return None if row is None else int(row[0])


def run(conn: psycopg.Connection[Any], *, at: datetime, mode_word: Mode | None = None, code_version: str | None = None) -> RunReport:
    """One pass. Off: returns before reading anything. Each E3 in a savepoint of its own: one that fails is counted, never the end."""
    word = mode_word or mode()
    report = RunReport(word)
    if word == "off":
        return report
    due = _rows(conn, DUE_SQL, {"start": at - WINDOW, "end": at + WINDOW, "at": at, "prefix": CUSTOM_PREFIX, "limit": LIMIT})
    report.counts["due"] = len(due)
    for r in due:
        try:
            with conn.transaction():
                rid = one(conn, r, at=at, code_version=code_version)
        except Exception as exc:  # one match never stops the others
            report.counts["errors"] += 1
            log.error("chronicle_update.failed_one", fixture_id=r.get("fixture_id"), error=f"{type(exc).__name__}: {exc}"[:300])
            continue
        if rid is None:
            report.counts["skipped"] += 1
            continue
        report.written.append(rid)
        report.counts["written"] += 1
        if r["trigger_at"] is not None:
            report.latency_ms.append(max(0, int((at - r["trigger_at"]).total_seconds() * 1000)))
    return report


def run_job(conn: psycopg.Connection[Any], *, at: datetime, code_version: str | None = None) -> RunReport:
    """One pass with its row in the job ledger only when it wrote or failed (a quiet pass, the usual one, leaves none). Off: nothing."""
    if mode() == "off":
        return RunReport("off")
    report = run(conn, at=at, code_version=code_version)
    conn.commit()
    if not report.written and not report.counts["errors"]:
        return report
    from fbi.ingestion.ledger import RunCounters, RunLedger

    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": up.VERSION, "why": up.WHY_VERSION})
    counters = RunCounters()
    counters.rows_inserted = len(report.written)
    counters.errors.extend(["an E3 raised (see chronicle_update.failed_one)"] * report.counts["errors"])
    ledger.close(run_id, counters, notes=json.dumps(report.as_json())[:NOTES_LIMIT])
    conn.commit()
    return report


__all__ = ["CUSTOM_PREFIX", "EVERY_MINUTES", "JOB", "SWITCH", "RunReport", "lineup_of", "mode", "one", "run", "run_job"]
