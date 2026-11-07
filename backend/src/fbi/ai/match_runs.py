"""The state of a match at the end of each pass, written without a model (plan IA, phase 1: ``ai.match_runs``, ``ms-v1``).

Phase 1 puts in place everything an agent will need and calls none. For every pass the AI layer has already run over a match - a row of
``ai.fixture_passes`` (the three passes of the day) or the owner's «run now» (a brief of the pass ``request``) - this module derives the
``mcp-v1`` package from the packet that pass stored (``fbi.ai.package.derive``, with the forecasts of the counts as of the packet), cuts its
slices, and appends one row to ``ai.match_runs``: the hash of the package and of each slice, their size in real tokens, what blocks them and
what was cleaned - never their content, which anyone can derive again from the stored packet, and the nightly audit does (``slice_known``).

Nothing here calls a model, searches the web, asks the provider for anything or creates a packet: it reads what the passes stored and writes a
table nothing reads yet (the Match Agent of phase 3 will, through ``ai.match_state``). So its rollback is to stop it (``FBI_AI_PACKAGE=0``).

What a run does, in the order it does it:

* the passes still without a state, newest first, at most ``LIMIT`` of them and none older than ``WINDOW`` (the AI layer works on today's matches;
  an older pass is history, and the audit reads the day it was written). A pass whose packet is not before the kick-off is not a pre-match
  state and is left alone; so is a pass that did not end ``ok`` or ``partial``, and a pass with no packet (it has nothing to derive from: it
  falls out of the join with the packets).
* each state stands on its own: one transaction per row, and ``ON CONFLICT DO NOTHING`` on the key of the table (a match, a kind of run, a pass
  and the moment of knowledge), so a second worker or a second run writes nothing twice;
* a packet that makes the package refuse (``PackageLeakError``: a stamp later than the pass) writes no row and is counted as ``refused`` with
  where it is; the same packet is tried again at the next run, and so with the code of the next release. A failure of the database for one row is
  counted as ``failed`` and the next row goes on; a connection that is gone ends the run, and so does the time (``MAX_SECONDS``): what was not
  tried is ``deferred``. Every pass a run finds ends in exactly one of ``built``, ``existing``, ``refused``, ``failed`` or ``deferred``.
* the run keeps its own ledger row in ``ai.cycles`` (kind ``package``) - only when there was something to do, so an idle clock leaves nothing.

``model_status.code`` keeps the fingerprint of the model code the package was derived with (``fbi.core.version.model_code_version``): it is
part of the package, so the audit needs it to derive the same package again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import package as mcp_package
from fbi.ai.config import AiSettings
from fbi.ai.contracts.mcp import SLICE_NAMES, PassKind
from fbi.ai.cycle import CycleReport, close_cycle, open_cycle
from fbi.core.version import model_code_version

STATE_VERSION: Final = "ms-v1"
"""The rule that writes a row: which column keeps what (``ai.match_runs.state_version``)."""
CYCLE_KIND: Final = "package"
WINDOW: Final = timedelta(days=4)
"""How far back a pass is still turned into a state."""
LIMIT: Final = 200
"""The most passes one run turns into states."""
MAX_SECONDS: Final = 90.0
"""The most time one run spends building: past it the rest waits for the next run (``deferred``)."""
COUNTS: Final = ("pending", "built", "existing", "refused", "failed", "deferred")

PENDING_SQL: Final = """
SELECT * FROM (
    SELECT DISTINCT ON (x.fixture_id, x.pass_kind, k.as_of) x.fixture_id, x.pass_kind, x.packet_id, k.as_of AS known_at, x.passed_at
      FROM (SELECT p.fixture_id, p.pass AS pass_kind, p.packet_id, p.finished_at AS passed_at
              FROM ai.fixture_passes p
             WHERE p.status IN ('ok', 'partial') AND p.finished_at >= %(since)s
             UNION ALL
            SELECT b.fixture_id, b.pass, b.packet_id, b.created_at
              FROM ai.match_briefs b
             WHERE b.pass = 'request' AND b.created_at >= %(since)s) x
      JOIN ai.match_packets k ON k.id = x.packet_id
      JOIN core.fixtures f ON f.id = x.fixture_id
     WHERE k.as_of < f.kickoff_at
       AND NOT EXISTS (SELECT 1 FROM ai.match_runs r
                        WHERE r.fixture_id = x.fixture_id AND r.run_kind = 'live' AND r.pass_kind = x.pass_kind AND r.known_at = k.as_of)
     ORDER BY x.fixture_id, x.pass_kind, k.as_of, x.passed_at, x.packet_id
) d
ORDER BY d.passed_at DESC, d.packet_id DESC, d.pass_kind
LIMIT %(limit)s
"""
"""The passes without a state: ``(match, pass, packet, moment of knowledge)``. One row per match, pass and moment, the first that made it."""

INSERT_SQL: Final = """
INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, package_hash, packet_id,
                           elapsed_ms, slices, blocking, flags, model_status)
