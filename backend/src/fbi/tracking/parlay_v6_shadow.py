"""``parlay-v6`` in the SHADOW (IA-110, AD-E06): build it from the chains confirmed in the shadow, keep it, follow it to its result.

One pass (``run_pass``), every ``EVERY`` minutes from the worker while ``FBI_PARLAY_V6=shadow`` (``off`` by default: the job is not even
scheduled):

1. for each kind (``daily``: the product day; ``multiday``: the next 72 hours over two product days) not yet kept for today: the chains of
   ``CHAINS`` (decision-v2's kept shadow, IA-093) whose NEWEST row is ``confirmada_sombra`` and whose match is in the window, with the
   price, books and probability of the decision that confirmed them (``CANDIDATES_SQL``) - read only;
2. the score matrices of the matches with two candidates (``corr-v2``'s same-match dependence) and the measured correlations;
3. ``fbi.tracking.parlay_v6.choose``: a parlay is kept the first time one meets (``intel.parlays_v6`` and its legs); otherwise nothing yet;
4. a product day that ended without one of a kind is kept as ``none``, with why (``close_days``): the days without a parlay are records too.

The legs are settled by the tracking of loose selections (IA-109, ``fbi.tracking.selections``, ``intel.selection_settlements``): a parlay's result
is read from its legs' newest settlements (``read``), never written twice. ``calibration`` measures the joint against the results, with its
sample.

It writes ``intel.parlays_v6`` and ``intel.parlay_v6_legs`` and nothing else. ``picks.parlays``, ``parlay-v5`` (what the product shows today)
and ``FBI_PICKS_SOURCE`` are not touched; no reader's page imports this.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds, local_day
from fbi.tracking import parlay_v6 as v6
from fbi.valuation import dependence as dep

SWITCH: Final = "FBI_PARLAY_V6"
CHAINS: Final = "decision-v2-shadow-v1"
"""The writer of the chains whose confirmations are the legs (decision-v2's kept shadow)."""
EVERY: Final = int(os.environ.get("FBI_PARLAY_V6_MINUTES", "15"))
CLOSE_BACK: Final = 3
"""Product days back that a day without a parlay is still recorded as such (a worker down for a while does not lose them)."""
LOCK: Final = 0x1A110
TIMEOUT_MS: Final = 60_000


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


CANDIDATES_SQL: Final = """
WITH tip AS (
    SELECT DISTINCT ON (s.chain_key) s.id, s.chain_key, s.fixture_id, s.market_key, s.selection, s.line, s.state, s.known_at,
           s.source, s.source_id
      FROM intel.selection_lifecycle s JOIN core.fixtures f ON f.id = s.fixture_id
     WHERE s.writer = %(writer)s AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND s.known_at <= %(at)s
     ORDER BY s.chain_key, s.id DESC
)
SELECT t.*, f.kickoff_at, f.home_team_id, f.away_team_id, cs.competition_id,
       COALESCE(d2.odds, d1.odds)::float8 AS odds, COALESCE(d2.p_market, d1.p_market)::float8 AS p_market,
       COALESCE(d2.p_cal, d1.p_cal)::float8 AS p_cal, COALESCE(d2.p_model, d1.p_model)::float8 AS p_model,
       COALESCE((d2.decision->'prediction'->'interval'->>0)::float8, d1.p_low::float8) AS p_low,
       COALESCE((d2.decision->'price'->>'n_bookmakers')::int, d1.n_bookmakers) AS n_bookmakers,
       COALESCE(d2.price_at, d1.price_at) AS price_at
  FROM tip t
  JOIN core.fixtures f ON f.id = t.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  LEFT JOIN intel.decisions_v2 d2 ON t.source = 'intel.decisions_v2' AND d2.id = t.source_id
  LEFT JOIN intel.decisions d1 ON t.source = 'intel.decisions' AND d1.id = t.source_id
 WHERE t.state = 'confirmada_sombra'
 ORDER BY f.kickoff_at, t.chain_key
"""
"""The chains whose newest row at ``at`` is a confirmation, with the price and probability of the decision that confirmed them."""
EXISTS_SQL: Final = "SELECT kind, day FROM intel.parlays_v6 WHERE writer = %(writer)s AND rule_version = %(rule)s AND day >= %(since)s"
EVER_CONFIRMED_SQL: Final = """
SELECT count(DISTINCT s.chain_key) FROM intel.selection_lifecycle s JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.writer = %(writer)s AND s.state = 'confirmada_sombra' AND s.known_at < f.kickoff_at
   AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
"""
PARLAY_SQL: Final = """
INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, none_reason, max_legs, n_legs, n_candidates, window_from, window_to,
    combined_odds, p_joint, p_joint_se, p_joint_low, p_product, p_market_joint, fair_odds, accumulated_margin, expected_value,
    expected_value_low, expected_log_growth, simulations, seed, dependence, inputs, known_at, code_version)
VALUES (%(writer)s, %(rule)s, %(kind)s, %(day)s, %(outcome)s, %(none_reason)s, %(max_legs)s, %(n_legs)s, %(n_candidates)s, %(frm)s,
    %(to)s, %(combined_odds)s, %(p_joint)s, %(p_joint_se)s, %(p_joint_low)s, %(p_product)s, %(p_market_joint)s, %(fair_odds)s,
    %(margin)s, %(ev)s, %(ev_low)s, %(elg)s, %(simulations)s, %(seed)s, %(dependence)s, %(inputs)s, %(known_at)s, %(code_version)s)
ON CONFLICT (writer, rule_version, kind, day) DO NOTHING
RETURNING id
"""
LEG_SQL: Final = """
INSERT INTO intel.parlay_v6_legs (parlay_id, leg_no, chain_key, confirmed_id, confirmed_at, fixture_id, kickoff_at, market_key, selection,
    line, odds, n_bookmakers, p_model, p_low, p_market, price_at, source, source_id, inputs)
VALUES (%(parlay_id)s, %(leg_no)s, %(chain_key)s, %(confirmed_id)s, %(confirmed_at)s, %(fixture_id)s, %(kickoff_at)s, %(market_key)s,
    %(selection)s, %(line)s, %(odds)s, %(n_bookmakers)s, %(p_model)s, %(p_low)s, %(p_market)s, %(price_at)s, %(source)s, %(source_id)s,
    %(inputs)s)
"""


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def candidate_of(r: Mapping[str, Any]) -> v6.Candidate:
    """A row of ``CANDIDATES_SQL`` as the builder reads it. The probability is the calibrated one when there is one; its pessimistic end
    keeps the width of the model's interval below the point (``p - (p_model - p_low)``), never above the point. Pure."""
    p_model = r.get("p_model")
    p = r.get("p_cal") if r.get("p_cal") is not None else p_model
    low = r.get("p_low")
    if p is not None and low is not None and p_model is not None:
        low = min(float(p), float(p) - max(0.0, float(p_model) - float(low)))
    teams = frozenset(int(t) for t in (r.get("home_team_id"), r.get("away_team_id")) if t is not None)
    return v6.Candidate(str(r["chain_key"]), str(r["state"]), int(r["id"]), r["known_at"], int(r["fixture_id"]),
                        None if r.get("competition_id") is None else int(r["competition_id"]), r["kickoff_at"], teams,
                        str(r["market_key"]), str(r["selection"]), Decimal(r["line"]).quantize(Decimal("0.01")),
                        None if r.get("odds") is None else float(r["odds"]), None if p is None else float(p),
                        None if low is None else float(low), None if r.get("p_market") is None else float(r["p_market"]),
                        None if r.get("n_bookmakers") is None else int(r["n_bookmakers"]), str(r["source"]),
                        int(r["source_id"] or 0), r.get("price_at"))


def candidates(conn: psycopg.Connection[Any], *, at: datetime, start: datetime, end: datetime, writer: str = CHAINS) -> list[v6.Candidate]:
    """The candidates of the window ``[start, end)`` as of ``at``. Read-only."""
    return [candidate_of(r) for r in _fetch(conn, CANDIDATES_SQL, {"writer": writer, "start": start, "end": end, "at": at})]


def none_reason(n: int) -> str:
    return "sin_candidatos" if n == 0 else "un_solo_candidato" if n == 1 else "ninguna_combinacion_cumple"


@dataclass
class PassReport:
    built: int = 0
    looked: int = 0
    days_without: int = 0
    by_kind: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"built": self.built, "looked": self.looked, "days_without": self.days_without, "by_kind": dict(self.by_kind),
                "errors": self.errors[:20]}


