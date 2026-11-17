"""The evaluation cycle's passes (IA-105..IA-108): read what was known, evaluate with the pure modules, keep every row. In SHADOW.

Two passes, each under its own advisory lock, scheduled by the worker only while ``FBI_EVAL_CYCLE`` is ``shadow``
(``fbi.shadowjobs.eval_cycle``):

``run_pass`` (every few minutes), for the tracked matches of the next 24 hours:
    * the match read again (kick-off, state, venue) against what its newest evaluation knew: a change is an alert (``conditions``);
    * E1 when its window opens: decision-v2 decides (``fbi.decision.shadow.decide_evaluation``, or the E1 moment decision-v2's own pass
      already kept, IA-093), the estimated starters and the goal model's matrix give each selection its dependency (AD-D03), and each
      selection is read (``reevaluate.reading``);
    * E2 for the new facts of the match (``ai.evidence``), each looked at once (``intel.eval_facts``);
    * E4 in its window: the match read again (``fbi.ai.final_reread``) and every selection judged with the last decision and the line-up
      known by then; a selection still waiting for its line-up raises «sin alineación»;
    * the chains of the cycle of states, under the writer ``eval-cycle-v1`` (``fbi.lifecycle.store.extend_rows``).

``run_line_ups`` (every minute): E3 for every match whose official line-up arrived (``core.fixture_lineup_arrivals``, IA-069; the stored
sheet when no arrival was recorded), code only: the official starters (the stored sheet, else the RAW answer the arrival was read from),
the dependencies applied, decision-v2 again when there is still time or the price read again otherwise, and the verdict. Its latency
from the line-up's first sighting is kept (``eval_runs.latency_ms``; AD-D06: p95 under two minutes).

Every evaluation of a match is its own savepoint: one that fails is rolled back, kept as ``fallida`` with the class of its error and the
pass goes on - a failed E3 leaves its selections waiting, never confirmed. Writes only the cycle's tables (revision 0156), decision-v2's
two tables through its own function and the cycle of states through its API. No provider, no model of language.
"""

from __future__ import annotations

import functools
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import final_reread
from fbi.ai.gates import typed_visible
from fbi.decision import book_price, engine, shadow
from fbi.evalcycle import VERSION, alerts, chain, clock, conditions, dependency, reevaluate
from fbi.evalcycle import players as player_inputs
from fbi.evalcycle.dependency import Dependency, Matrix, PlayerDependency
from fbi.evalcycle.reevaluate import Decided, Outcome, Priced, Standing
from fbi.factlinks import store as factlinks
from fbi.forecasting import market_reader
from fbi.forecasting import score_matrix as sm
from fbi.lifecycle import derive
from fbi.lifecycle import store as lifecycle
from fbi.providers.api_football.details import iter_fixture_details
from fbi.storage.payload_store import PayloadStore

LOCK: Final = 0x1A105
LOCK_LINE_UPS: Final = 0x1A106
TIMEOUT_MS: Final = 95_000
AHEAD: Final = clock.E1_FROM
BACK: Final = timedelta(days=2)
"""How long after kick-off a match's chain is still extended (to close it)."""
LINE_UP_AHEAD: Final = timedelta(minutes=90)
MAX_E1: Final = 12
"""Matches given E1 in one pass, nearest kick-off first: each reads 180 days of both teams for the estimated starters."""
GOAL_MODELS: Final = ("dixon_coles", "poisson")
"""The goal model whose stored rows the dependency's matrix is rebuilt from, in order of preference."""
CHECKPOINT: Final = "lineups"
"""The checkpoint the price's age is held to when E3 or E4 reads it again without a decision (decision-v1's own after the line-up)."""

EstimateReader = Callable[[psycopg.Connection[Any], int, datetime], Mapping[str, Any] | None]
"""(conn, fixture, at) -> the estimated starters of the match as of ``at`` with the player engine's history (``estimate_fixture``)."""


# -- reads ------------------------------------------------------------------------------------------------------------------------------

FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group, f.venue_id, f.provider_fixture_id,
       h.provider_team_id AS home_provider, a.provider_team_id AS away_provider
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams h ON h.id = f.home_team_id
  JOIN core.teams a ON a.id = f.away_team_id
 WHERE c.is_tracked AND f.kickoff_at > %(start)s AND f.kickoff_at <= %(end)s
 ORDER BY f.kickoff_at, f.id
"""
RUNS_SQL: Final = """
SELECT id, fixture_id, evaluation, evaluation_version, cause_key, known_at, kickoff_at, conditions, decided
  FROM intel.eval_runs WHERE fixture_id = ANY(%(fixtures)s) AND status <> 'fallida' ORDER BY id
"""
FAILURES_SQL: Final = """
SELECT fixture_id, evaluation, count(*) AS n FROM intel.eval_runs
 WHERE fixture_id = ANY(%(fixtures)s) AND status = 'fallida' GROUP BY 1, 2
"""
MAX_FAILURES: Final = 3
"""An evaluation that failed this many times for a match is not tried again (each failure is kept as ``fallida``)."""
MOMENT_SQL: Final = """
SELECT id FROM intel.decision_v2_moments
 WHERE fixture_id = %(fixture)s AND trigger = %(trigger)s AND config_key = %(config)s AND known_at <= %(at)s
 ORDER BY known_at DESC, id DESC LIMIT 1
"""
DECISIONS_SQL: Final = """
SELECT d.id, d.market_key, d.selection, d.line, d.state, d.reason, d.codes, d.context_status, d.checkpoint, d.known_at, d.kickoff_at,
       d.p_model, d.p_cal, d.odds, d.p_market, d.price_state, d.price_at, d.price_age_minutes,
       COALESCE((d.decision->'prediction'->>'p_push')::float8, 0) AS p_push
  FROM intel.decisions_v2 d WHERE d.moment_id = %(moment)s ORDER BY d.id
"""
VERDICTS_SQL: Final = """
SELECT DISTINCT ON (market_key, selection, line) id, market_key, selection, line, state, reason, p_after, odds_after, evaluation
  FROM intel.eval_verdicts WHERE fixture_id = %(fixture)s ORDER BY market_key, selection, line, id DESC
"""
DEPENDENCIES_SQL: Final = """
SELECT DISTINCT ON (market_key, selection, line) id, market_key, selection, line, market_group, status, waits, p_base, p_matrix, matrix,
       players
  FROM intel.lineup_dependencies WHERE fixture_id = %(fixture)s ORDER BY market_key, selection, line, id DESC
