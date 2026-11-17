"""The shadow writer of the cycle (IA-068, AD-D02): read the layers, append to ``intel.selection_lifecycle`` what is missing.

One pass (``run_pass``), every ``EVERY`` minutes from the worker while ``FBI_LIFECYCLE=shadow`` (``off`` by default: the job is
not even scheduled):

1. the matches with a decision or a shadow pick whose kick-off is in ``[now - BACK, now + AHEAD)``, minus the ones already
   played whose chains are all closed (``descartada``, ``evaluada``);
2. what the layers hold about each of their selections (``SOURCES_SQL``: ``intel.decisions`` of the layers it follows,
   ``picks.picks``, ``ai.pick_reviews``, ``intel.decision_outcomes``, ``intel.postmortems``, ``intel.family_postmortems``) - read
   only, under a statement timeout;
3. the chain each selection should have (``fbi.lifecycle.derive``), compared with the stored one: a stored chain that is a prefix
   of it gets the rest appended; one that is not (a layer said something that the stored rows contradict) is counted as
   ``divergent`` and left as it is - nothing is ever rewritten.

It writes ``intel.selection_lifecycle`` and nothing else (``tests/unit/test_lifecycle_isolation.py`` scans every statement).
Two passes at once cannot write: the pass holds an advisory lock. The same database gives the same rows: the pass is idempotent.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.lifecycle import derive, machine
from fbi.lifecycle.derive import Decision, Evaluation, Fixture, History, Key, Outcome, Review, Row

SWITCH: Final = "FBI_LIFECYCLE"
WRITER: Final = "lifecycle-shadow-v1"
"""The writer of the chains read off today's layers. The evaluations of AD-D06 will write chains of their own (``eval-cycle-v1``)."""
LAYERS: Final[tuple[str, ...]] = (DECISION_CORE, DECISION_FAMILIES)
"""The decision layers whose rows drive a chain: the candidates decision-v2's replay re-decides (``fbi.decision.replay``) are these
same rows. decision-v2 writes nothing yet (AD-D01): its table joins here the day it exists."""
EVERY: Final = int(os.environ.get("FBI_LIFECYCLE_MINUTES", "30"))
BACK: Final = timedelta(days=7)
"""How far back a match is still followed: its settlement (p90 48 h after kick-off) and its post-mortem."""
AHEAD: Final = timedelta(hours=48)
CHUNK: Final = 100
LOCK: Final = 0x1A068
TIMEOUT_MS: Final = 60_000


def mode() -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    return "shadow" if os.environ.get(SWITCH, "off").strip().lower() == "shadow" else "off"


FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group
  FROM core.fixtures f
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
   AND (EXISTS (SELECT 1 FROM intel.decisions d WHERE d.fixture_id = f.id AND d.decision_version = ANY(%(layers)s))
        OR EXISTS (SELECT 1 FROM picks.picks p WHERE p.fixture_id = f.id))
 ORDER BY f.kickoff_at, f.id
"""
STORED_SQL: Final = """
SELECT id, chain_key, fixture_id, market_key, selection, line, state, reason, source, source_id, known_at
  FROM intel.selection_lifecycle
 WHERE fixture_id = ANY(%(fixtures)s) AND writer = %(writer)s
 ORDER BY chain_key, id
"""
DECISIONS_SQL: Final = """
SELECT d.id, d.decision_version, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.state, d.reasons,
       d.context_status, d.kickoff_at
  FROM intel.decisions d
 WHERE d.fixture_id = ANY(%(fixtures)s) AND d.decision_version = ANY(%(layers)s)
"""
PICKS_SQL: Final = """
SELECT DISTINCT ON (fixture_id, market_key, selection, line) id, fixture_id, market_key, selection, line, created_at
  FROM picks.picks
 WHERE fixture_id = ANY(%(fixtures)s)
 ORDER BY fixture_id, market_key, selection, line, created_at, id
"""
REVIEWS_SQL: Final = """
SELECT id, fixture_id, market_key, selection, line, reviewed_at, decision
  FROM ai.pick_reviews
 WHERE fixture_id = ANY(%(fixtures)s) AND engine = 'combined' AND status = 'ok' AND decision IN ('REJECT', 'DOWNGRADE')
"""
"""The review of record (the combined one decision-v1 reads), in either mode: only what takes a selection down."""
OUTCOMES_SQL: Final = """
SELECT o.decision_id, o.settled_at, o.result_status
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id
 WHERE d.fixture_id = ANY(%(fixtures)s) AND d.decision_version = ANY(%(layers)s) AND o.settled_at IS NOT NULL
