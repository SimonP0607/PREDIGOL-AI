"""The AI's own prospective test: does the review add information - before it is allowed to touch users?

Over settled selections the AI reviewed BEFORE kick-off (the newest review of each selection, per engine),
three things are compared on the same matches:

    model         every selection the quantitative rule shortlisted (what users would get without the AI)
    model + AI    the selections the review kept (APPROVE, DOWNGRADE, ABSTAIN) - and APPROVE alone
    market        the de-vigged market's own forecast of the same selections

with log loss and Brier score (of the model's and the market's probabilities), calibration (expected
calibration error, ten bins), hit rate, ROI at the price taken (flat one unit), closing-line value (the
price taken against the provider's final pre-match price of the same bookmaker), the claimed EV and the EV by
the market's own price, and the worst drawdown. REJECTION QUALITY is the point: what the review rejected must
do measurably worse than what it kept.

The gate (``ai-gate-v1``), which ``FBI_AI_MODE=enforce`` also needs (``fbi.ai.gating``):

* at least 300 settled reviewed selections over at least 30 days, at least 50 of them rejected;
* ROI(kept) - ROI(rejected) at least two standard errors above zero (bootstrap over matches);
* the kept selections' closing-line value not below the rejected ones';
* the kept selections' Brier score no worse than all selections' (+0.002).

Otherwise the verdict is ``insufficient`` (not enough evidence yet) or ``fail``. The numbers are reported
either way; nothing is tuned to pass.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.picks.settlement import Status, market_outcome, profit

VERSION = "ai-gate-v1"
WINDOW = timedelta(days=60)
MIN_SELECTIONS = 300
MIN_DAYS = 30
MIN_REJECTED = 50
MIN_Z = 2.0
BRIER_TOLERANCE = 0.002
ENGINES = ("rules", "llm", "combined")
BOOTSTRAP = 300

SETTLED_SQL = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
       r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.bookmaker_id, r.p_model, r.p_market, r.decision,
       r.reviewed_at, f.kickoff_at, res.reg_goals_home, res.reg_goals_away
  FROM ai.pick_reviews r
  JOIN core.fixtures f ON f.id = r.fixture_id
  JOIN core.fixture_results res ON res.fixture_id = f.id
 WHERE r.engine = %(engine)s AND r.reviewed_at < f.kickoff_at AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND f.status_group = 'finished' AND res.reg_goals_home IS NOT NULL AND r.odds IS NOT NULL AND r.p_model IS NOT NULL
   AND r.status IN ('ok', 'fallback')
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""

CLOSE_SQL = """
SELECT fixture_id, bookmaker_id, market_key, selection, line, odds_decimal FROM market.final_prematch_odds
 WHERE fixture_id = ANY(%(fixtures)s)
