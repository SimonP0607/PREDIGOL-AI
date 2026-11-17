"""The read-only measurement of value-v2 (AD-E02, IA-097) and of the three calculations of correlation against corr-v2 (AD-E07, IA-098).

    python -m scripts.ia_value_correlation drift --days 8 --json                          # how far a price moves with its age
    python -m scripts.ia_value_correlation value --since 2026-11-03 --until 2026-11-17     # value-v2 over decision-v1's rows
    python -m scripts.ia_value_correlation correlation --since 2026-11-03 --until 2026-11-17

``drift``: the change of the logarithm of the best price between consecutive consensus captures of a selection (the measurement behind
``value.PRICE_DRIFT_PER_SQRT_HOUR`` and ``PRICE_DRIFT_CAP``), by how far apart the captures are.

``value``: value-v2 on every row decision-v1 wrote in the window (``intel.decisions``), at its own moment (``known_at``) with its own
calibrated probability (conditional, as decision-v1 keeps it), its model's interval carried to it by width, its price, its books and the
moment of its price: how many carry an interval, the verdicts, «una sola casa», by decision-v1's state.

``correlation``: for each Bogotá day, the selections the shadow portfolio would weigh (``fbi.portfolio.build.read_rows`` as of 06:00
Bogotá, RECOMMENDED and CAUTION through state-v2) and every pair of them, under the three calculations of today - decision-v1's filter 8
(one per match), ``parlay-v5`` (``persist.correlated_pairs``, after its guard of one match and one team) and ``portfolio-corr-v1``
(``fbi.portfolio.correlation.estimate``, with no joint distribution, as in production) - and under corr-v2 with each match's score matrix.

Nothing is written: the connection is read-only (``default_transaction_read_only``) with a statement timeout. Exit 0 a report, 2 it cannot
run.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import DAY_TZ
from fbi.core.decision_versions import DECISION_CORE
from fbi.parlays import correlation as icc
from fbi.parlays import persist
from fbi.portfolio import build as portfolio
from fbi.portfolio import correlation as pcorr
from fbi.portfolio.selection import Selection
from fbi.valuation import dependence as dep
from fbi.valuation import value as v

COMMANDS = ("drift", "value", "correlation")
OK, CANNOT = 0, 2
MOMENT = time(6, 0)
"""The moment of each day the portfolio's selections are read as of (Bogotá)."""
STATES = ("RECOMMENDED", "CAUTION")

DRIFT_SQL = """
WITH fx AS (SELECT id, kickoff_at FROM core.fixtures WHERE kickoff_at >= %(lo)s AND kickoff_at < %(hi)s),
s AS (
  SELECT m.as_of, m.best_odds::float8 AS o, m.n_bookmakers AS nb, lag(m.as_of) OVER w AS as0, lag(m.best_odds::float8) OVER w AS o0
    FROM market.market_consensus m JOIN fx ON fx.id = m.fixture_id
   WHERE m.devig_method = 'shin' AND m.as_of < fx.kickoff_at
     AND (m.market_key IN ('1X2', 'BTTS') OR (m.market_key = 'OU' AND m.line = 2.5))
  WINDOW w AS (PARTITION BY m.fixture_id, m.market_key, m.selection, m.line ORDER BY m.as_of))
SELECT width_bucket(extract(epoch FROM as_of - as0) / 3600, ARRAY[0, 0.5, 1, 2, 3, 6, 12, 24, 48, 96]) AS band, count(*) AS n,
       avg(extract(epoch FROM as_of - as0) / 3600) AS hours, sqrt(avg(ln(o / o0) ^ 2)) AS rms
  FROM s WHERE as0 IS NOT NULL AND o > 1 AND o0 > 1 AND nb >= 3 GROUP BY 1 ORDER BY 1
"""

VALUE_SQL = """
SELECT d.id, d.state, d.known_at, d.market_key, d.selection, d.line, d.p_model::float8 AS p_model, d.p_low::float8 AS p_low,
       d.p_high::float8 AS p_high, COALESCE(d.p_push, 0)::float8 AS p_push, d.p_cal::float8 AS p_cal, d.odds::float8 AS odds,
       d.n_bookmakers, d.price_at, d.ev_cal::float8 AS ev_cal
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.known_at >= %(lo)s AND d.known_at < %(hi)s AND d.checkpoint <> 'selection'
 ORDER BY d.known_at, d.id
"""


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=DAY_TZ)


def _spread(xs: Sequence[float]) -> dict[str, Any]:
    s = sorted(xs)
    if not s:
        return {"n": 0}

    def q(p: float) -> float:
        return round(s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))], 6)

    return {"n": len(s), "p10": q(0.1), "p50": q(0.5), "p90": q(0.9), "min": round(s[0], 6), "max": round(s[-1], 6)}


# -- drift -----------------------------------------------------------------------------------------------------------------------------

