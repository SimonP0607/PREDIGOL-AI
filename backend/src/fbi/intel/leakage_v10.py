"""Data-leakage audit - ``leak-audit-v10`` (IA-061, plan AD-A04): the last reading of a match before its last pass, and the news the agents read.

It runs every night AFTER ``leak-audit-v9`` (``fbi.intel.leakage``), over the same Bogotá day, and writes its own rows to ``intel.audit_checks`` with
its own version. v9 is not changed, not run again and its rows are never recomputed: every rule of v9 keeps writing as ``leak-audit-v9`` - Gate B
reads those - and v10 is the rules below, which v9 did not have. ``leak-audit-v10`` is, then, v9's rules (rows ``leak-audit-v9``) plus these
(rows ``leak-audit-v10``).

    final_reread_known       the shadow's states of a ``final`` pass (``ai.match_runs``, ``run_kind = 'shadow'``) written on the day, once the
                             reading exists (from the first such state that carries one: a state written by the code of before has none and is
                             not read): each one carries the last reading of the match (``data_status.reread``, ``fbi.ai.final_reread``) in a
                             version this code knows, which let the pass go on, was made between the moment of the packet and the writing of
                             the state, saw the packet's kick-off, ahead of the reading, and a match still to be played. One check per state.
                             Examples are the ids of the states.
    final_started_known      every state of a ``final`` pass written on the day (live and shadow): its moment of knowledge is before the kick-off
                             as it is known TODAY, or the kick-off moved after the state was written and, when it was written, the provider
                             said a kick-off later than that moment (the first change of ``core.fixture_kickoff_changes`` observed after the
                             writing has ``before_kickoff > known_at``) - EXPLAINED: the provider's word, not a reading that was not made. What is
                             not explained is a violation. One check per state. Examples are the ids of the states with a violation.
    final_started_explained  the companion of the one above: ``n_checked`` is the number of states of the day EXPLAINED that way and its examples
                             are their ids. It is never a violation (``n_violations`` 0): it is the line that says an explained case is there,
                             so that a night is not clean in silence (12 Nov 2026, state 6912: written at 19:26:51 with the provider's kick-off at
                             20:00, corrected to 19:00 on 13 Nov at 10:57:29).
    news_known               the news, and every other fact from outside, that the packages of the day carry (every state of ``ai.match_runs``
                             with a package, live and shadow: the shadow's agents read theirs, the live ones are what the Match Agent will read):
                             the package is derived again from its stored packet with the version the state names, and every fact of its
                             evidence index is a row of ``ai.evidence`` of that match (or of a team), retrieved and - when dated - published by
                             the package's moment, and the times the packet copied are the row's (``fbi.ai.known_at.fact_problems``). One check
                             per fact, and one per state whose package this code cannot derive again (a violation). Examples are state ids.

Nothing here writes but ``audit_day``'s rows (the caller commits). Every rule reads the states of ONE day (some hundreds at most) and looks up what
they name by id.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import final_reread, known_at
from fbi.ai import package as mcp_package
from fbi.ai.calendar import day_bounds
from fbi.core import match_state

VERSION: Final = "leak-audit-v10"
BASE_VERSION: Final = "leak-audit-v9"
"""The audit whose rules v10 extends (``fbi.intel.leakage.VERSION``; a test holds the two equal)."""
READINGS: Final = frozenset({final_reread.VERSION})
"""The versions of the last reading this audit knows: a reading of another version is a violation until the audit is taught it."""

FINAL_ROWS: Final = """
WITH since AS (SELECT min(m.created_at) AS at FROM ai.match_runs m
                WHERE m.run_kind = 'shadow' AND m.pass_kind = 'final' AND m.data_status ? 'reread')