def _tables_exist(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT to_regclass('intel.parlays_v6') IS NOT NULL AND to_regclass('intel.selection_lifecycle') IS NOT NULL "
                       "AND to_regclass('intel.decisions_v2') IS NOT NULL").fetchone()
    return bool(row and row[0])


def build(conn: psycopg.Connection[Any], *, kind: str, at: datetime, writer: str = CHAINS,
          simulations: int = v6.SIMULATIONS) -> v6.Built | v6.NoParlay:
    """What ``parlay-v6`` would build of ``kind`` at ``at`` from what is stored. Read-only (``run_pass`` keeps it; the command shows it)."""
    frm, to = v6.window(kind, at)
    pool = candidates(conn, at=at, start=frm, end=to, writer=writer)
    valid = [c for c in pool if v6.refusal(c, at=at) is None]
    per_match: dict[int, int] = {}
    for c in valid:
        per_match[c.fixture_id] = per_match.get(c.fixture_id, 0) + 1
    twice = sorted(f for f, n in per_match.items() if n > 1)
    matrices, basis = dep.read_matrices(conn, twice, at=at) if twice else ({}, {})
    measured = dep.read_measured(conn) if len(valid) > 1 else {}
    return v6.choose(pool, kind=kind, at=at, matrices=matrices, measured=measured, matrix_basis=basis, simulations=simulations)