"""
EVALUATIONS_SQL: Final = """
SELECT 'intel.postmortems' AS source, p.id, p.decision_id, p.created_at
  FROM intel.postmortems p JOIN intel.decisions d ON d.id = p.decision_id
 WHERE d.fixture_id = ANY(%(fixtures)s) AND d.decision_version = ANY(%(layers)s)
UNION ALL
SELECT 'intel.family_postmortems' AS source, p.id, p.decision_id, p.created_at
  FROM intel.family_postmortems p JOIN intel.decisions d ON d.id = p.decision_id
 WHERE d.fixture_id = ANY(%(fixtures)s) AND d.decision_version = ANY(%(layers)s)
"""
INSERT_SQL: Final = """
INSERT INTO intel.selection_lifecycle (chain_key, writer, fixture_id, market_key, selection, line, layer, previous_id, from_state,
    state, reason, actor, owner_signature, evaluation, evaluation_version, settlement_result, known_at, source, source_id,
    machine_version, map_version)
VALUES (%(chain_key)s, %(writer)s, %(fixture_id)s, %(market_key)s, %(selection)s, %(line)s, %(layer)s, %(previous_id)s,
    %(from_state)s, %(state)s, %(reason)s, %(actor)s, %(owner_signature)s, %(evaluation)s, %(evaluation_version)s,
    %(settlement_result)s, %(known_at)s, %(source)s, %(source_id)s, %(machine_version)s, %(map_version)s)
RETURNING id
"""


def chain_key(writer: str, key: Key) -> str:
    """The table's ``chain_key`` (its CHECK computes the same from the columns: ``line::text`` of a NUMERIC(6,2) is ``2.50``)."""
    return f"{writer}|{key.fixture_id}|{key.market_key}|{key.selection}|{key.line}"


def _key(r: Mapping[str, Any]) -> Key:
    return Key.of(r["fixture_id"], r["market_key"], r["selection"], r["line"])


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def histories(conn: psycopg.Connection[Any], fixtures: Sequence[int], *, layers: Sequence[str] = LAYERS) -> dict[Key, History]:
    """What the layers hold about every selection of ``fixtures``. Read-only."""
    p = {"fixtures": list(fixtures), "layers": list(layers)}
    out: dict[Key, History] = {}

    def h(k: Key) -> History:
        return out.setdefault(k, History(k))

    for r in _fetch(conn, DECISIONS_SQL, p):
        h(_key(r)).decisions.append(Decision(int(r["id"]), str(r["decision_version"]), r["known_at"], str(r["checkpoint"]),
                                             str(r["state"]), tuple(str(c) for c in r["reasons"] or ()), str(r["context_status"]),
                                             r["kickoff_at"]))
    for r in _fetch(conn, PICKS_SQL, p):
        hist = h(_key(r))
        hist.detected_at, hist.detected_pick = r["created_at"], int(r["id"])
    for r in _fetch(conn, REVIEWS_SQL, p):
        k = _key(r)
        if k in out:
            out[k].reviews.append(Review(int(r["id"]), r["reviewed_at"], str(r["decision"])))
    outcomes = {int(r["decision_id"]): Outcome(int(r["decision_id"]), r["settled_at"], str(r["result_status"]))
                for r in _fetch(conn, OUTCOMES_SQL, p)}
    evaluations: dict[int, Evaluation] = {}
    for r in sorted(_fetch(conn, EVALUATIONS_SQL, p), key=lambda x: (x["created_at"], x["id"])):
        evaluations.setdefault(int(r["decision_id"]), Evaluation(int(r["decision_id"]), r["created_at"], str(r["source"]),
                                                                 int(r["id"])))
    for hist in out.values():
        ids = {d.id for d in hist.decisions}
        hist.outcomes = {i: o for i, o in outcomes.items() if i in ids}
        hist.evaluations = {i: e for i, e in evaluations.items() if i in ids}
    return out