SELECT r.id, r.fixture_id, r.run_kind, r.known_at, r.created_at, r.data_status -> 'reread' AS reread,
       p.content -> 'fixture' ->> 'kickoff_at' AS packet_kickoff, p.fixture_id AS packet_fixture, f.kickoff_at,
       (SELECT s.at FROM since s) AS reread_since, c.before_kickoff AS stated_then
  FROM ai.match_runs r
  LEFT JOIN ai.match_packets p ON p.id = r.packet_id
  LEFT JOIN core.fixtures f ON f.id = r.fixture_id
  LEFT JOIN LATERAL (SELECT c.before_kickoff FROM core.fixture_kickoff_changes c
                      WHERE c.fixture_id = r.fixture_id AND c.observed_at > r.created_at
                      ORDER BY c.observed_at, c.after_kickoff LIMIT 1) c ON true
 WHERE r.created_at >= %(start)s AND r.created_at < %(end)s AND r.pass_kind = 'final' AND r.package_hash IS NOT NULL
 ORDER BY r.id
"""
"""The states of a final pass written on the day, with the packet's kick-off, today's kick-off, the first moment a state carried a reading, and the
kick-off the provider stated when the state was written if it changed afterwards (the ``before`` of the first change observed after the writing)."""

PACKAGE_ROWS: Final = """
SELECT r.id, r.fixture_id, r.pass_kind, r.known_at, r.package_version, r.packet_id, r.model_status ->> 'code' AS model_code
  FROM ai.match_runs r
 WHERE r.created_at >= %(start)s AND r.created_at < %(end)s AND r.package_hash IS NOT NULL AND r.packet_id IS NOT NULL
 ORDER BY r.id