"""
FACTS_SQL: Final = """
SELECT e.id, e.kind, e.provider_player_id, e.retrieved_at
  FROM ai.evidence e
 WHERE e.fixture_id = %(fixture)s AND e.retrieved_at > %(since)s AND e.retrieved_at <= %(at)s
   AND (e.published_at IS NULL OR e.published_at <= %(at)s) AND e.status <> 'OUTDATED' AND (e.subject_type IS NULL OR %(typed)s)
 ORDER BY e.retrieved_at, e.id LIMIT 500
"""
"""The new facts of a match since E1, as the system reads them: research v2's claims only when it is part of what the system reads
(``typed_visible``)."""
SEEN_FACTS_SQL: Final = "SELECT evidence_id FROM intel.eval_facts WHERE fixture_id = %(fixture)s"
ARRIVALS_SQL: Final = """
SELECT DISTINCT ON (a.fixture_id, a.team_side) a.id, a.fixture_id, a.team_side, a.observed_at, a.starters_hash, a.starters, a.payload_hash
  FROM core.fixture_lineup_arrivals a
 WHERE a.fixture_id = ANY(%(fixtures)s) AND a.observed_at <= %(at)s
 ORDER BY a.fixture_id, a.team_side, a.observed_at DESC, a.id DESC
"""
SHEETS_SQL: Final = """
SELECT l.fixture_id, l.team_side, COALESCE(l.first_seen_at, l.fetched_at) AS seen_at,
       COALESCE(array_agg(lp.provider_player_id ORDER BY lp.provider_player_id) FILTER (WHERE lp.is_starter AND lp.provider_player_id > 0),
                '{}') AS starters
  FROM core.fixture_lineups l
  JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE l.fixture_id = ANY(%(fixtures)s) AND l.source = 'api-football' AND l.fetched_at <= %(at)s
 GROUP BY l.fixture_id, l.team_side, l.first_seen_at, l.fetched_at
"""
"""The stored sheets read by the moment: the starters E3 judges with, and the arrival of a side when no arrival row was recorded."""
PAYLOAD_SQL: Final = "SELECT file_path FROM raw.ingestion_payloads WHERE hash = %(hash)s"
CONSENSUS_SQL: Final = """
SELECT m.best_odds::float8 AS odds, m.p_fair::float8 AS p_fair, m.as_of
  FROM market.market_consensus m
 WHERE m.fixture_id = %(fixture)s AND m.market_key = %(market)s AND m.selection = %(selection)s AND m.line = %(line)s
   AND m.devig_method = 'shin' AND m.as_of <= %(at)s
 ORDER BY m.as_of DESC LIMIT 1
"""
VENUE_SQL: Final = "SELECT venue_id FROM core.fixtures WHERE id = %(fixture)s"
LINK_SQL: Final = """
SELECT id, fixture_id, market_key, selection, line, known_at, state, reason, evaluation, evaluation_version
  FROM intel.eval_verdicts WHERE fixture_id = ANY(%(fixtures)s) ORDER BY id
"""

# -- writes -----------------------------------------------------------------------------------------------------------------------------

RUN_SQL: Final = """
INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, trigger_at, finished_at,
    latency_ms, status, decided, decision_moment_id, conditions, lineup, summary, error, version, code_version)
VALUES (%(fixture_id)s, %(evaluation)s, %(evaluation_version)s, %(cause)s, %(cause_key)s, %(known_at)s, %(kickoff_at)s, %(trigger_at)s,
    %(finished_at)s, %(latency_ms)s, %(status)s, %(decided)s, %(decision_moment_id)s, %(conditions)s, %(lineup)s, %(summary)s, %(error)s,
    %(version)s, %(code_version)s)
RETURNING id
"""
FACT_SQL: Final = """
INSERT INTO intel.eval_facts (fixture_id, evidence_id, run_id, action, reason, retrieved_at, known_at)
VALUES (%(fixture_id)s, %(evidence_id)s, %(run_id)s, %(action)s, %(reason)s, %(retrieved_at)s, %(known_at)s)
"""
DEPENDENCY_SQL: Final = """
INSERT INTO intel.lineup_dependencies (run_id, fixture_id, decision_id, market_key, selection, line, market_group, status, waits, p_base,
    p_matrix, matrix, players, evaluation, known_at, kickoff_at, version, model, estimate_version, input_hash, code_version)
VALUES (%(run_id)s, %(fixture_id)s, %(decision_id)s, %(market_key)s, %(selection)s, %(line)s, %(market_group)s, %(status)s, %(waits)s,
    %(p_base)s, %(p_matrix)s, %(matrix)s, %(players)s, %(evaluation)s, %(known_at)s, %(kickoff_at)s, %(version)s, %(model)s,
    %(estimate_version)s, %(input_hash)s, %(code_version)s)
RETURNING id
"""
VERDICT_SQL: Final = """
INSERT INTO intel.eval_verdicts (run_id, previous_id, fixture_id, market_key, selection, line, evaluation, evaluation_version, known_at,
    kickoff_at, verdict, state, reason, cause, decision_id, dependency_id, p_before, p_after, odds_before, odds_after, price_state,
    ev_after, edge_after, lineup, detail, version)
VALUES (%(run_id)s, %(previous_id)s, %(fixture_id)s, %(market_key)s, %(selection)s, %(line)s, %(evaluation)s, %(evaluation_version)s,
    %(known_at)s, %(kickoff_at)s, %(verdict)s, %(state)s, %(reason)s, %(cause)s, %(decision_id)s, %(dependency_id)s, %(p_before)s,
    %(p_after)s, %(odds_before)s, %(odds_after)s, %(price_state)s, %(ev_after)s, %(edge_after)s, %(lineup)s, %(detail)s, %(version)s)
RETURNING id
"""
ALERT_SQL: Final = """
INSERT INTO intel.private_alerts (dedupe_key, kind, fixture_id, market_key, selection, line, cause, before, after, price, run_id,
    verdict_id, decision_id, evaluation, evaluation_version, known_at, kickoff_at, version)
VALUES (%(dedupe_key)s, %(kind)s, %(fixture_id)s, %(market_key)s, %(selection)s, %(line)s, %(cause)s, %(before)s, %(after)s, %(price)s,
    %(run_id)s, %(verdict_id)s, %(decision_id)s, %(evaluation)s, %(evaluation_version)s, %(known_at)s, %(kickoff_at)s, %(version)s)