@dataclass
class PassReport:
    fixtures: int = 0
    skipped_closed: int = 0
    selections: int = 0
    appended: int = 0
    unchanged: int = 0
    extended: int = 0
    new_chains: int = 0
    divergent: int = 0
    illegal: int = 0
    unknown_reason: int = 0
    by_state: Counter[str] = field(default_factory=Counter)
    """The newest state of every selection seen in the pass (the derived chain's last row)."""
    by_reason: Counter[str] = field(default_factory=Counter)
    rows_by_state: Counter[str] = field(default_factory=Counter)
    """The rows appended (or that a dry run would append), by state."""
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"fixtures": self.fixtures, "skipped_closed": self.skipped_closed, "selections": self.selections,
                "appended": self.appended, "unchanged": self.unchanged, "extended": self.extended, "new_chains": self.new_chains,
                "divergent": self.divergent, "illegal": self.illegal, "unknown_reason": self.unknown_reason,
                "by_state": dict(sorted(self.by_state.items())), "by_reason": dict(sorted(self.by_reason.items())),
                "rows_by_state": dict(sorted(self.rows_by_state.items())), "errors": self.errors[:20]}


@dataclass(frozen=True, slots=True)
class Stored:
    id: int
    state: str
    reason: str
    source: str
    source_id: int | None


def same(stored: Stored, row: Row) -> bool:
    return (stored.state, stored.reason, stored.source, stored.source_id) == (row.step.state, row.step.reason, row.source,
                                                                              row.source_id)


def plan(stored: Sequence[Stored], derived: Sequence[Row]) -> tuple[str, list[Row]]:
    """(``unchanged`` | ``new`` | ``extended`` | ``divergent``, the rows to append). Pure."""
    if len(stored) > len(derived) or any(not same(s, d) for s, d in zip(stored, derived, strict=False)):
        return "divergent", []
    rest = list(derived[len(stored):])
    if not rest:
        return "unchanged", []
    return ("new" if not stored else "extended"), rest


