"""The worker's job of the estimated starters (IA-094, AD-D04): read what was known, estimate with ``fbi.players.lineup_estimate``, keep.

``FBI_LINEUP_ESTIMATE`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker does not even schedule
the job. In the shadow, every ``FBI_LINEUP_ESTIMATE_MINUTES`` (5 by default) one pass estimates every side of the tracked matches due at
E1 (24 to 12 hours before kick-off) or at E4 (20 to 10 minutes before: the same windows as decision-v2's kept shadow, IA-093) and not yet
estimated in that evaluation, at most ``MAX_FIXTURES`` matches a pass, nearest kick-off first, and appends one row per player to
``intel.lineup_estimates`` (revision 0151).

WHAT IT READS, as of the moment and nothing later: the played matches of the competition and of both teams of the last 180 days
(``fbi.players.history``), the provider's absences then (``fbi.ai.absences``) and the facts of the press about who is out
(``fbi.ai.evidence.CONTEXT_SQL``, v1's items) resolved into one state per player by IA-091 (``fbi.people.availability``), the facts
«titular» of the match (``ai.evidence`` line-up items that name a player; research v2's claims only when the system reads them,
``typed_visible``), and the official sheet if it was read by then (``core.fixture_lineups``). No provider, no model, no text of a claim.

This module is the one importer of the player engine outside its package and its command (``tests/unit/test_players_isolation.py``):
only the worker's scheduler imports it; nothing it writes is read by a decision, a pick or a page.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

SWITCH: Final = "FBI_LINEUP_ESTIMATE"
JOB: Final = "lineup_estimate_shadow"
E1_FROM: Final = timedelta(hours=24)
E1_UNTIL: Final = timedelta(hours=12)
E4_FROM: Final = timedelta(minutes=20)
E4_UNTIL: Final = timedelta(minutes=10)
MAX_FIXTURES: Final = 12
LOCK: Final = 0x1A094
TIMEOUT_MS: Final = 95_000


def mode(env: Mapping[str, str] | None = None) -> str:
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    e = os.environ if env is None else env
    try:
        value = int(e.get("FBI_LINEUP_ESTIMATE_MINUTES", "5").strip())
    except ValueError:
        return 5
    return value if 1 <= value <= 10 else 5


def evaluation_due(kickoff_at: datetime, now: datetime) -> str | None:
    """``E1`` or ``E4`` when ``now`` is in its window before ``kickoff_at``, else None. Pure."""
    if kickoff_at - E1_FROM <= now <= kickoff_at - E1_UNTIL:
        return "E1"
    if kickoff_at - E4_FROM <= now < kickoff_at - E4_UNTIL:
        return "E4"
    return None


DUE_SQL: Final = """
SELECT f.id, f.kickoff_at
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled'
   AND f.kickoff_at > %(at)s + %(floor)s AND f.kickoff_at <= %(at)s + %(ahead)s
 ORDER BY f.kickoff_at, f.id
"""
DONE_SQL: Final = """
SELECT DISTINCT fixture_id, evaluation FROM intel.lineup_estimates
 WHERE fixture_id = ANY(%(fixtures)s) AND version = %(version)s
"""
FACTS_SQL: Final = """
SELECT e.id, e.fixture_id, COALESCE(e.provider_player_id, p.provider_player_id) AS provider_player_id, e.attributes->>'assertion' AS assertion,
       e.claim_type, e.origin, e.status, e.source_tier, e.subject_type, e.retrieved_at, e.published_at
  FROM ai.evidence e
  LEFT JOIN core.players p ON e.subject_type = 'PLAYER' AND p.id = e.subject_id
 WHERE e.fixture_id = %(fixture)s AND e.kind = 'lineup' AND e.retrieved_at <= %(at)s
   AND (e.published_at IS NULL OR e.published_at <= %(at)s) AND (e.subject_type IS NULL OR %(typed)s)