def _keep(conn: psycopg.Connection[Any], res: v6.Built | v6.NoParlay, *, writer: str, day: date, frm: datetime, to: datetime,
          at: datetime, code_version: str | None) -> int | None:
    params: dict[str, Any] = {
        "writer": writer, "rule": v6.RULE_VERSION, "kind": res.kind, "day": day, "outcome": res.outcome, "none_reason": None,
        "max_legs": res.max_legs, "n_legs": 0, "n_candidates": res.n_candidates, "frm": frm, "to": to, "known_at": at,
        "code_version": code_version, "combined_odds": None, "p_joint": None, "p_joint_se": None, "p_joint_low": None,
        "p_product": None, "p_market_joint": None, "fair_odds": None, "margin": None, "ev": None, "ev_low": None, "elg": None,
        "simulations": None, "seed": None, "dependence": Jsonb([]), "inputs": Jsonb({})}
    if isinstance(res, v6.NoParlay):
        params.update({"none_reason": res.reason, "inputs": Jsonb({"refused": dict(res.refused)})})
    if isinstance(res, v6.Built):
        j = res.joint
        params.update({
            "combined_odds": round(res.combined_odds, 4), "p_joint": round(j.p, 8), "p_joint_se": round(j.se, 8),
            "p_joint_low": round(j.p_low, 8), "p_product": round(j.product, 8),
            "p_market_joint": None if j.p_market is None else round(j.p_market, 8), "fair_odds": round(res.fair_odds, 4),
            "margin": None if res.accumulated_margin is None else round(res.accumulated_margin, 6), "ev": round(res.expected_value, 6),
            "ev_low": round(res.expected_value_low, 6), "elg": round(res.expected_log_growth, 10), "simulations": j.simulations,
            "seed": j.seed, "dependence": Jsonb(list(res.dependence)),
            "n_legs": len(res.legs), "inputs": Jsonb({"latent": [list(x) for x in j.latent], "leg_margins": list(res.leg_margins)})})
    got = conn.execute(PARLAY_SQL, params).fetchone()
    if got is None:
        return None
    parlay_id = int(got[0])
    if isinstance(res, v6.Built):
        for n, c in enumerate(res.legs, start=1):
            conn.execute(LEG_SQL, {
                "parlay_id": parlay_id, "leg_no": n, "chain_key": c.chain_key, "confirmed_id": c.confirmed_id,
                "confirmed_at": c.confirmed_at, "fixture_id": c.fixture_id, "kickoff_at": c.kickoff_at, "market_key": c.market_key,
                "selection": c.selection, "line": c.line, "odds": c.odds, "n_bookmakers": c.n_bookmakers, "p_model": c.p, "p_low": c.p_low,
                "p_market": c.p_market, "price_at": c.price_at, "source": c.source, "source_id": c.source_id,
                "inputs": Jsonb({"competition_id": c.competition_id, "teams": sorted(c.teams)})})
    return parlay_id


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, writer: str = CHAINS, dry_run: bool = False,
             code_version: str | None = None) -> PassReport:
    """One pass of ``parlay-v6`` in the shadow. ``dry_run`` reads the same and writes nothing."""
    rep = PassReport()
    if not _tables_exist(conn):
        rep.errors.append("intel.parlays_v6, intel.selection_lifecycle or intel.decisions_v2 does not exist: apply 0142, 0150 and 0157")
        conn.rollback()
        return rep
    if not dry_run:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
        if not got or not got[0]:
            rep.errors.append("another pass holds the lock")
            conn.rollback()
            return rep
    try:
        conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        today = local_day(now)
        kept = {(str(r["kind"]), r["day"]) for r in _fetch(conn, EXISTS_SQL, {"writer": writer, "rule": v6.RULE_VERSION,
                                                                              "since": today - timedelta(days=CLOSE_BACK)})}
        for kind in v6.SPECS:
            if (kind, today) in kept:
                rep.by_kind[kind] = "kept"
                continue
            try:
                rep.looked += 1
                res = build(conn, kind=kind, at=now, writer=writer)
                rep.by_kind[kind] = res.outcome if isinstance(res, v6.Built) else f"none:{res.reason}"
                if isinstance(res, v6.Built):
                    rep.built += 1
                    if not dry_run:
                        frm, to = v6.window(kind, now)
                        _keep(conn, res, writer=writer, day=today, frm=frm, to=to, at=now, code_version=code_version)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                rep.errors.append(f"{kind}: {type(exc).__name__}: {exc}"[:300])
        rep.days_without = close_days(conn, now=now, writer=writer, kept=kept, dry_run=dry_run, code_version=code_version)
    finally:
        if not dry_run:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
            conn.commit()
    return rep


