"""What an evaluation after the match is made of, read from the database (IA-112, AD-K01). Read only, under a statement timeout.

* the decisions of each selection of the matches (``intel.decisions`` of the layers it follows, by ``decision_version``; and
  decision-v2's own ``intel.decisions_v2`` where the table exists), their settlement (``intel.decision_outcomes``), the score and
  status of the match (``core.fixtures``, ``core.fixture_results``), the official line-up and the minutes of each player
  (``core.fixture_lineups``, ``core.fixture_lineup_players``, ``core.fixture_player_stats``), the estimated starters
  (``intel.lineup_estimates`` where it exists) and the facts the decision cited (``ai.evidence`` by id, with the one question every
  reader of that table asks: research v2's claims only when ``fbi.ai.gates.typed_visible`` says they are part of what the system
  reads).

Nothing here writes, and nothing here is read before a match: the evaluation exists only once the selection is settled.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.gates import typed_visible
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.evaluation.selection import (
    Decided,
    Fact,
    Inputs,
    Match,
    PlayerDay,
    Point,
    Settled,
    standing,
)
from fbi.evaluation.sources import LINEUP_AT_SQL
from fbi.market import closing_reference
from fbi.picks import settlement

LAYERS: Final[tuple[str, ...]] = (DECISION_CORE, DECISION_FAMILIES)
V2_LAYER: Final = "decision-v2"
CORE_MARKETS: Final = frozenset({"1X2", "DC", "OU", "BTTS", "AH"})
"""The markets ``settle-v4`` settles on the regulation score (``fbi.picks.settlement.market_outcome``)."""
TIMEOUT_MS: Final = 60_000
CHUNK: Final = 100

FIXTURES_SQL: Final = """
SELECT f.id FROM core.fixtures f
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
   AND EXISTS (SELECT 1 FROM intel.decisions d WHERE d.fixture_id = f.id AND d.decision_version = ANY(%(layers)s))
 ORDER BY f.kickoff_at, f.id
"""
DECISIONS_SQL: Final = """
SELECT d.id, d.decision_version, d.fixture_id, d.market_key, d.selection, d.line, d.known_at, d.kickoff_at, d.checkpoint, d.state,
       d.p_model::float8 AS p_model, d.p_cal::float8 AS p_cal, d.p_market::float8 AS p_market, d.odds, d.evidence_ids,
       d.reasons, d.context_status
  FROM intel.decisions d
 WHERE d.fixture_id = ANY(%(fixtures)s) AND d.decision_version = ANY(%(layers)s)
"""
OUTCOMES_SQL: Final = """
SELECT o.decision_id, o.settled_at, o.result_status, o.close_p_fair, o.close_minutes_to_ko, o.clv, o.version
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id
 WHERE d.id = ANY(%(ids)s) AND d.decision_version = ANY(%(layers)s)
"""
V2_EXISTS_SQL: Final = "SELECT to_regclass('intel.decisions_v2') IS NOT NULL, to_regclass('intel.lineup_estimates') IS NOT NULL"
V2_SQL: Final = """
SELECT d.id, d.fixture_id, d.market_key, d.selection, d.line, d.known_at, d.kickoff_at, d.checkpoint, d.state,
       d.p_model::float8 AS p_model, d.p_cal::float8 AS p_cal, d.p_market::float8 AS p_market, d.odds, d.codes AS reasons,
       d.context_status
  FROM intel.decisions_v2 d
 WHERE d.fixture_id = ANY(%(fixtures)s)
"""
MATCH_SQL: Final = """
SELECT f.id, f.status_short, r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away, r.ft_goals_home,
       r.ft_goals_away, r.settled_at AS result_at
  FROM core.fixtures f LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.id = ANY(%(fixtures)s)
"""
PLAYERS_SQL: Final = """
SELECT fixture_id, provider_player_id, bool_or(is_starter) AS starter, NULL::int AS minutes, true AS listed
  FROM core.fixture_lineup_players WHERE fixture_id = ANY(%(fixtures)s) AND provider_player_id IS NOT NULL
 GROUP BY fixture_id, provider_player_id
UNION ALL
SELECT fixture_id, provider_player_id, NULL::boolean, max(minutes)::int, false
  FROM core.fixture_player_stats WHERE fixture_id = ANY(%(fixtures)s) AND provider_player_id IS NOT NULL
 GROUP BY fixture_id, provider_player_id
"""
ESTIMATES_SQL: Final = """
WITH last AS (
    SELECT DISTINCT ON (e.fixture_id, e.team_id) e.fixture_id, e.team_id, e.evaluation, e.known_at
      FROM intel.lineup_estimates e WHERE e.fixture_id = ANY(%(fixtures)s) AND e.known_at < e.kickoff_at
     ORDER BY e.fixture_id, e.team_id, e.known_at DESC)