ON CONFLICT (dedupe_key) DO NOTHING
RETURNING id
"""


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def _q(x: float | None, places: int) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, places)))


Key = tuple[str, str, Decimal]


def key_of(r: Mapping[str, Any]) -> Key:
    return str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"])).quantize(derive.LINE_Q)


# -- the match --------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Match:
    id: int
    kickoff_at: datetime
    status_short: str | None
    status_group: str | None
    venue_id: int | None
    provider_fixture_id: int
    home_provider: int | None
    away_provider: int | None


@dataclass(frozen=True, slots=True)
class Run:
    id: int
    evaluation: str
    version: int
    cause_key: str
    known_at: datetime
    kickoff_at: datetime
    conditions: Mapping[str, Any] | None


def _match(r: Mapping[str, Any]) -> Match:
    return Match(int(r["id"]), r["kickoff_at"], r["status_short"], r["status_group"],
                 None if r["venue_id"] is None else int(r["venue_id"]), int(r["provider_fixture_id"]),
                 None if r["home_provider"] is None else int(r["home_provider"]),
                 None if r["away_provider"] is None else int(r["away_provider"]))


def _runs(conn: psycopg.Connection[Any], fixtures: Sequence[int]) -> dict[int, list[Run]]:
    out: dict[int, list[Run]] = defaultdict(list)
    if fixtures:
        for r in _fetch(conn, RUNS_SQL, {"fixtures": list(fixtures)}):
            out[int(r["fixture_id"])].append(Run(int(r["id"]), str(r["evaluation"]), int(r["evaluation_version"]), str(r["cause_key"]),
                                                 r["known_at"], r["kickoff_at"], r["conditions"]))
    return out


def _failures(conn: psycopg.Connection[Any], fixtures: Sequence[int]) -> dict[tuple[int, str], int]:
    if not fixtures:
        return {}
    return {(int(r["fixture_id"]), str(r["evaluation"])): int(r["n"]) for r in _fetch(conn, FAILURES_SQL, {"fixtures": list(fixtures)})}


def snapshot(m: Match) -> dict[str, Any]:
    """What a run keeps of the match as it read it (``eval_runs.conditions``): the next run's changes are held against it."""
    return {"kickoff_at": m.kickoff_at.isoformat(), "status": m.status_short, "venue_id": m.venue_id}


def known_of(run: Run) -> conditions.Known:
    c = run.conditions or {}
    venue = c.get("venue_id")
    return conditions.Known(run.kickoff_at, c.get("status"), None if venue is None else int(venue))


# -- reports ----------------------------------------------------------------------------------------------------------------------------

@dataclass
class Report:
    runs: Counter[str] = field(default_factory=Counter)
    failed: Counter[str] = field(default_factory=Counter)
    verdicts: Counter[str] = field(default_factory=Counter)
    alerts: Counter[str] = field(default_factory=Counter)
    dependencies: Counter[str] = field(default_factory=Counter)
    facts: Counter[str] = field(default_factory=Counter)
    sources: Counter[str] = field(default_factory=Counter)
    latency_ms: list[int] = field(default_factory=list)
    lifecycle: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        lat = sorted(self.latency_ms)
        return {"runs": dict(sorted(self.runs.items())), "failed": dict(sorted(self.failed.items())),
                "verdicts": dict(sorted(self.verdicts.items())), "alerts": dict(sorted(self.alerts.items())),
                "dependencies": dict(sorted(self.dependencies.items())), "facts": dict(sorted(self.facts.items())),
                "sources": dict(sorted(self.sources.items())),
                "e3_latency_ms": {"n": len(lat), "max": lat[-1] if lat else None,
                                  "p95": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None},
                "lifecycle": self.lifecycle, "errors": self.errors[:20]}


@dataclass
class Context:
    """What one pass hands every evaluation."""

    conn: psycopg.Connection[Any]
    now: datetime
    store: PayloadStore | None
    config: shadow.Config
    code_version: str | None
    estimates: EstimateReader | None
    rep: Report
    clock_ms: Callable[[], float] = field(default=lambda: time.monotonic() * 1000)
    answers: dict[int, book_price.Answer] = field(default_factory=dict)
    """The odds book's answer in force of each match, read once per pass (``reread_price``)."""


# -- decisions --------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Kept:
    """A decision of decision-v2 as the cycle reads it."""

    id: int
    key: Key
    state: str
    reason: str
    p: float | None
    odds: float | None
    p_market: float | None
    price_state: str | None
    price_at: datetime | None
    price_age_minutes: float | None
    p_push: float

    def decided(self) -> Decided:
        return Decided(self.id, self.state, self.reason, self.p, self.odds, self.p_market, self.price_state, self.p_push)


def decisions_of(conn: psycopg.Connection[Any], moment_id: int | None) -> dict[Key, Kept]:
    """The decisions of one moment, one per selection (the newest row when two models decided it), mapped to the cycle's words
    (``derive.map_decision`` over decision-v2's states in decision-v1's words, ``shadow.V1_WORDS``)."""
    if moment_id is None:
        return {}
    out: dict[Key, Kept] = {}
    for r in _fetch(conn, DECISIONS_SQL, {"moment": moment_id}):
        d = derive.Decision(int(r["id"]), shadow.LAYER, r["known_at"], str(r["checkpoint"]), shadow.V1_WORDS[str(r["state"])],
                            tuple(str(c) for c in r["codes"] or ()), str(r["context_status"]), r["kickoff_at"])
        state, reason = derive.map_decision(d)
        p = _f(r["p_cal"]) if r["p_cal"] is not None else _f(r["p_model"])
        out[key_of(r)] = Kept(int(r["id"]), key_of(r), state, reason, p, _f(r["odds"]), _f(r["p_market"]), r["price_state"],
                              r["price_at"], _f(r["price_age_minutes"]), float(r["p_push"] or 0.0))
    return out


def _moment(ctx: Context, m: Match, evaluation: str, version: int) -> int | None:
    """decision-v2 at this evaluation: E1 and E4 adopt the moment decision-v2's own pass already kept in the window (IA-093), the rest
    decide now. None when it can no longer decide (under decision-v1's floor)."""
    if not clock.decides(m.kickoff_at, ctx.now):
        return None
    if evaluation in ("E1", "E4"):
        since = m.kickoff_at - (clock.E1_FROM if evaluation == "E1" else clock.E4_FROM)
        got = _fetch(ctx.conn, MOMENT_SQL, {"fixture": m.id, "trigger": evaluation, "config": ctx.config.key, "at": ctx.now})
        if got:
            mid = int(got[0]["id"])
            row = ctx.conn.execute("SELECT known_at FROM intel.decision_v2_moments WHERE id = %s", (mid,)).fetchone()
            if row is not None and row[0] >= since:
                return mid
    rep = shadow.decide_evaluation(ctx.conn, evaluation=evaluation, at=ctx.now, kickoffs={m.id: m.kickoff_at}, versions={m.id: version},
                                   store=ctx.store, config=ctx.config, code_version=ctx.code_version)
    ctx.rep.errors.extend(f"{m.id}/{evaluation}: {e}"[:300] for e in rep.errors)  # a decision with a later input is not written
    return rep.kept.get(m.id)