VALUES (%(fixture)s, 'live', %(pass_kind)s, %(known_at)s, %(created_at)s, %(state)s, %(package_version)s, %(package_hash)s, %(packet)s,
        %(elapsed_ms)s, %(slices)s, %(blocking)s, %(flags)s, %(model_status)s)
ON CONFLICT (fixture_id, run_kind, pass_kind, known_at) DO NOTHING
RETURNING id
"""


@dataclass(frozen=True, slots=True)
class Pending:
    """A pass that stored a packet and has no state yet."""

    fixture_id: int
    pass_kind: PassKind
    packet_id: int
    known_at: datetime
    passed_at: datetime

    def where(self) -> str:
        return f"match {self.fixture_id}, pass {self.pass_kind}, packet {self.packet_id}"


def pending(conn: psycopg.Connection[Any], *, at: datetime, limit: int = LIMIT) -> list[Pending]:
    """The passes of the last ``WINDOW`` that have a packet before the kick-off and no live state, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PENDING_SQL, {"since": at - WINDOW, "limit": limit})
        return [Pending(fixture_id=int(r["fixture_id"]), pass_kind=r["pass_kind"], packet_id=int(r["packet_id"]), known_at=r["known_at"],
                        passed_at=r["passed_at"]) for r in cur.fetchall()]


@dataclass(frozen=True, slots=True)
class Written:
    """What one state cost to build: the id of its row (None: it was already there), the tokens of its biggest slice and the milliseconds."""

    row_id: int | None
    tokens: int
    elapsed_ms: int


def record(conn: psycopg.Connection[Any], item: Pending, *, model_code: str, at: datetime) -> Written:
    """The state of one pass: the package derived from its packet, the slices cut, one row written. The caller commits.

    Raises ``PackageLeakError`` when the packet makes the package refuse, and ``LookupError`` when the packet is not there."""
    package = mcp_package.derive(conn, item.packet_id, pass_kind=item.pass_kind, model_code=model_code)
    if package is None:
        raise LookupError(f"the packet {item.packet_id} is not there")
    made = mcp_package.slices_of(package)
    values = {"fixture": package.fixture_id, "pass_kind": item.pass_kind, "known_at": package.known_at, "created_at": max(at, package.known_at),
              "state": STATE_VERSION, "package_version": package.version, "package_hash": package.hash, "packet": item.packet_id,
              "elapsed_ms": package.elapsed_ms, "slices": Jsonb([made[name].measures() for name in SLICE_NAMES]),
              "blocking": list(package.blocking), "flags": list(package.flags),
              "model_status": Jsonb({"code": model_code} if model_code else {})}
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, values)
        row = cur.fetchone()
    return Written(row_id=None if row is None else int(row[0]), tokens=max(s.tokens for s in made.values()), elapsed_ms=package.elapsed_ms)


def run(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, limit: int = LIMIT, max_seconds: float = MAX_SECONDS) -> CycleReport | None:
    """Turns the passes without a state into states. None when there is nothing to do (and then nothing is written, not even a ledger row)."""
    todo = pending(conn, at=at, limit=limit)
    if not todo:
        return None
    cycle_id = open_cycle(conn, CYCLE_KIND, at=at, settings=settings)
    report = CycleReport(cycle_id=cycle_id)
    for name in COUNTS:
        report.counts[name] += 0
    report.counts["pending"] = len(todo)
    report.counts["build_ms"] = 0
    report.counts["tokens_max"] = 0
    code = model_code_version()
    started = time.monotonic()
    tried = 0
    for item in todo:
        if time.monotonic() - started >= max_seconds:
            break
        tried += 1
        try:
            done = record(conn, item, model_code=code, at=at)
            conn.commit()
        except mcp_package.PackageLeakError as exc:
            conn.rollback()
            report.counts["refused"] += 1
            report.errors.append(f"refused, {item.where()}: {exc}")
            continue
        except Exception as exc:  # a row that cannot be written is counted and the next one goes on; the job never stops the worker
            if not conn.closed:
                conn.rollback()
            report.counts["failed"] += 1
            report.errors.append(f"failed, {item.where()}: {type(exc).__name__}: {exc}")
            if conn.closed:
                break
            continue
        report.counts["built" if done.row_id is not None else "existing"] += 1
        report.counts["build_ms"] += done.elapsed_ms
        report.counts["tokens_max"] = max(report.counts["tokens_max"], done.tokens)
    report.counts["deferred"] = len(todo) - tried  # out of time, or the connection went: every pass ends in exactly one of the five counts
    bad = report.counts["refused"] + report.counts["failed"]
    report.status = "ok" if not bad else ("partial" if report.counts["built"] + report.counts["existing"] else "failed")
    close_cycle(conn, cycle_id, report, at=at)
    return report