"""
"""The line-up items of the match known by the moment; research v2's claims only when the system reads them (``typed_visible``)."""
INSERT_SQL: Final = """
INSERT INTO intel.lineup_estimates (fixture_id, team_id, provider_player_id, evaluation, known_at, kickoff_at, position, p_start, p_play,
    expected_minutes, basis, sample, share, started_last, absence_status, absence_basis, fact_rung, fact_ids, seal, lineup_confirmed,
    history_matches, start_model_samples, start_model_fitted, version, model, input_hash, code_version)
VALUES (%(fixture_id)s, %(team_id)s, %(provider_player_id)s, %(evaluation)s, %(known_at)s, %(kickoff_at)s, %(position)s, %(p_start)s,
    %(p_play)s, %(expected_minutes)s, %(basis)s, %(sample)s, %(share)s, %(started_last)s, %(absence_status)s, %(absence_basis)s,
    %(fact_rung)s, %(fact_ids)s, %(seal)s, %(lineup_confirmed)s, %(history_matches)s, %(start_model_samples)s, %(start_model_fitted)s,
    %(version)s, %(model)s, %(input_hash)s, %(code_version)s)
ON CONFLICT ON CONSTRAINT lineup_estimates_once DO NOTHING
"""


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


@dataclass
class PassReport:
    due: Counter[str] = field(default_factory=Counter)
    fixtures: int = 0
    sides: int = 0
    rows: int = 0
    confirmed_sides: int = 0
    bases: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"due": dict(sorted(self.due.items())), "fixtures": self.fixtures, "sides": self.sides, "rows": self.rows,
                "confirmed_sides": self.confirmed_sides, "bases": dict(sorted(self.bases.items())), "errors": self.errors[:20]}


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None = None, commit: bool = True,
             limit: int = MAX_FIXTURES) -> PassReport:
    """One pass. Each match is its own transaction (``commit``; a savepoint without it): one that fails is counted and the pass goes on."""
    from fbi.ai.gates import typed_visible
    from fbi.players import lineup_estimate as le

    rep = PassReport()
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
    if not got or not got[0]:
        rep.errors.append("another pass holds the lock")
        return rep
    try:
        if commit:
            conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        due = [(int(r["id"]), r["kickoff_at"]) for r in _fetch(conn, DUE_SQL, {"at": now, "floor": E4_UNTIL, "ahead": E1_FROM})]
        done = {(int(r["fixture_id"]), str(r["evaluation"])) for r in _fetch(conn, DONE_SQL, {"fixtures": [f for f, _ in due],
                                                                                               "version": le.VERSION})} if due else set()
        todo = [(f, k, ev) for f, k in due if (ev := evaluation_due(k, now)) is not None and (f, ev) not in done]
        todo.sort(key=lambda x: (x[1], x[0]))
        typed = typed_visible(conn)
        if commit:
            conn.commit()
        for fid, kickoff, ev in todo[:limit]:
            rep.due[ev] += 1
            try:
                with conn.transaction():
                    _one(conn, fid, kickoff, ev, now=now, typed=typed, code_version=code_version, rep=rep)
            except (psycopg.Error, ValueError, KeyError) as exc:
                rep.errors.append(f"{fid}/{ev}: {type(exc).__name__}: {exc}"[:300])
    finally:
        if commit:
            conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        if commit:
            conn.commit()
    return rep