def reread_price(ctx: Context, m: Match, key: Key) -> Priced:
    """The price of one selection read again at ``now`` (no decision: under decision-v2's floor), with its age held to the ruleset's
    rule at the ``lineups`` checkpoint."""
    rule = engine.RULESETS[ctx.config.rules].age_for(ctx.config.price)
    minutes = (m.kickoff_at - ctx.now).total_seconds() / 60
    odds = p_fair = None
    at: datetime | None = None
    if ctx.config.price == engine.BOOK:
        if ctx.store is not None:
            if m.id not in ctx.answers:
                ctx.answers[m.id] = book_price.read(ctx.conn, ctx.store, [m.id]).answer_at(m.id, ctx.now)
            answer = ctx.answers[m.id]
            quoted = answer.price((m.id, key[0], key[1], key[2]))
            if quoted is not None:
                odds, p_fair, at = quoted.best_odds, quoted.p_fair, answer.checked_at
    else:
        got = _fetch(ctx.conn, CONSENSUS_SQL, {"fixture": m.id, "market": key[0], "selection": key[1], "line": key[2], "at": ctx.now})
        if got:
            odds, p_fair, at = _f(got[0]["odds"]), _f(got[0]["p_fair"]), got[0]["as_of"]
    age = None if at is None else ctx.now - at
    check = rule.check(priced=odds is not None and p_fair is not None, age=age, minutes_to_kickoff=minutes, checkpoint=CHECKPOINT)
    return Priced(odds, p_fair, check.state, None if age is None else age.total_seconds() / 60)


# -- the dependencies (E1) --------------------------------------------------------------------------------------------------------------

def matrix_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> Matrix | None:
    """The goal model's parameters for the match as of ``at``: its seven stored rows inverted (``score_matrix.invert``)."""
    numbers = market_reader.read_numbers(conn, [fixture_id], at).get(fixture_id, {})
    for model in GOAL_MODELS:
        rows = numbers.get(model)
        if not rows:
            continue
        inv = sm.invert({k: v.p for k, v in rows.items()}, model)
        if inv is not None:
            return Matrix(inv.params.lam_home, inv.params.lam_away, inv.params.rho, model, inv.residual)
    return None


def _dependency_of(r: Mapping[str, Any]) -> Dependency:
    mx = r["matrix"]
    matrix = None if not mx else Matrix(float(mx["lam_home"]), float(mx["lam_away"]), _f(mx.get("rho")), str(mx["model"]),
                                        float(mx.get("residual") or 0.0))
    return Dependency(key_of(r), str(r["market_group"]), str(r["status"]), bool(r["waits"]), _f(r["p_base"]), _f(r["p_matrix"]), matrix,
                      tuple(PlayerDependency.from_json(p) for p in r["players"] or []))


def dependencies_now(conn: psycopg.Connection[Any], fixture_id: int) -> dict[Key, tuple[int, Dependency]]:
    return {key_of(r): (int(r["id"]), _dependency_of(r)) for r in _fetch(conn, DEPENDENCIES_SQL, {"fixture": fixture_id})}


# -- the line-up (E3) -------------------------------------------------------------------------------------------------------------------

def arrivals_of(conn: psycopg.Connection[Any], fixtures: Sequence[int], at: datetime) -> dict[int, dict[str, clock.Arrival]]:
    """The newest line-up of each side by ``at``: the arrival rows (IA-069), else the stored sheet (its first sighting, or its fetch)."""
    out: dict[int, dict[str, clock.Arrival]] = defaultdict(dict)
    if not fixtures:
        return out
    for r in _fetch(conn, ARRIVALS_SQL, {"fixtures": list(fixtures), "at": at}):
        out[int(r["fixture_id"])][str(r["team_side"])] = clock.Arrival(str(r["team_side"]), r["observed_at"], str(r["starters_hash"]),
                                                                       int(r["starters"]), int(r["id"]), str(r["payload_hash"]))
    for r in _fetch(conn, SHEETS_SQL, {"fixtures": list(fixtures), "at": at}):
        fid, side = int(r["fixture_id"]), str(r["team_side"])
        if side in out[fid] or r["seen_at"] is None or r["seen_at"] > at:
            continue
        xi = [int(p) for p in r["starters"] or []]
        out[fid][side] = clock.Arrival(side, r["seen_at"], "sheet:" + ",".join(map(str, xi)), len(xi))
    return out


def starters_of(ctx: Context, m: Match, due: clock.LineUpDue) -> tuple[dict[str, frozenset[int]], dict[str, str]]:
    """The official starters of each side E3 reads, and where from: the stored sheet, else the RAW answer the arrival was read from."""
    sheets = {str(r["team_side"]): frozenset(int(p) for p in r["starters"] or [])
              for r in _fetch(ctx.conn, SHEETS_SQL, {"fixtures": [m.id], "at": ctx.now})}
    starters: dict[str, frozenset[int]] = {}
    source: dict[str, str] = {}
    for a in due.arrivals:
        xi = sheets.get(a.side)
        if xi is not None and len(xi) >= clock.STARTERS and (a.payload_hash is None or len(xi) == a.starters):
            starters[a.side], source[a.side] = xi, "sheet"
            continue
        raw = _from_raw(ctx, m, a)
        if raw is not None:
            starters[a.side], source[a.side] = raw, "raw"
        elif xi is not None:
            starters[a.side], source[a.side] = xi, "sheet"
    return starters, source


def _from_raw(ctx: Context, m: Match, a: clock.Arrival) -> frozenset[int] | None:
    if ctx.store is None or a.payload_hash is None:
        return None
    got = _fetch(ctx.conn, PAYLOAD_SQL, {"hash": a.payload_hash})
    if not got:
        return None
    try:
        body = ctx.store.load(str(got[0]["file_path"])).get("body")
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(body, dict):
        return None
    team = m.home_provider if a.side == "home" else m.away_provider
    for d in iter_fixture_details(body):
        if d.provider_fixture_id != m.provider_fixture_id:
            continue
        for lu in d.lineups:
            if lu.provider_team_id == team:
                return frozenset(p.provider_player_id for p in lu.players if p.is_starter)
    return None


# -- writing one evaluation -------------------------------------------------------------------------------------------------------------

def _version(runs: Sequence[Run], evaluation: str) -> int:
    return 1 + sum(1 for r in runs if r.evaluation == evaluation)