SELECT e.fixture_id, e.team_id, e.provider_player_id, e.p_start::float8 AS p_start
  FROM intel.lineup_estimates e JOIN last l ON l.fixture_id = e.fixture_id AND l.team_id = e.team_id AND l.known_at = e.known_at
"""
EVIDENCE_SQL: Final = """
SELECT e.id, e.kind, e.attributes ->> 'assertion' AS assertion, e.provider_player_id
  FROM ai.evidence e
 WHERE e.id = ANY(%(ids)s) AND (e.subject_type IS NULL OR %(typed)s)
"""
"""The facts a decision cited, by id - with the question every reader of ``ai.evidence`` asks (``typed``: ``gates.typed_visible``)."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _key(r: Mapping[str, Any]) -> tuple[int, str, str, Decimal]:
    return int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"]).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Batch:
    """What one batch of matches gives: the evaluations' inputs and the selections that could not be evaluated yet, by why."""

    inputs: list[Inputs]
    skipped: dict[str, int]


def fixtures(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> list[int]:
    """The matches that kicked off in ``[start, end)`` with a decision of a followed layer."""
    with conn.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        cur.execute(FIXTURES_SQL, {"start": start, "end": end, "layers": list(LAYERS)})
        return [int(r[0]) for r in cur.fetchall()]


def _decided(r: Mapping[str, Any], layer: str, source: str, evidence: Iterable[int] = ()) -> Decided:
    return Decided(layer=layer, source=source, decision_id=int(r["id"]), fixture_id=int(r["fixture_id"]),
                   market_key=str(r["market_key"]), selection=str(r["selection"]), line=_key(r)[3], known_at=r["known_at"],
                   kickoff_at=r["kickoff_at"], checkpoint=str(r["checkpoint"]), state=str(r["state"]), p_model=float(r["p_model"]),
                   p_cal=None if r["p_cal"] is None else float(r["p_cal"]),
                   p_market=None if r["p_market"] is None else float(r["p_market"]),
                   odds=None if r["odds"] is None else Decimal(r["odds"]), evidence_ids=tuple(sorted(int(i) for i in evidence)),
                   reasons=tuple(str(c) for c in (r.get("reasons") or ())), context_status=str(r.get("context_status") or "FULL"))


def rederive(market_key: str, selection: str, line: Decimal, m: Mapping[str, Any]) -> str | None:
    """The result ``settle-v4`` gives on the regulation score, for the core markets; None when it is not final or not derivable."""
    if market_key not in CORE_MARKETS or m.get("status_short") is None:
        return None
    state = settlement.MatchState(str(m["status_short"]), m["reg_goals_home"], m["reg_goals_away"], m["et_goals_home"],
                                  m["et_goals_away"], m["ft_goals_home"], m["ft_goals_away"])
    s = settlement.settle(market_key, selection, line, Decimal(2), Decimal(1), state)
    return s.status.value if s.is_final else None


def players_of(rows: Sequence[Mapping[str, Any]]) -> dict[int, dict[int, PlayerDay]]:
    acc: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        p = acc[int(r["fixture_id"])].setdefault(int(r["provider_player_id"]), {"listed": False, "starter": False, "minutes": None})
        if r["listed"]:
            p["listed"] = True
            p["starter"] = p["starter"] or bool(r["starter"])
        elif r["minutes"] is not None:
            p["minutes"] = int(r["minutes"])
    return {f: {pid: PlayerDay(in_squad=v["listed"] or v["minutes"] is not None, starter=v["starter"], minutes=v["minutes"])
                for pid, v in ps.items()} for f, ps in acc.items()}


def estimate_hits(rows: Sequence[Mapping[str, Any]], players: Mapping[int, PlayerDay]) -> tuple[int, int] | None:
    """(estimated starters who started, estimated starters): the eleven most likely starters of each side's last estimate."""
    by_team: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for r in rows:
        by_team[int(r["team_id"])].append((float(r["p_start"]), int(r["provider_player_id"])))
    if not by_team or not any(p.starter for p in players.values()):
        return None
    chosen = [pid for team in by_team.values() for _, pid in sorted(team, key=lambda t: (-t[0], t[1]))[:11]]
    return sum(1 for pid in chosen if pid in players and players[pid].starter), len(chosen)


def batch(conn: psycopg.Connection[Any], fixture_ids: Sequence[int]) -> Batch:
    """The inputs of every settled selection of these matches, for every followed layer (``LAYERS`` and decision-v2 where it is kept)."""
    ids = sorted(set(fixture_ids))
    skipped: dict[str, int] = defaultdict(int)
    if not ids:
        return Batch([], {})
    with conn.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        cur.execute(V2_EXISTS_SQL)
        has_v2, has_estimates = cur.fetchone() or (False, False)
    p = {"fixtures": ids, "layers": list(LAYERS)}
    decisions = _rows(conn, DECISIONS_SQL, p)
    matches = {int(r["id"]): r for r in _rows(conn, MATCH_SQL, p)}
    lineup_at = {int(r["fixture_id"]): r["first_seen"] for r in _rows(conn, LINEUP_AT_SQL, p)}
    players = players_of(_rows(conn, PLAYERS_SQL, p))
    estimates: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if has_estimates:
        for r in _rows(conn, ESTIMATES_SQL, p):
            estimates[int(r["fixture_id"])].append(r)
    chains: dict[tuple[str, tuple[int, str, str, Decimal]], list[dict[str, Any]]] = defaultdict(list)
    for r in decisions:
        chains[(str(r["decision_version"]), _key(r))].append(r)
    if has_v2:
        for r in _rows(conn, V2_SQL, p):
            chains[(V2_LAYER, _key(r))].append(r)
    tips: dict[tuple[str, tuple[int, str, str, Decimal]], dict[str, Any]] = {}
    for ck, rows in chains.items():
        tip = standing([(r["known_at"], r) for r in rows], rows[0]["kickoff_at"])
        if tip is None:
            skipped["sin_decision_antes_del_saque"] += 1
        else:
            tips[ck] = tip
    v1_ids = [int(t["id"]) for (layer, _), t in tips.items() if layer != V2_LAYER]
    outcomes = {int(r["decision_id"]): r for r in _rows(conn, OUTCOMES_SQL, {"ids": v1_ids, "layers": list(LAYERS)})} if v1_ids else {}
    v2_keys = [k for (layer, k), _ in tips.items() if layer == V2_LAYER]
    closes = closing_reference.closing_probabilities(conn, v2_keys) if v2_keys else {}
    cited = sorted({int(i) for (layer, _), t in tips.items() if layer != V2_LAYER for i in (t.get("evidence_ids") or [])})
    facts = {int(r["id"]): Fact(int(r["id"]), str(r["kind"]), r["assertion"], None if r["provider_player_id"] is None
                                else int(r["provider_player_id"]))
             for r in (_rows(conn, EVIDENCE_SQL, {"ids": cited, "typed": typed_visible(conn)}) if cited else [])}
    out: list[Inputs] = []
    for (layer, key), tip in sorted(tips.items(), key=lambda kv: (kv[0][0], kv[0][1][0], kv[0][1][1], kv[0][1][2], kv[0][1][3])):
        m = matches.get(key[0])
        if m is None:
            skipped["sin_partido"] += 1
            continue
        redo = rederive(key[1], key[2], key[3], m)
        if layer == V2_LAYER:
            close = closes.get(key)
            if redo is None or m["result_at"] is None:
                skipped["sin_liquidar"] += 1
                continue
            settled = Settled(redo, m["result_at"], "settle-v4", settlement.RULE_VERSION,
                              None if close is None else Decimal(repr(close.p_fair)).quantize(Decimal("0.000001")),
                              None if close is None else close.minutes_to_ko, None)
            decided = _decided(tip, layer, "intel.decisions_v2")
        else:
            o = outcomes.get(int(tip["id"]))
            if o is None:
                skipped["sin_liquidar" if tip["odds"] is not None else "sin_cuota"] += 1
                continue
            settled = Settled(str(o["result_status"]), o["settled_at"], "intel.decision_outcomes", o["version"],
                              None if o["close_p_fair"] is None else Decimal(o["close_p_fair"]),
                              None if o["close_minutes_to_ko"] is None else int(o["close_minutes_to_ko"]),
                              None if o["clv"] is None else Decimal(o["clv"]))
            decided = _decided(tip, layer, "intel.decisions", tip.get("evidence_ids") or ())
        at = lineup_at.get(key[0])
        before = None
        if at is not None:
            earlier = [(r["known_at"], r) for r in chains[(layer, key)] if r["known_at"] < at]
            prev = max(earlier, key=lambda t: (t[0], int(t[1]["id"])))[1] if earlier else None
            if prev is not None:
                before = Point(prev["known_at"], str(prev["state"]),
                               float(prev["p_cal"]) if prev["p_cal"] is not None else float(prev["p_model"]))
        ps = players.get(key[0], {})
        match = Match(status=str(m["status_short"]), reg_home=m["reg_goals_home"], reg_away=m["reg_goals_away"], lineup_at=at,
                      players=ps, rederived=redo)
        out.append(Inputs(decided=decided, settled=settled, match=match,
                          facts=tuple(facts[i] for i in decided.evidence_ids if i in facts), before_lineup=before,
                          estimate=estimate_hits(estimates.get(key[0], []), ps)))
    return Batch(out, dict(skipped))