def day_window(kind: str, day: date) -> tuple[datetime, datetime]:
    """The kick-offs a parlay of ``kind`` of product day ``day`` could have held: the day, or the day and the 72 hours after it."""
    frm, to = day_bounds(day)
    return (frm, to) if kind == "daily" else (frm, to + v6.MULTIDAY_WINDOW)


def close_days(conn: psycopg.Connection[Any], *, now: datetime, writer: str, kept: set[tuple[str, date]], dry_run: bool,
               code_version: str | None) -> int:
    """Keep ``none`` for every product day of the last ``CLOSE_BACK`` that ended without a parlay of a kind, with why: no chain of its
    window was ever confirmed, one was, or several were and no combination met. Returns how many."""
    today = local_day(now)
    n = 0
    for back in range(CLOSE_BACK, 0, -1):
        day = today - timedelta(days=back)
        for kind in v6.SPECS:
            if (kind, day) in kept:
                continue
            frm, to = day_window(kind, day)
            row = conn.execute(EVER_CONFIRMED_SQL, {"writer": writer, "start": frm, "end": to}).fetchone()
            count = int(row[0]) if row else 0
            res = v6.NoParlay(kind, none_reason(count), count)  # type: ignore[arg-type]
            if not dry_run:
                _keep(conn, res, writer=writer, day=day, frm=frm, to=to, at=now, code_version=code_version)
            n += 1
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return n