def _write_run(ctx: Context, m: Match, *, evaluation: str, version: int, cause: str, cause_key: str, trigger_at: datetime | None,
               started_ms: float, decided: bool, moment_id: int | None, conditions_doc: Mapping[str, Any] | None,
               lineup: Mapping[str, Any] | None, summary: Mapping[str, Any], status: str = "completa", error: str | None = None) -> int:
    finished = ctx.now + timedelta(milliseconds=max(0.0, ctx.clock_ms() - started_ms))
    latency = None if trigger_at is None else max(0, int((finished - trigger_at).total_seconds() * 1000))
    got = ctx.conn.execute(RUN_SQL, {
        "fixture_id": m.id, "evaluation": evaluation, "evaluation_version": version, "cause": cause, "cause_key": cause_key,
        "known_at": ctx.now, "kickoff_at": m.kickoff_at, "trigger_at": trigger_at, "finished_at": finished, "latency_ms": latency,
        "status": status, "decided": decided, "decision_moment_id": moment_id,
        "conditions": Jsonb(dict(conditions_doc)) if conditions_doc is not None else None,
        "lineup": Jsonb(dict(lineup)) if lineup is not None else None, "summary": Jsonb(dict(summary)), "error": error,
        "version": VERSION, "code_version": ctx.code_version}).fetchone()
    assert got is not None
    if evaluation == "E3" and latency is not None and status != "fallida":
        ctx.rep.latency_ms.append(latency)
    return int(got[0])


def _write_verdict(ctx: Context, m: Match, run_id: int, key: Key, *, evaluation: str, version: int, previous_id: int | None,
                   verdict: str, state: str, reason: str, cause: str, decision_id: int | None, dependency_id: int | None,
                   o: Outcome | None, p: float | None = None, odds: float | None = None, price_state: str | None = None,
                   detail: Mapping[str, Any] | None = None) -> int:
    got = ctx.conn.execute(VERDICT_SQL, {
        "run_id": run_id, "previous_id": previous_id, "fixture_id": m.id, "market_key": key[0], "selection": key[1], "line": key[2],
        "evaluation": evaluation, "evaluation_version": version, "known_at": ctx.now, "kickoff_at": m.kickoff_at, "verdict": verdict,
        "state": state, "reason": reason, "cause": cause, "decision_id": decision_id, "dependency_id": dependency_id,
        "p_before": _q(o.p_before if o else None, 6), "p_after": _q(o.p_after if o else p, 6),
        "odds_before": _q(o.odds_before if o else None, 4), "odds_after": _q(o.odds_after if o else odds, 4),
        "price_state": o.price_state if o else price_state, "ev_after": _q(o.ev_after if o else None, 6),
        "edge_after": _q(o.edge_after if o else None, 6), "lineup": Jsonb(dict(o.lineup)) if o and o.lineup else None,
        "detail": Jsonb(dict(detail or {})), "version": reevaluate.VERSION}).fetchone()
    assert got is not None
    ctx.rep.verdicts[f"{evaluation}:{verdict}"] += 1
    return int(got[0])


def _write_alert(ctx: Context, m: Match, a: alerts.Alert, *, run_id: int, verdict_id: int | None, evaluation: str, version: int) -> None:
    got = ctx.conn.execute(ALERT_SQL, {
        "dedupe_key": a.dedupe_key, "kind": a.kind, "fixture_id": m.id, "market_key": None if a.key is None else a.key[0],
        "selection": None if a.key is None else a.key[1], "line": None if a.key is None else a.key[2], "cause": a.cause,
        "before": Jsonb(dict(a.before)), "after": Jsonb(dict(a.after)), "price": None if a.price is None else Jsonb(dict(a.price)),
        "run_id": run_id, "verdict_id": verdict_id, "decision_id": a.decision_id, "evaluation": evaluation,
        "evaluation_version": version, "known_at": ctx.now, "kickoff_at": m.kickoff_at, "version": alerts.VERSION}).fetchone()
    if got is not None:
        ctx.rep.alerts[a.kind] += 1


def _write_sources(ctx: Context, m: Match, run_id: int, *, evaluation: str, version: int) -> None:
    """The facts this evaluation looked at, linked or refused by ``link-v1`` (AD-G08, C-07), written now - in the evaluation's own
    transaction, after its verdicts: the database refuses them at any other moment (revision 0160)."""
    got = factlinks.record(ctx.conn, run_id=run_id, fixture_id=m.id, evaluation=evaluation, evaluation_version=version,
                           known_at=ctx.now, typed=typed_visible(ctx.conn))
    if got is None:
        ctx.rep.sources["sin_tabla"] += 1
        return
    ctx.rep.sources["lists"] += 1
    ctx.rep.sources["linked"] += got.linked
    ctx.rep.sources["refused"] += got.candidates - got.linked


def standings_of(conn: psycopg.Connection[Any], fixture_id: int) -> dict[Key, tuple[int, Standing]]:
    return {key_of(r): (int(r["id"]), Standing(str(r["state"]), str(r["reason"]), _f(r["p_after"]), _f(r["odds_after"]), int(r["id"])))
            for r in _fetch(conn, VERDICTS_SQL, {"fixture": fixture_id})}


def _failed(ctx: Context, m: Match, *, evaluation: str, version: int, cause: str, cause_key: str, trigger_at: datetime | None,
            started_ms: float, exc: BaseException, lineup: Mapping[str, Any] | None = None) -> None:
    """A failed evaluation is kept as ``fallida`` (the class of its error, never its message) in a savepoint of its own."""
    ctx.rep.failed[evaluation] += 1
    ctx.rep.errors.append(f"{m.id}/{evaluation}: {type(exc).__name__}: {exc}"[:300])
    try:
        with ctx.conn.transaction():
            _write_run(ctx, m, evaluation=evaluation, version=version, cause=cause, cause_key=cause_key, trigger_at=trigger_at,
                       started_ms=started_ms, decided=False, moment_id=None, conditions_doc=snapshot(m),
                       lineup=lineup if lineup is not None else ({"sides": []} if evaluation == "E3" else None), summary={},
                       status="fallida", error=type(exc).__name__[:80])
    except psycopg.Error as again:
        ctx.rep.errors.append(f"{m.id}/{evaluation}: not kept: {type(again).__name__}"[:300])


# -- E1 ---------------------------------------------------------------------------------------------------------------------------------