def estimate_fixture(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, typed: bool) -> dict[str, Any] | None:
    """Every side of one match as of ``at``: the estimates and what they were made from. Read-only."""
    from fbi.ai import absences as provider_absences
    from fbi.ai import evidence as ai_evidence
    from fbi.people import availability as people
    from fbi.players import history as hist
    from fbi.players import lineup_estimate as le

    fx = hist.read_fixture(conn, fixture_id)
    if fx is None or at >= fx.kickoff:
        return None
    matches = [m for m in hist.load_matches(conn, at - le.HISTORY, at, competitions=[fx.competition_id],
                                            teams=[fx.home_team_id, fx.away_team_id], prefer_sheet=True) if m.fixture_id != fixture_id]
    engine = le.EstimateEngine(matches, hist.absence_history(conn, [m.fixture_id for m in matches if m.kickoff >= at - le.TRAIN]))
    engine.walk(at, record_from=at, train_from=at - le.TRAIN)
    engine.prepare(at)
    sheets = hist.confirmed_lineup(conn, fixture_id, at)
    listed = provider_absences.absences_as_of(conn, fixture_id, at)
    press = [r for r in _fetch(conn, ai_evidence.CONTEXT_SQL, {"fixture": fixture_id, "at": at}) if r.get("provider_player_id")]
    facts = le.facts_from_rows(_fetch(conn, FACTS_SQL, {"fixture": fixture_id, "at": at, "typed": typed}), at=at)
    # one state per player (a provider player id is one man, whichever side): the provider's listing and the press, by IA-091's precedence
    states = people.resolve(people.provider_reports(listed, fixture_id=fixture_id) + people.press_reports(
        [{"provider_player_id": r["provider_player_id"], "kind": r["kind"],
          "assertion": (r.get("attributes") or {}).get("assertion") if isinstance(r.get("attributes"), dict) else None,
          "status": r["status"], "source_tier": r["source_tier"], "source_name": r["source_domain"], "known_at": r["retrieved_at"],
          "fixture_id": r["fixture_id"], "player_name": None} for r in press if r.get("kind") != "lineup"]))
    sides: dict[str, Any] = {}
    for side, team in (("home", fx.home_team_id), ("away", fx.away_team_id)):
        sides[side] = {"team_id": team, "confirmed": side in sheets,
                       "estimates": le.estimate_side(engine.h, engine.model, fixture_id=fixture_id, team_id=team,
                                                     competition_id=fx.competition_id, states=states, facts=facts,
                                                     sheet=sheets.get(side))}
    return {"fixture": fx, "sides": sides, "history_matches": engine.h.matches, "start_model": engine.model}


def _one(conn: psycopg.Connection[Any], fixture_id: int, kickoff: datetime, evaluation: str, *, now: datetime, typed: bool,
         code_version: str | None, rep: PassReport) -> None:
    from fbi.players import lineup_estimate as le

    doc = estimate_fixture(conn, fixture_id, at=now, typed=typed)
    if doc is None:
        return
    rep.fixtures += 1
    model = doc["start_model"]
    for side in doc["sides"].values():
        rep.sides += 1
        rep.confirmed_sides += int(side["confirmed"])
        for e in side["estimates"]:
            row = e.as_json()
            rep.bases[e.basis] += 1
            rep.rows += 1
            conn.execute(INSERT_SQL, {
                "fixture_id": fixture_id, "team_id": side["team_id"], "provider_player_id": e.provider_player_id, "evaluation": evaluation,
                "known_at": now, "kickoff_at": kickoff, "position": e.position, "p_start": round(e.p_start, 4),
                "p_play": round(e.p_play, 4), "expected_minutes": round(e.expected_minutes, 1), "basis": e.basis, "sample": e.sample,
                "share": None if e.share is None else round(e.share, 4), "started_last": e.started_last,
                "absence_status": e.absence_status, "absence_basis": e.absence_basis, "fact_rung": e.fact_rung,
                "fact_ids": list(e.fact_ids), "seal": e.seal, "lineup_confirmed": side["confirmed"],
                "history_matches": doc["history_matches"], "start_model_samples": model.samples,
                "start_model_fitted": model.coef is not None, "version": le.VERSION, "model": le.MODEL,
                "input_hash": hashlib.sha256(json.dumps({"at": now.isoformat(), "row": row}, sort_keys=True).encode()).hexdigest(),
                "code_version": code_version})