def drift(conn: psycopg.Connection[Any], *, until: datetime, days: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DRIFT_SQL, {"lo": until - timedelta(days=days), "hi": until})
        rows = [dict(r) for r in cur.fetchall()]
    bands = [{"hours": round(float(r["hours"]), 3), "n": int(r["n"]), "rms": round(float(r["rms"]), 5),
              "rms_per_sqrt_hour": round(float(r["rms"]) / math.sqrt(float(r["hours"])), 5) if float(r["hours"]) > 0 else None}
             for r in rows]
    return {"window": {"kickoff_from": (until - timedelta(days=days)).isoformat(), "kickoff_to": until.isoformat()}, "bands": bands,
            "in_code": {"per_sqrt_hour": v.PRICE_DRIFT_PER_SQRT_HOUR, "cap": v.PRICE_DRIFT_CAP}}


# -- value -----------------------------------------------------------------------------------------------------------------------------

def reading(r: dict[str, Any]) -> v.ValueReading:
    """value-v2 of one decision-v1 row at its own moment."""
    p_model, p_cal, push = r["p_model"], r["p_cal"], r["p_push"]
    judged = p_cal if p_cal is not None else p_model
    chance: v.Chance | None = None
    if judged is not None:
        moved = p_cal is not None and p_model is not None and p_cal != p_model
        lo, hi = v.transported(judged, p_model, r["p_low"], r["p_high"]) if moved else (r["p_low"], r["p_high"])
        try:
            chance = v.Chance.conditional(judged, push, lo, hi, calibrated=p_cal is not None,
                                          interval_basis="transported" if moved else "own")
        except ValueError:
            chance = None
    return v.assess(chance, v.Quote(r["odds"], r["n_bookmakers"], r["price_at"]), at=r["known_at"])


def value(conn: psycopg.Connection[Any], *, since: date, until: date) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(VALUE_SQL, {"version": DECISION_CORE, "lo": _day_start(since), "hi": _day_start(until)})
        rows = [dict(r) for r in cur.fetchall()]
    by_state: dict[str, Counter[str]] = defaultdict(Counter)
    readings = []
    gaps = []
    for r in rows:
        x = reading(r)
        readings.append(x)
        by_state[str(r["state"])][x.verdict] += 1
        if x.ev is not None and r["ev_cal"] is not None and x.calibrated:
            gaps.append(abs(x.ev - r["ev_cal"]))
    priced = [x for x in readings if x.odds is not None and x.verdict != v.FUTURE_PRICE]
    with_interval = [x for x in priced if x.ev_low is not None]
    return {"window": {"since": since.isoformat(), "until": until.isoformat(), "version": DECISION_CORE}, "rows": len(rows),
            "priced": len(priced), "with_interval": len(with_interval),
            "verdicts": dict(sorted(Counter(x.verdict for x in readings).items())),
            "by_state": {s: dict(sorted(c.items())) for s, c in sorted(by_state.items())},
            "books_of_priced": dict(sorted(Counter("none" if x.books is None else str(min(x.books, 10)) for x in priced).items())),
            "single_book_of_priced": sum(1 for x in priced if x.single_book),
            "confirmed": sum(1 for x in readings if x.confirms),
            "confirmed_single_book": sum(1 for x in readings if x.confirms and x.single_book),
            "interval_basis": dict(sorted(Counter(x.interval_basis for x in readings).items())),
            "price_age_min": _spread([x.price_age_min for x in priced if x.price_age_min is not None]),
            "ev": _spread([x.ev for x in with_interval if x.ev is not None]),
            "ev_low": _spread([x.ev_low for x in with_interval if x.ev_low is not None]),
            "width": _spread([(x.ev_high or 0) - (x.ev_low or 0) for x in with_interval]),
            "ev_vs_decision_v1": {"compared": len(gaps), "over_1e-6": sum(1 for g in gaps if g > 1e-6), "max": max(gaps, default=None)}}


# -- correlation -----------------------------------------------------------------------------------------------------------------------

def _ranked(s: Selection) -> Any:
    """A selection in the shape ``persist.correlated_pairs`` reads (the leg's candidate and the row's competition)."""
    return SimpleNamespace(leg=SimpleNamespace(candidate=SimpleNamespace(market_key=s.market_key, selection=s.selection,
                                                                         kickoff_at=s.kickoff_at)), row={"competition_id": s.competition_id})