def e1(ctx: Context, m: Match) -> None:
    started = ctx.clock_ms()
    moment = _moment(ctx, m, "E1", 1)
    kept = decisions_of(ctx.conn, moment)
    doc = None
    if ctx.estimates is not None and kept:
        doc = ctx.estimates(ctx.conn, m.id, ctx.now)
    inputs = player_inputs.inputs(doc, at=ctx.now) if doc is not None else []
    matrix = matrix_of(ctx.conn, m.id, ctx.now) if kept else None
    keys = sorted(kept)
    deps = dependency.dependencies([(k, kept[k].p) for k in keys], matrix, inputs)
    summary = {"decisions": len(kept), "estimated_players": len(inputs), "matrix": None if matrix is None else matrix.model}
    run_id = _write_run(ctx, m, evaluation="E1", version=1, cause="ventana", cause_key="ventana", trigger_at=None, started_ms=started,
                        decided=moment is not None, moment_id=moment, conditions_doc=snapshot(m), lineup=None,
                        summary=summary, status="completa" if kept else "sin_candidatos")
    ctx.rep.runs["E1"] += 1
    previous = standings_of(ctx.conn, m.id)
    for k, dep in zip(keys, deps, strict=True):
        d = kept[k]
        dep_id = _write_dependency(ctx, m, run_id, d.id, dep, inputs)
        rd = reevaluate.reading(d.state, d.reason, dep)
        _write_verdict(ctx, m, run_id, k, evaluation="E1", version=1, previous_id=previous.get(k, (None,))[0], verdict="lectura",
                       state=rd.state, reason=rd.reason, cause=rd.cause, decision_id=d.id, dependency_id=dep_id, o=None, p=d.p,
                       odds=d.odds, price_state=d.price_state, detail={"decision_state": d.state, "decision_reason": d.reason})
    _write_sources(ctx, m, run_id, evaluation="E1", version=1)


def _write_dependency(ctx: Context, m: Match, run_id: int, decision_id: int, dep: Dependency, inputs: Sequence[dependency.PlayerInput]
                      ) -> int:
    got = ctx.conn.execute(DEPENDENCY_SQL, {
        "run_id": run_id, "fixture_id": m.id, "decision_id": decision_id, "market_key": dep.key[0], "selection": dep.key[1],
        "line": dep.key[2], "market_group": dep.group, "status": dep.status, "waits": dep.waits, "p_base": _q(dep.p_base, 6),
        "p_matrix": _q(dep.p_matrix, 6), "matrix": None if dep.matrix is None else Jsonb(dep.matrix.as_json()),
        "players": Jsonb(dep.players_json()), "evaluation": "E1", "known_at": ctx.now, "kickoff_at": m.kickoff_at,
        "version": dependency.VERSION, "model": player_inputs.MODEL, "estimate_version": player_inputs.ESTIMATE_VERSION,
        "input_hash": dependency.input_hash(dep.key, dep.p_base, dep.matrix, inputs), "code_version": ctx.code_version}).fetchone()
    assert got is not None
    ctx.rep.dependencies[f"{dep.group}:{dep.status}"] += 1
    return int(got[0])


# -- E2 ---------------------------------------------------------------------------------------------------------------------------------

def e2(ctx: Context, m: Match, runs: Sequence[Run], calls: Sequence[clock.FactCall]) -> None:
    started = ctx.clock_ms()
    version = _version(runs, "E2")
    recalc = any(c.action == clock.RECALCULATE for c in calls)
    moment = _moment(ctx, m, "E2", version) if recalc else None
    kept = decisions_of(ctx.conn, moment)
    deps = dependencies_now(ctx.conn, m.id)
    summary = {"facts": len(calls), "recalculated": recalc, "decisions": len(kept)}
    run_id = _write_run(ctx, m, evaluation="E2", version=version, cause="hecho_nuevo", cause_key=clock.facts_key(calls),
                        trigger_at=max(c.fact.retrieved_at for c in calls), started_ms=started, decided=moment is not None,
                        moment_id=moment, conditions_doc=snapshot(m), lineup=None, summary=summary)
    ctx.rep.runs["E2"] += 1
    for c in calls:
        ctx.conn.execute(FACT_SQL, {"fixture_id": m.id, "evidence_id": c.fact.evidence_id, "run_id": run_id, "action": c.action,
                                    "reason": c.reason, "retrieved_at": c.fact.retrieved_at, "known_at": ctx.now})
        ctx.rep.facts[c.action] += 1
    previous = standings_of(ctx.conn, m.id)
    for k in sorted(kept):
        d = kept[k]
        dep_id, dep = deps.get(k, (None, None))
        prev_id, st = previous.get(k, (None, None))
        rd = reevaluate.reread(st, d.state, d.reason, dep)
        vid = _write_verdict(ctx, m, run_id, k, evaluation="E2", version=version, previous_id=prev_id, verdict="lectura", state=rd.state,
                             reason=rd.reason, cause=rd.cause, decision_id=d.id, dependency_id=dep_id, o=None, p=d.p, odds=d.odds,
                             price_state=d.price_state, detail={"decision_state": d.state, "decision_reason": d.reason})
        if st is not None and rd.cause == "decision_en_contra":
            o = Outcome("retirada", rd.state, rd.reason, rd.cause, st.p, d.p, st.odds, d.odds, d.price_state, None, None)
            a = alerts.withdrawn(m.id, k, st, o, decision_id=d.id, price_at=d.price_at, age_minutes=d.price_age_minutes)
            if a is not None:
                _write_alert(ctx, m, a, run_id=run_id, verdict_id=vid, evaluation="E2", version=version)
    _write_sources(ctx, m, run_id, evaluation="E2", version=version)


# -- E3 and E4 --------------------------------------------------------------------------------------------------------------------------

def _judge_all(ctx: Context, m: Match, run_id: int, *, evaluation: str, version: int, kept: Mapping[Key, Kept],
               starters: Mapping[str, frozenset[int]], stops: str | None = None) -> list[tuple[Key, Standing, Outcome, int]]:
    """Every selection the cycle holds (and every one decided now) judged: the verdicts written, the withdrawals alerted."""
    standing = standings_of(ctx.conn, m.id)
    deps = dependencies_now(ctx.conn, m.id)
    out: list[tuple[Key, Standing, Outcome, int]] = []
    for k in sorted(set(standing) | set(kept)):
        prev_id, st = standing.get(k, (None, Standing("detectado", "candidato_nuevo", None, None)))
        dep_id, dep = deps.get(k, (None, None))
        d = kept.get(k)
        if stops is not None:
            o = _stopped(st, stops)
        else:
            priced = None if d is not None else reread_price(ctx, m, k)
            o = reevaluate.reassess(st, dep, starters, None if d is None else d.decided(), priced)
        vid = _write_verdict(ctx, m, run_id, k, evaluation=evaluation, version=version, previous_id=prev_id, verdict=o.verdict,
                             state=o.state, reason=o.reason, cause=o.cause, decision_id=None if d is None else d.id,
                             dependency_id=dep_id, o=o)
        a = alerts.withdrawn(m.id, k, st, o, decision_id=None if d is None else d.id, price_at=None if d is None else d.price_at,
                             age_minutes=None if d is None else d.price_age_minutes)
        if a is not None:
            _write_alert(ctx, m, a, run_id=run_id, verdict_id=vid, evaluation=evaluation, version=version)
        out.append((k, st, o, vid))
    return out