"""


def _present(conn: psycopg.Connection[Any], *tables: str) -> bool:
    with conn.cursor() as cur:
        for table in tables:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
            row = cur.fetchone()
            if not row or not row[0]:
                return False
    return True


# ── final_reread_known ───────────────────────────────────────────────────────────────────────────────────────────

def reread_problems(row: dict[str, Any]) -> list[str]:
    """What is wrong with the last reading a shadow state of a final pass carries (empty: honest). Pure; see ``final_reread_known``."""
    rec = row.get("reread")
    if not isinstance(rec, dict):
        return ["no_reread"]
    if rec.get("version") not in READINGS:
        return ["reread_version"]
    out: list[str] = []
    if rec.get("ok") is not True:
        out.append("reread_not_ok")  # a reading that stopped the pass leaves no state: a state with one is a pass that went on anyway
    at = final_reread.parse_moment(rec.get("at"))
    if at is None or at < row["known_at"] or at > row["created_at"]:
        out.append("reread_out_of_time")
    seen = final_reread.parse_moment(rec.get("kickoff_at"))
    packet = final_reread.parse_moment(row.get("packet_kickoff"))
    if seen is None or packet is None or seen != packet or final_reread.parse_moment(rec.get("packet_kickoff_at")) != packet:
        out.append("reread_kickoff_differs")
    if seen is None or at is None or seen <= at:
        out.append("reread_after_kickoff")
    if match_state.code(rec.get("status")) != "NS" or rec.get("in_play_at") is not None:
        out.append("reread_not_scheduled")
    return out


def final_reread_known(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> tuple[int, int, list[int]]:
    rows = _final_rows(conn, start, end)
    judged = [r for r in rows if r["run_kind"] == "shadow" and r["reread_since"] is not None and r["created_at"] >= r["reread_since"]]
    bad = [int(r["id"]) for r in judged if reread_problems(r)]
    return len(judged), len(bad), bad[:5]


# ── final_started_known / final_started_explained ────────────────────────────────────────────────────────────────

def started_verdict(row: dict[str, Any]) -> str:
    """``honest`` (known before today's kick-off), ``explained`` (the provider moved the kick-off after the state was written, from one later than
    its moment) or ``violation``. Pure."""
    kickoff = row.get("kickoff_at")
    if kickoff is not None and row["known_at"] < kickoff:
        return "honest"
    stated = row.get("stated_then")
    if kickoff is not None and stated is not None and stated > row["known_at"]:
        return "explained"
    return "violation"


def _final_rows(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> list[dict[str, Any]]:
    if not _present(conn, "ai.match_runs", "ai.match_packets", "core.fixture_kickoff_changes"):
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FINAL_ROWS, {"start": start, "end": end})
        return [dict(r) for r in cur.fetchall()]


def final_started(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> tuple[tuple[int, int, list[int]], tuple[int, int, list[int]]]:
    """``(checked, violations, examples)`` of ``final_started_known`` and of ``final_started_explained`` (explained, 0, their ids)."""
    rows = _final_rows(conn, start, end)
    verdicts = [(int(r["id"]), started_verdict(r)) for r in rows]
    bad = [i for i, v in verdicts if v == "violation"]
    explained = [i for i, v in verdicts if v == "explained"]
    return (len(rows), len(bad), bad[:5]), (len(explained), 0, explained[:5])


# ── news_known ───────────────────────────────────────────────────────────────────────────────────────────────────

def _package_facts(conn: psycopg.Connection[Any], row: dict[str, Any]) -> tuple[list[int], dict[int, known_at.Copy]] | None:
    """The facts of the package of a state and the moments its packet copied, or None when this code cannot derive that package again."""
    if row["package_version"] not in mcp_package.DERIVABLE:
        return None
    stored = mcp_package.load_stored(conn, int(row["packet_id"]))
    if stored is None or stored[0].fixture_id != row["fixture_id"]:
        return None
    packet, stored_hash = stored
    try:
        package = mcp_package.package_from_packet(packet, pass_kind=row["pass_kind"], model_code=row["model_code"] or "",
                                                  packet_id=int(row["packet_id"]), source_hash=stored_hash, version=row["package_version"])
    except psycopg.Error:
        raise
    except Exception:  # a packet written by hand can fail the rule and never stop the audit
        return None
    if package.known_at != row["known_at"]:
        return None
    return known_at.package_facts(package.document), known_at.packet_copies(packet.content)


def news_known(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> tuple[int, int, list[int]]:
    if not _present(conn, "ai.match_runs", "ai.match_packets", "ai.evidence"):
        return 0, 0, []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PACKAGE_ROWS, {"start": start, "end": end})
        rows = [dict(r) for r in cur.fetchall()]
    derived = {int(r["id"]): _package_facts(conn, r) for r in rows}
    evidence = known_at.rows_of(conn, {i for d in derived.values() if d is not None for i in d[0]})
    checked, violations, bad = 0, 0, []
    for r in rows:
        got = derived[int(r["id"])]
        if got is None:
            checked, violations = checked + 1, violations + 1
            bad.append(int(r["id"]))
            continue
        facts, copies = got
        problems = known_at.fact_problems(int(r["fixture_id"]), r["known_at"], facts, copies, evidence)
        checked += len(facts)
        violations += len(problems)
        if problems:
            bad.append(int(r["id"]))
    return checked, violations, bad[:5]


# ── the night ────────────────────────────────────────────────────────────────────────────────────────────────────

RULE_NAMES: Final = ("final_reread_known", "final_started_known", "final_started_explained", "news_known")
"""Every rule of v10, in the order the night writes them."""


def audit_day(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> dict[str, dict[str, Any]]:
    """Run the rules of v10 over the Bogotá ``day`` and write one row per rule (``version = 'leak-audit-v10'``). The caller commits."""
    start, end = day_bounds(day)
    started, explained = final_started(conn, start, end)
    results = {"final_reread_known": final_reread_known(conn, start, end), "final_started_known": started,
               "final_started_explained": explained, "news_known": news_known(conn, start, end)}
    out: dict[str, dict[str, Any]] = {}
    with conn.cursor() as cur:
        for rule in RULE_NAMES:
            n, bad, examples = results[rule]
            out[rule] = {"checked": n, "violations": bad, "examples": examples}
            cur.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations, examples) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)", (day, at, VERSION, rule, n, bad, Jsonb(examples)))
    return out