def correlation(conn: psycopg.Connection[Any], *, since: date, until: date) -> dict[str, Any]:
    estimates = icc.latest(conn)
    measured = {m: dep.Measured.of(e) for m, e in estimates.items()}
    relation: Counter[str] = Counter()
    v1_source: Counter[str] = Counter()
    v2_source: Counter[str] = Counter()
    parlay: Counter[str] = Counter()
    budget: Counter[str] = Counter()
    joint_diff: Counter[str] = Counter()
    matrix_rhos: list[float] = []
    same_match_kinds: Counter[str] = Counter()
    filter8: Counter[str] = Counter()
    days = selections = matrices_found = fixtures_seen = 0
    day = since
    while day < until:
        at = _day_start(day) + timedelta(hours=MOMENT.hour)
        sel = [s for s in (Selection.of(r) for r in portfolio.read_rows(conn, day=day, at=at)) if s.state_v2 in STATES]
        day += timedelta(days=1)
        if len(sel) < 2:
            continue
        days += 1
        selections += len(sel)
        mats, basis = dep.read_matrices(conn, [s.fixture_id for s in sel], at=at)
        fixtures_seen += len({s.fixture_id for s in sel})
        matrices_found += len(mats)
        legs = {s.decision_id: dep.Leg(s.decision_id, s.fixture_id, s.competition_id, s.kickoff_at, s.teams, s.market_key, s.selection,
                                       s.line) for s in sel}
        for i, a in enumerate(sel):
            for b in sel[i + 1:]:
                old = pcorr.estimate(a, b, measured=estimates)
                new = dep.estimate(legs[a.decision_id], legs[b.decision_id], matrices=mats, measured=measured, matrix_basis=basis)
                if new.relation == "none" and old.source == "none":
                    relation["none"] += 1
                    continue
                relation[new.relation] += 1
                v1_source[old.source] += 1
                v2_source[f"{new.relation}:{new.source}"] += 1
                # decision-v1's filter 8: one approvable selection per match - the only dependence it knows
                if new.relation == "same_match":
                    filter8["same_match_pair"] += 1
                    same_match_kinds[f"{a.market_key}/{b.market_key}"] += 1
                    if "correlated_same_match" in (a.reason, b.reason):
                        filter8["a_side_is_correlated_same_match"] += 1
                    if new.source == dep.SCORE_MATRIX and new.rho is not None:
                        matrix_rhos.append(new.rho)
                # parlay-v5: the guard refuses one match and one team; then only a significant negative measured rho enters the joint
                if new.relation in ("same_match", "same_team"):
                    parlay["refused_by_guard"] += 1
                    joint_diff["v2_combinable" if new.combinable else "v2_not_combinable"] += 1
                else:
                    pairs = persist.correlated_pairs(cast(Any, [_ranked(a), _ranked(b)]), estimates)
                    old_rho = pairs[0][2] if pairs else 0.0
                    parlay["joint_corrected" if pairs else "independent"] += 1
                    joint_diff["same" if abs(old_rho - (new.joint_rho or 0.0)) <= 1e-12 else "differs"] += 1
                # portfolio-corr-v1 against corr-v2: the budget's dependence
                o, n = old.budget_rho, new.budget_rho
                budget["same" if abs(o - n) <= 1e-9 else "v2_higher" if n > o else "v2_lower"] += 1
                if abs(o - n) > 1e-9:
                    budget[f"{old.source}->{new.relation}:{new.source}"] += 1
    return {"window": {"since": since.isoformat(), "until": until.isoformat(), "moment_bogota": MOMENT.isoformat(),
                       "states": list(STATES)},
            "measured": {m: {"rho": e.rho, "se": e.se, "n_groups": e.n_groups, "significant": e.n_groups >= icc.MIN_GROUPS
                             and (e.rho - 1.96 * e.se > 0 or e.rho + 1.96 * e.se < 0)} for m, e in sorted(estimates.items())},
            "days": days, "selections": selections, "fixtures": fixtures_seen, "matrices": matrices_found,
            "pairs_by_relation": dict(sorted(relation.items())),
            "portfolio_corr_v1_source": dict(sorted(v1_source.items())), "corr_v2_source": dict(sorted(v2_source.items())),
            "decision_v1_filter_8": dict(sorted(filter8.items())), "same_match_markets": dict(same_match_kinds.most_common(12)),
            "parlay_v5": dict(sorted(parlay.items())), "joint_parlay_v5_vs_corr_v2": dict(sorted(joint_diff.items())),
            "budget_portfolio_v1_vs_corr_v2": dict(sorted(budget.items())),
            "same_match_matrix_rho": _spread(matrix_rhos)
            | {"abs_ge_0_60": sum(1 for x in matrix_rhos if abs(x) >= 0.60), "negative": sum(1 for x in matrix_rhos if x < 0)}}


# -- the command -----------------------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_value_correlation", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--since", help="first Bogotá day (YYYY-MM-DD)")
    ap.add_argument("--until", help="the Bogotá day after the last (YYYY-MM-DD)")
    ap.add_argument("--days", type=int, default=8, help="drift: matches that kicked off in the last N days (and over a day ago)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    try:
        since = None if args.since is None else date.fromisoformat(args.since)
        until = None if args.until is None else date.fromisoformat(args.until)
    except ValueError as exc:
        ap.error(str(exc))
    if args.command in ("value", "correlation") and (since is None or until is None or since >= until):
        ap.error("value and correlation need --since < --until")
    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000") as conn:
        if args.command == "drift":
            now = conn.execute("SELECT now()").fetchone()
            assert now is not None
            doc = drift(conn, until=now[0] - timedelta(days=1), days=args.days - 1)
        elif args.command == "value":
            assert since is not None and until is not None
            doc = value(conn, since=since, until=until)
        else:
            assert since is not None and until is not None
            doc = correlation(conn, since=since, until=until)
    out = {"command": args.command, "versions": {"value": v.VERSION, "correlation": dep.VERSION}} | doc
    sys.stdout.write(json.dumps(out, indent=None if not args.as_json else 1, default=str, ensure_ascii=False) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