def _stopped(st: Standing, cause: str) -> Outcome:
    if st.state in reevaluate.WAITING:
        return Outcome("retirada", "retirada", "partido_no_jugado", cause, st.p, st.p, st.odds, st.odds, None, None, None)
    return Outcome("sigue_igual", st.state, st.reason, cause, st.p, st.p, st.odds, st.odds, None, None, None)


def e3(ctx: Context, m: Match, runs: Sequence[Run], due: clock.LineUpDue) -> None:
    started = ctx.clock_ms()
    version = _version(runs, "E3")
    starters, source = starters_of(ctx, m, due)
    lineup = {"key": due.key, "sides": sorted(starters), "source": source, "starters": {s: len(x) for s, x in starters.items()},
              "first_seen_at": due.trigger_at.isoformat(), "arrivals": [a.arrival_id for a in due.arrivals if a.arrival_id is not None]}
    if not starters:
        raise LookupError("the official line-up was announced but its starters could not be read")
    moment = _moment(ctx, m, "E3", version)
    kept = decisions_of(ctx.conn, moment)
    with ctx.conn.transaction():
        run_id = _write_run(ctx, m, evaluation="E3", version=version, cause=due.cause, cause_key=due.key, trigger_at=due.trigger_at,
                            started_ms=started, decided=moment is not None, moment_id=moment, conditions_doc=snapshot(m), lineup=lineup,
                            summary={"decisions": len(kept), "sides": sorted(starters)})
        _judge_all(ctx, m, run_id, evaluation="E3", version=version, kept=kept, starters=starters)
        _write_sources(ctx, m, run_id, evaluation="E3", version=version)
    ctx.rep.runs["E3"] += 1


def e4(ctx: Context, m: Match, runs: Sequence[Run], check: conditions.Check) -> None:
    started = ctx.clock_ms()
    stops = conditions.CAUSE_OF.get(check.verdict.reason or "") if check.stops else None
    moment = None if stops is not None else _moment(ctx, m, "E4", 1)
    kept = decisions_of(ctx.conn, moment)
    arrivals = arrivals_of(ctx.conn, [m.id], ctx.now).get(m.id, {})
    due = clock.plan_line_up(arrivals, (), now=ctx.now, kickoff_at=m.kickoff_at)
    starters: dict[str, frozenset[int]] = {}
    if due is not None:
        starters, _ = starters_of(ctx, m, due)
    run_id = _write_run(ctx, m, evaluation="E4", version=1, cause="ventana", cause_key="ventana", trigger_at=None, started_ms=started,
                        decided=moment is not None, moment_id=moment, conditions_doc={**snapshot(m), "reread": check.record()},
                        lineup={"sides": sorted(starters)}, summary={"decisions": len(kept), "stops": stops})
    ctx.rep.runs["E4"] += 1
    judged = _judge_all(ctx, m, run_id, evaluation="E4", version=1, kept=kept, starters=starters, stops=stops)
    minutes = (m.kickoff_at - ctx.now).total_seconds() / 60
    for k, _st, o, vid in judged:
        if o.verdict == "pendiente" or (o.state == reevaluate.PENDING and stops is None):
            missing = [s for s in clock.SIDES if s not in starters]
            if missing:
                _write_alert(ctx, m, alerts.no_line_up(m.id, k, minutes_to_kickoff=minutes, sides_missing=missing), run_id=run_id,
                             verdict_id=vid, evaluation="E4", version=1)
    for c in check.changes:
        _write_alert(ctx, m, alerts.changed(m.id, c), run_id=run_id, verdict_id=None, evaluation="E4", version=1)
    _write_sources(ctx, m, run_id, evaluation="E4", version=1)


# -- the passes -------------------------------------------------------------------------------------------------------------------------

def _lock(conn: psycopg.Connection[Any], key: int) -> bool:
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()
    return bool(got and got[0])


def _tables_exist(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT to_regclass('intel.eval_runs') IS NOT NULL AND to_regclass('intel.decisions_v2') IS NOT NULL").fetchone()
    return bool(row and row[0])


def _guarded(ctx: Context, m: Match, evaluation: str, fn: Callable[[], None], *, version: int, cause: str, cause_key: str,
             trigger_at: datetime | None = None) -> None:
    started = ctx.clock_ms()
    try:
        with ctx.conn.transaction():
            fn()
    except (psycopg.Error, ValueError, KeyError, LookupError, RuntimeError, ArithmeticError) as exc:
        _failed(ctx, m, evaluation=evaluation, version=version, cause=cause, cause_key=cause_key, trigger_at=trigger_at,
                started_ms=started, exc=exc)


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, store: PayloadStore | None, estimates: EstimateReader | None,
             config: shadow.Config = shadow.CONFIG, code_version: str | None = None, commit: bool = True, link: bool = True,
             max_e1: int = MAX_E1) -> Report:
    """One main pass (changes, E1, E2, E4 and the chains). ``commit``: one transaction per evaluation (without it, a savepoint inside the
    caller's transaction)."""
    rep = Report()
    if not _tables_exist(conn):
        raise RuntimeError("intel.eval_runs does not exist: apply revision 0156 first")
    if not _lock(conn, LOCK):
        rep.errors.append("another pass holds the lock")
        return rep
    ctx = Context(conn, now, store, config, code_version, estimates, rep)
    try:
        if commit:
            conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        matches = [_match(r) for r in _fetch(conn, FIXTURES_SQL, {"start": now - BACK, "end": now + AHEAD})]
        runs = _runs(conn, [x.id for x in matches])
        failures = _failures(conn, [x.id for x in matches])
        if commit:
            conn.commit()
        e1_left = max_e1
        for m in matches:
            if m.kickoff_at <= now or ((m.status_group or "scheduled") != "scheduled" and not runs.get(m.id)):
                continue
            mine = runs.get(m.id, [])
            _changes(ctx, m, mine)
            due = clock.window(m.kickoff_at, now)
            has = {r.evaluation for r in mine} | {ev for (f, ev), n in failures.items() if f == m.id and n >= MAX_FAILURES}
            if due == "E1" and "E1" not in has and e1_left > 0:
                e1_left -= 1
                _guarded(ctx, m, "E1", functools.partial(e1, ctx, m), version=1, cause="ventana", cause_key="ventana")
            elif "E1" in has:
                _facts(ctx, m, mine)
            if due == "E4" and "E4" not in has:
                _e4_due(ctx, m, mine)
            if commit:
                conn.commit()
        if link:
            try:
                with conn.transaction():
                    rep.lifecycle = link_lifecycle(conn, now=now).as_json()
            except psycopg.Error as exc:
                rep.errors.append(f"lifecycle: {type(exc).__name__}: {exc}"[:300])
            if commit:
                conn.commit()
    finally:
        if commit:
            conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        if commit:
            conn.commit()
    return rep