def _table_exists(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT to_regclass('intel.selection_lifecycle') IS NOT NULL").fetchone()
    return bool(row and row[0])


def _stored(conn: psycopg.Connection[Any], fixtures: Sequence[int], writer: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in _fetch(conn, STORED_SQL, {"fixtures": list(fixtures), "writer": writer}):
        out.setdefault(str(r["chain_key"]), []).append(r)
    return out


def _insert(conn: psycopg.Connection[Any], *, writer: str, key: Key, row: Row, previous_id: int | None,
            from_state: str | None) -> int:
    s = row.step
    got = conn.execute(INSERT_SQL, {
        "chain_key": chain_key(writer, key), "writer": writer, "fixture_id": key.fixture_id, "market_key": key.market_key,
        "selection": key.selection, "line": key.line, "layer": row.layer, "previous_id": previous_id, "from_state": from_state,
        "state": s.state, "reason": s.reason, "actor": s.actor, "owner_signature": s.owner_signature, "evaluation": s.evaluation,
        "evaluation_version": s.evaluation_version, "settlement_result": s.settlement_result, "known_at": row.known_at,
        "source": row.source, "source_id": row.source_id, "machine_version": machine.VERSION,
        "map_version": derive.MAP_VERSION}).fetchone()
    assert got is not None
    return int(got[0])


def _chunks(xs: Sequence[int], n: int) -> Iterable[list[int]]:
    for i in range(0, len(xs), n):
        yield list(xs[i:i + n])


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, dry_run: bool = False, writer: str = WRITER,
             layers: Sequence[str] = LAYERS, back: timedelta = BACK, ahead: timedelta = AHEAD,
             chunk: int = CHUNK) -> PassReport:
    """One pass of the shadow writer. ``dry_run`` reads the same and writes nothing (it works before the table exists, as if it
    were empty). Commits once per chunk of matches; a chunk that fails is rolled back, counted and the pass goes on."""
    rep = PassReport()
    have_table = _table_exists(conn)
    if not dry_run and not have_table:
        raise RuntimeError("intel.selection_lifecycle does not exist: apply revision 0142 first")
    if not dry_run:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
        if not got or not got[0]:
            rep.errors.append("another pass holds the lock")
            conn.rollback()
            return rep
    try:
        conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        fixtures = {int(r["id"]): Fixture(int(r["id"]), r["kickoff_at"], r["status_short"], r["status_group"])
                    for r in _fetch(conn, FIXTURES_SQL, {"start": now - back, "end": now + ahead, "layers": list(layers)})}
        rep.fixtures = len(fixtures)
        conn.commit()
        for ids in _chunks(sorted(fixtures), chunk):
            try:
                _one_chunk(conn, ids, fixtures, now=now, dry_run=dry_run, have_table=have_table, writer=writer, layers=layers,
                           rep=rep)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                rep.errors.append(f"{ids[0]}..{ids[-1]}: {type(exc).__name__}: {exc}"[:300])
    finally:
        if not dry_run:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
            conn.commit()
    return rep


def _one_chunk(conn: psycopg.Connection[Any], ids: list[int], fixtures: Mapping[int, Fixture], *, now: datetime, dry_run: bool,
               have_table: bool, writer: str, layers: Sequence[str], rep: PassReport) -> None:
    stored = _stored(conn, ids, writer) if have_table else {}
    tips: dict[int, list[str]] = {}
    for kept in stored.values():
        tips.setdefault(int(kept[-1]["fixture_id"]), []).append(str(kept[-1]["state"]))
    live = [i for i in ids if not (fixtures[i].kickoff_at < now and tips.get(i) and all(s in machine.TERMINAL for s in tips[i]))]
    rep.skipped_closed += len(ids) - len(live)
    if not live:
        return
    for key, hist in sorted(histories(conn, live, layers=layers).items(), key=lambda kv: (kv[0].fixture_id, kv[0].market_key,
                                                                                         kv[0].selection, kv[0].line)):
        try:
            chain = derive.derive(hist, fixtures[key.fixture_id], now=now)
        except machine.IllegalTransitionError as exc:
            rep.illegal += 1
            rep.errors.append(f"{chain_key(writer, key)}: {exc}"[:300])
            continue
        if not chain:
            continue
        rep.selections += 1
        rep.by_state[chain[-1].step.state] += 1
        rep.by_reason[f"{chain[-1].step.state}:{chain[-1].step.reason}"] += 1
        rep.unknown_reason += sum(1 for r in chain if r.step.reason == "sin_motivo_conocido")
        have = [Stored(int(s["id"]), str(s["state"]), str(s["reason"]), str(s["source"]),
                       None if s["source_id"] is None else int(s["source_id"])) for s in stored.get(chain_key(writer, key), [])]
        verdict, rest = plan(have, chain)
        if verdict == "divergent":
            rep.divergent += 1
            continue
        if verdict == "unchanged":
            rep.unchanged += 1
            continue
        rep.new_chains += int(verdict == "new")
        rep.extended += int(verdict == "extended")
        previous_id = have[-1].id if have else None
        from_state = have[-1].state if have else None
        for r in rest:
            rep.rows_by_state[r.step.state] += 1
            rep.appended += 1
            if not dry_run:
                previous_id = _insert(conn, writer=writer, key=key, row=r, previous_id=previous_id, from_state=from_state)
            from_state = r.step.state


def measure(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, now: datetime,
            layers: Sequence[str] = LAYERS) -> dict[str, Any]:
    """How many selections and rows the cycle would hold for the matches that kick off in ``[start, end)``, derived as of ``now``
    from what the layers hold. Read-only (the measurement of 16-nov-2026 in production, ``docs/owner/IA_068_CICLO_DE_ESTADOS.md``)."""
    fixtures = {int(r["id"]): Fixture(int(r["id"]), r["kickoff_at"], r["status_short"], r["status_group"])
                for r in _fetch(conn, FIXTURES_SQL, {"start": start, "end": end, "layers": list(layers)})}
    ids = sorted(fixtures)
    found: dict[Key, History] = {}
    for part in _chunks(ids, CHUNK):
        found.update(histories(conn, part, layers=layers))
    by_layer: Counter[str] = Counter()
    rows_by_state: Counter[str] = Counter()
    final: Counter[str] = Counter()
    illegal = unknown = rows = 0
    for key, hist in found.items():
        try:
            chain = derive.derive(hist, fixtures[key.fixture_id], now=now)
        except machine.IllegalTransitionError:
            illegal += 1
            continue
        if not chain:
            continue
        by_layer[chain[0].layer] += 1
        rows += len(chain)
        rows_by_state.update(r.step.state for r in chain)
        unknown += sum(1 for r in chain if r.step.reason == "sin_motivo_conocido")
        final[f"{chain[-1].step.state}:{chain[-1].step.reason}"] += 1
    return {"fixtures": len(fixtures), "selections": sum(by_layer.values()), "by_layer": dict(sorted(by_layer.items())), "rows": rows,
            "rows_by_state": dict(sorted(rows_by_state.items())), "final": dict(final.most_common()), "illegal": illegal,
            "unknown_reason_rows": unknown}