# -- the owner's reading (private) ----------------------------------------------------------------------------------------------------

READ_SQL: Final = """
SELECT p.id, p.kind, p.day, p.outcome, p.none_reason, p.n_legs, p.n_candidates, p.combined_odds::float8, p.p_joint::float8,
       p.p_joint_se::float8, p.p_joint_low::float8, p.p_product::float8, p.p_market_joint::float8, p.fair_odds::float8,
       p.accumulated_margin::float8, p.expected_value::float8, p.known_at, p.rule_version
  FROM intel.parlays_v6 p
 WHERE p.writer = %(writer)s AND p.day >= %(start)s AND p.day <= %(end)s
 ORDER BY p.day, p.kind
"""
LEGS_SQL: Final = """
SELECT l.parlay_id, l.leg_no, l.chain_key, l.fixture_id, l.market_key, l.selection, l.line, l.odds::float8, l.p_model::float8,
       l.p_low::float8, l.p_market::float8, l.kickoff_at,
       (SELECT s.result FROM intel.selection_settlements s WHERE s.chain_key = l.chain_key AND s.kind IN ('primera', 'correccion')
         ORDER BY s.known_at DESC, s.id DESC LIMIT 1) AS result
  FROM intel.parlay_v6_legs l WHERE l.parlay_id = ANY(%(ids)s) ORDER BY l.parlay_id, l.leg_no
"""


def read(conn: psycopg.Connection[Any], *, start: date, end: date, writer: str = CHAINS) -> list[dict[str, Any]]:
    """The parlays of ``parlay-v6`` of the product days ``start`` to ``end`` with their legs and their result (from the legs' newest
    settlements). Read-only; for the owner (C-04 is AD-J05)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL statement_timeout = 30000")
        cur.execute(READ_SQL, {"writer": writer, "start": start, "end": end})
        parlays = [dict(r) for r in cur.fetchall()]
        ids = [int(p["id"]) for p in parlays if p["outcome"] == "built"]
        legs: dict[int, list[dict[str, Any]]] = {}
        if ids:
            cur.execute(LEGS_SQL, {"ids": ids})
            for r in cur.fetchall():
                legs.setdefault(int(r["parlay_id"]), []).append(dict(r))
    out = []
    for p in parlays:
        mine = legs.get(int(p["id"]), [])
        status, factor = v6.outcome([r["result"] for r in mine], [float(r["odds"]) for r in mine]) if mine else ("NONE", None)
        out.append({**{k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in p.items()}, "status": status,
                    "payout_factor": factor,
                    "legs": [{"chain_key": r["chain_key"], "fixture_id": r["fixture_id"], "market": r["market_key"],
                              "selection": r["selection"], "line": float(r["line"]), "odds": r["odds"], "p_model": r["p_model"],
                              "p_low": r["p_low"], "p_market": r["p_market"], "kickoff_at": r["kickoff_at"].isoformat(),
                              "result": r["result"]} for r in mine]})
    return out


def calibration(parlays: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The joint against the results of the settled parlays (WON or LOST; a parlay with a void leg is left out: its joint was of three
    legs): how many, how many won, the sum of the joints, the Brier score and the same for the pessimistic joint. Pure."""
    done = [p for p in parlays if p.get("status") in ("WON", "LOST")]
    n = len(done)
    won = sum(1 for p in done if p["status"] == "WON")
    if not n:
        return {"settled": 0, "won": 0, "expected": None, "expected_low": None, "brier": None, "note": "sin parlays liquidados todavía"}
    exp = sum(float(p["p_joint"]) for p in done)
    low = sum(float(p["p_joint_low"]) for p in done)
    brier = sum((float(p["p_joint"]) - (p["status"] == "WON")) ** 2 for p in done) / n
    return {"settled": n, "won": won, "expected": round(exp, 4), "expected_low": round(low, 4), "brier": round(brier, 6),
            "note": "muestra pequeña: la calibración no se juzga con menos de 100 parlays" if n < 100 else ""}