def _changes(ctx: Context, m: Match, runs: Sequence[Run]) -> None:
    """The match read again against its newest evaluation: each change is an alert (attached to that evaluation)."""
    if not runs:
        return
    last = runs[-1]
    reading = final_reread.read(ctx.conn, m.id, at=ctx.now)
    check = conditions.check(known_of(last), reading, m.venue_id, at=ctx.now)
    if not check.changes:
        return
    with ctx.conn.transaction():
        for c in check.changes:
            _write_alert(ctx, m, alerts.changed(m.id, c), run_id=last.id, verdict_id=None, evaluation=last.evaluation,
                         version=last.version)


def _facts(ctx: Context, m: Match, runs: Sequence[Run]) -> None:
    first = next(r for r in runs if r.evaluation == "E1")
    if not clock.in_facts_window(m.kickoff_at, ctx.now, first.known_at):
        return
    seen = [int(r["evidence_id"]) for r in _fetch(ctx.conn, SEEN_FACTS_SQL, {"fixture": m.id})]
    facts = [clock.Fact(int(r["id"]), r["kind"], None if r["provider_player_id"] is None else int(r["provider_player_id"]),
                        r["retrieved_at"]) for r in _fetch(ctx.conn, FACTS_SQL, {"fixture": m.id, "since": first.known_at, "at": ctx.now,
                                                                                    "typed": typed_visible(ctx.conn)})]
    dependents = frozenset(pid for _, d in dependencies_now(ctx.conn, m.id).values() for pid in d.dependents)
    calls = clock.plan_facts(facts, seen, dependents, e1_at=first.known_at, now=ctx.now, kickoff_at=m.kickoff_at)
    if calls:
        _guarded(ctx, m, "E2", lambda: e2(ctx, m, runs, calls), version=_version(runs, "E2"), cause="hecho_nuevo",
                 cause_key=clock.facts_key(calls), trigger_at=max(c.fact.retrieved_at for c in calls))


def _e4_due(ctx: Context, m: Match, runs: Sequence[Run]) -> None:
    last = runs[-1] if runs else None
    known = known_of(last) if last is not None else conditions.Known(m.kickoff_at, m.status_short, m.venue_id)
    reading = final_reread.read(ctx.conn, m.id, at=ctx.now)
    check = conditions.check(known, reading, m.venue_id, at=ctx.now)
    _guarded(ctx, m, "E4", lambda: e4(ctx, m, runs, check), version=1, cause="ventana", cause_key="ventana")


def run_line_ups(conn: psycopg.Connection[Any], *, now: datetime, store: PayloadStore | None, config: shadow.Config = shadow.CONFIG,
                 code_version: str | None = None, commit: bool = True,
                 clock_ms: Callable[[], float] | None = None) -> Report:
    """One E3 pass: every tracked match of the next ``LINE_UP_AHEAD`` whose official line-up (a new content of it) arrived."""
    rep = Report()
    if not _tables_exist(conn):
        raise RuntimeError("intel.eval_runs does not exist: apply revision 0156 first")
    if not _lock(conn, LOCK_LINE_UPS):
        rep.errors.append("another pass holds the lock")
        return rep
    ctx = Context(conn, now, store, config, code_version, None, rep)
    if clock_ms is not None:
        ctx.clock_ms = clock_ms
    try:
        if commit:
            conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        matches = [_match(r) for r in _fetch(conn, FIXTURES_SQL, {"start": now, "end": now + LINE_UP_AHEAD})]
        ids = [x.id for x in matches]
        runs = _runs(conn, ids)
        failures = _failures(conn, ids)
        arrivals = arrivals_of(conn, ids, now)
        if commit:
            conn.commit()
        for m in matches:
            mine = runs.get(m.id, [])
            if failures.get((m.id, "E3"), 0) >= MAX_FAILURES:
                continue
            done = [r.cause_key for r in mine if r.evaluation == "E3"]
            due = clock.plan_line_up(arrivals.get(m.id, {}), done, now=now, kickoff_at=m.kickoff_at)
            if due is None:
                continue
            _guarded(ctx, m, "E3", functools.partial(e3, ctx, m, mine, due), version=_version(mine, "E3"),
                     cause=due.cause, cause_key=due.key, trigger_at=due.trigger_at)
            if commit:
                conn.commit()
    finally:
        if commit:
            conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_LINE_UPS,))
        if commit:
            conn.commit()
    return rep


# -- the cycle of states ----------------------------------------------------------------------------------------------------------------

LINK_FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group FROM core.fixtures f
 WHERE f.id IN (SELECT r.fixture_id FROM intel.eval_runs r WHERE r.kickoff_at >= %(start)s AND r.kickoff_at < %(end)s)
"""


def chains_of(rows: Iterable[Mapping[str, Any]], fixtures: Mapping[int, derive.Fixture], *, now: datetime) -> dict[derive.Key, list[derive.Row]]:
    by: dict[derive.Key, list[chain.Verdict]] = defaultdict(list)
    for r in rows:
        k = derive.Key.of(r["fixture_id"], r["market_key"], r["selection"], r["line"])
        by[k].append(chain.Verdict(int(r["id"]), r["known_at"], str(r["state"]), str(r["reason"]), str(r["evaluation"]),
                                   int(r["evaluation_version"])))
    return {k: chain.chain(vs, fixtures[k.fixture_id], now=now) for k, vs in by.items() if k.fixture_id in fixtures}


def link_lifecycle(conn: psycopg.Connection[Any], *, now: datetime, dry_run: bool = False) -> lifecycle.PassReport:
    """The chains of the matches of the last ``BACK`` and the next 48 h, appended under ``eval-cycle-v1`` (the cycle's API)."""
    fixtures = {int(r["id"]): derive.Fixture(int(r["id"]), r["kickoff_at"], r["status_short"], r["status_group"])
                for r in _fetch(conn, LINK_FIXTURES_SQL, {"start": now - BACK, "end": now + 2 * AHEAD})}
    if not fixtures:
        return lifecycle.PassReport()
    rows = _fetch(conn, LINK_SQL, {"fixtures": sorted(fixtures)})
    return lifecycle.extend_rows(conn, chains_of(rows, fixtures, now=now), writer=chain.WRITER, dry_run=dry_run)