"""


@dataclass(frozen=True)
class Settled:
    fixture_id: int
    kickoff_at: datetime
    decision: str
    odds: float
    p_model: float
    p_market: float | None
    status: str
    profit: float
    close: float | None

    @property
    def won(self) -> bool | None:
        return True if self.status == "win" else False if self.status == "loss" else None


def _settle(r: dict[str, Any]) -> tuple[str, float]:
    try:
        st = market_outcome(r["market_key"], r["selection"], Decimal(r["line"]), int(r["reg_goals_home"]),
                            int(r["reg_goals_away"]))
    except ValueError:
        return "unknown", 0.0
    return st.value, float(profit(st, Decimal(r["odds"]), Decimal(1))) if st != Status.PENDING else 0.0


def load(conn: psycopg.Connection[Any], *, engine: str, since: datetime, until: datetime) -> list[Settled]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SETTLED_SQL, {"engine": engine, "since": since, "until": until})
        rows = [dict(r) for r in cur.fetchall()]
        fixtures = sorted({int(r["fixture_id"]) for r in rows})
        closes: dict[tuple[int, int, str, str, Decimal], float] = {}
        if fixtures:
            cur.execute(CLOSE_SQL, {"fixtures": fixtures})
            for c in cur.fetchall():
                closes[(int(c["fixture_id"]), int(c["bookmaker_id"]), c["market_key"], c["selection"],
                        Decimal(c["line"]))] = float(c["odds_decimal"])
    out = []
    for r in rows:
        status, prof = _settle(r)
        if status in ("unknown", "pending"):
            continue
        close = None if r["bookmaker_id"] is None else closes.get(
            (int(r["fixture_id"]), int(r["bookmaker_id"]), r["market_key"], r["selection"], Decimal(r["line"])))
        out.append(Settled(int(r["fixture_id"]), r["kickoff_at"], r["decision"], float(r["odds"]), float(r["p_model"]),
                           None if r["p_market"] is None else float(r["p_market"]), status, prof, close))
    return out


def _ll(p: float, won: bool) -> float:
    return -math.log(min(max(p if won else 1 - p, 1e-6), 1.0))


def ece(pairs: Sequence[tuple[float, bool]], bins: int = 10) -> float | None:
    if not pairs:
        return None
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for p, w in pairs:
        buckets[min(bins - 1, int(p * bins))].append((p, w))
    n = len(pairs)
    return round(sum(len(b) / n * abs(sum(p for p, _ in b) / len(b) - sum(w for _, w in b) / len(b))
                     for b in buckets.values()), 5)


def max_drawdown(items: Sequence[Settled]) -> float:
    peak = cum = worst = 0.0
    for s in sorted(items, key=lambda x: (x.kickoff_at, x.fixture_id)):
        cum += s.profit
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return round(worst, 4)


def metrics(items: Sequence[Settled]) -> dict[str, Any]:
    n = len(items)
    if n == 0:
        return {"n": 0}
    binary = [s for s in items if s.won is not None]
    with_market = [s for s in binary if s.p_market is not None]
    clv = [s.odds / s.close - 1 for s in items if s.close]
    out: dict[str, Any] = {
        "n": n, "fixtures": len({s.fixture_id for s in items}),
        "hit_rate": round(sum(1 for s in binary if s.won) / len(binary), 4) if binary else None,
        "profit": round(sum(s.profit for s in items), 4), "roi": round(sum(s.profit for s in items) / n, 4),
        "ev_claimed": round(sum(s.p_model * s.odds - 1 for s in items) / n, 4),
        "ev_market": round(sum((s.p_market or 0) * s.odds - 1 for s in with_market) / len(with_market), 4)
        if with_market else None,
        "clv": round(sum(clv) / len(clv), 4) if clv else None, "n_clv": len(clv),
        "logloss_model": round(sum(_ll(s.p_model, bool(s.won)) for s in binary) / len(binary), 5) if binary else None,
        "logloss_market": round(sum(_ll(s.p_market or 0.5, bool(s.won)) for s in with_market) / len(with_market), 5)
        if with_market else None,
        "brier_model": round(sum((s.p_model - (1.0 if s.won else 0.0)) ** 2 for s in binary) / len(binary), 5)
        if binary else None,
        "brier_market": round(sum(((s.p_market or 0.5) - (1.0 if s.won else 0.0)) ** 2 for s in with_market)
                              / len(with_market), 5) if with_market else None,
        "ece_model": ece([(s.p_model, bool(s.won)) for s in binary]),
        "ece_market": ece([(s.p_market or 0.5, bool(s.won)) for s in with_market]),
        "max_drawdown": max_drawdown(items),
    }
    return out


def roi_difference(kept: Sequence[Settled], rejected: Sequence[Settled], *, seed: int = 11) -> dict[str, Any]:
    """ROI(kept) - ROI(rejected), its bootstrap standard error (resampling matches, not bets) and z."""
    if not kept or not rejected:
        return {"diff": None, "se": None, "z": None}

    def by_fixture(xs: Sequence[Settled]) -> list[list[float]]:
        g: dict[int, list[float]] = defaultdict(list)
        for s in xs:
            g[s.fixture_id].append(s.profit)
        return list(g.values())

    def roi(groups: list[list[float]]) -> float:
        flat = [x for g in groups for x in g]
        return sum(flat) / len(flat) if flat else 0.0

    gk, gr = by_fixture(kept), by_fixture(rejected)
    diff = roi(gk) - roi(gr)
    rng = random.Random(seed)
    boots = []
    for _ in range(BOOTSTRAP):
        bk = [gk[rng.randrange(len(gk))] for _ in gk]
        br = [gr[rng.randrange(len(gr))] for _ in gr]
        boots.append(roi(bk) - roi(br))
    mean = sum(boots) / len(boots)
    se = math.sqrt(sum((b - mean) ** 2 for b in boots) / (len(boots) - 1))
    return {"diff": round(diff, 4), "se": round(se, 4), "z": round(diff / se, 3) if se > 0 else None}


def evaluate(items: list[Settled]) -> tuple[dict[str, Any], dict[str, Any]]:
    kept = [s for s in items if s.decision != "REJECT"]
    rejected = [s for s in items if s.decision == "REJECT"]
    arms = {"model": metrics(items), "model_ai": metrics(kept),
            "approved": metrics([s for s in items if s.decision == "APPROVE"]),
            "downgraded": metrics([s for s in items if s.decision == "DOWNGRADE"]),
            "rejected": metrics(rejected), "abstained": metrics([s for s in items if s.decision == "ABSTAIN"])}
    rq = roi_difference(kept, rejected)
    days = len({s.kickoff_at.date() for s in items})
    checks: dict[str, dict[str, Any]] = {
        "selections": {"value": len(items), "need": MIN_SELECTIONS, "ok": len(items) >= MIN_SELECTIONS},
        "days": {"value": days, "need": MIN_DAYS, "ok": days >= MIN_DAYS},
        "rejected": {"value": len(rejected), "need": MIN_REJECTED, "ok": len(rejected) >= MIN_REJECTED},
        "rejection_quality": {"value": rq, "need": f"z >= {MIN_Z}", "ok": rq["z"] is not None and rq["z"] >= MIN_Z},
    }
    ck, cr = arms["model_ai"].get("clv"), arms["rejected"].get("clv")
    checks["clv"] = {"value": {"kept": ck, "rejected": cr}, "need": "kept >= rejected",
                     "ok": ck is not None and cr is not None and ck >= cr}
    bk, ba = arms["model_ai"].get("brier_model"), arms["model"].get("brier_model")
    checks["calibration"] = {"value": {"kept": bk, "all": ba}, "need": f"kept <= all + {BRIER_TOLERANCE}",
                             "ok": bk is not None and ba is not None and bk <= ba + BRIER_TOLERANCE}
    sample_ok = checks["selections"]["ok"] and checks["days"]["ok"] and checks["rejected"]["ok"]
    verdict = ("pass" if all(c["ok"] for c in checks.values()) else "fail" if sample_ok else "insufficient")
    gate = {"version": VERSION, "verdict": verdict, "checks": checks, "rejection_quality": rq}
    return arms, gate


@dataclass
class ShadowRun:
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)


def run_shadow(conn: psycopg.Connection[Any], *, at: datetime, store: bool = True) -> ShadowRun:
    since, until = at - WINDOW, at
    out = ShadowRun()
    for engine in ENGINES:
        items = load(conn, engine=engine, since=since, until=until)
        if engine == "llm" and not items:
            continue
        arms, gate = evaluate(items)
        out.reports[engine] = {"arms": arms, "gate": gate}
        if store:
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("INSERT INTO ai.shadow_reports (created_at, window_from, window_to, engine, arms, gate, "
                            "version) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (at, since.date(), until.date(), engine, Jsonb(arms), Jsonb(gate), VERSION))
    return out


def latest(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT DISTINCT ON (engine) engine, created_at, window_from, window_to, arms, gate, version "
                    "FROM ai.shadow_reports ORDER BY engine, created_at DESC, id DESC")
        return [dict(r) for r in cur.fetchall()]


__all__ = ["ENGINES", "VERSION", "evaluate", "latest", "load", "metrics", "run_shadow"]
