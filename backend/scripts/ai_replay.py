"""Replay of the rules reviewer over the historical shadow picks: would its decisions have kept the better bets?

For every shadow pick on a finished match, the packet is rebuilt AS OF the moment the pick was made (nothing
recorded later is read), the deterministic reviewer (``fbi.ai.review.rules_review``) decides, and the pick is
settled at its own price. Nothing is written: the report goes to stdout (JSON) or ``--out``.

Two honest caveats are measured and reported, not hidden:

* blocks the platform did not record at the time cannot be replayed - the competition's data score and the
  injury checks exist only from their first computation - so their two "unknown" signals would downgrade
  nearly every historical pick; the replay therefore also gives the decision WITHOUT those two signals
  (``decision_ex_unavailable``), labelled as such;
* the picks are the shadow engine's (no model has qualified): the question is whether the reviewer separates
  better from worse among them, not whether they were profitable.

    python scripts/ai_replay.py --dsn postgresql://... [--since 2026-09-01] [--limit 2000] [--out replay.json]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.packet import PacketBuilder
from fbi.ai.review import RULES_VERSION, Candidate, rules_review
from fbi.ai.shadow import Settled, evaluate, metrics
from fbi.picks.settlement import Status, market_outcome, profit

UNAVAILABLE = frozenset({"data_quality_unknown", "absences_unknown"})

PICKS_SQL = """
SELECT p.id, p.fixture_id, p.market_key, p.selection, p.line, p.market_odds, p.bookmaker_id, p.odds_captured_at,
       p.created_at, p.p_calibrated, p.p_calibrated_lo, p.p_calibrated_hi, p.p_market_fair, p.ev, p.p_push,
       r.name AS model, f.kickoff_at, res.reg_goals_home, res.reg_goals_away, fp.odds_decimal AS close_odds
  FROM picks.picks p
  JOIN models.model_versions v ON v.id = p.model_version_id JOIN models.model_registry r ON r.id = v.model_id
  JOIN core.fixtures f ON f.id = p.fixture_id
  JOIN core.fixture_results res ON res.fixture_id = f.id
  LEFT JOIN market.final_prematch_odds fp ON fp.fixture_id = p.fixture_id AND fp.bookmaker_id = p.bookmaker_id
       AND fp.market_key = p.market_key AND fp.selection = p.selection AND fp.line = p.line
 WHERE f.status_group = 'finished' AND res.reg_goals_home IS NOT NULL AND p.odds_captured_at >= %(since)s
   AND p.odds_captured_at < f.kickoff_at
 ORDER BY p.odds_captured_at, p.id
 LIMIT %(limit)s
"""


def decide_without(out: dict[str, Any], signals: list[Any], drop: frozenset[str]) -> str:
    """The rules' decision had the unavailable signals not been there (same thresholds)."""
    kept = [s for s in signals if s.code not in drop]
    if out["decision"] == "ABSTAIN":
        return "ABSTAIN"
    hard = [s for s in kept if s.severity == "hard"]
    soft = [s for s in kept if s.severity == "soft"]
    uncertain = [s for s in kept if s.severity == "uncertain"]
    if hard or len(soft) >= 3:
        return "REJECT"
    if soft or len(uncertain) >= 2:
        return "DOWNGRADE"
    return "APPROVE"


def _clustered_z(a: list[tuple[int, float]], b: list[tuple[int, float]], *, rounds: int = 300,
                 seed: int = 13) -> float | None:
    """z of ROI(a) - ROI(b) with the standard error from resampling MATCHES, not bets: the many selections of
    one match (lines of the same market) win and lose together, and counting them as independent would
    overstate any difference."""
    def groups(xs: list[tuple[int, float]]) -> list[list[float]]:
        g: dict[int, list[float]] = defaultdict(list)
        for fixture, x in xs:
            g[fixture].append(x)
        return list(g.values())

    def roi(gs: list[list[float]]) -> float:
        flat = [x for g in gs for x in g]
        return sum(flat) / len(flat) if flat else 0.0

    ga, gb = groups(a), groups(b)
    if len(ga) < 5 or len(gb) < 5:
        return None
    rng = random.Random(seed)
    boots = [roi([ga[rng.randrange(len(ga))] for _ in ga]) - roi([gb[rng.randrange(len(gb))] for _ in gb])
             for _ in range(rounds)]
    mean = sum(boots) / len(boots)
    se = math.sqrt(sum((x - mean) ** 2 for x in boots) / (len(boots) - 1))
    return round((roi(ga) - roi(gb)) / se, 2) if se > 0 else None


def signal_effects(rows: list[dict[str, Any]], *, min_matches: int = 30) -> list[dict[str, Any]]:
    """ROI at the price taken with and without each signal, and the z of the difference (match-clustered)."""
    codes = sorted({c for r in rows for c in r["signals"]})
    out = []
    for code in codes:
        a = [(r["fixture"], r["profit"]) for r in rows if code in r["signals"]]
        b = [(r["fixture"], r["profit"]) for r in rows if code not in r["signals"]]
        clv_a = [r["clv"] for r in rows if code in r["signals"] and r["clv"] is not None]
        clv_b = [r["clv"] for r in rows if code not in r["signals"] and r["clv"] is not None]
        matches_a = len({f for f, _ in a})
        out.append({"signal": code, "n_with": len(a), "matches_with": matches_a, "n_without": len(b),
                    "roi_with": round(sum(x for _, x in a) / len(a), 4) if a else None,
                    "roi_without": round(sum(x for _, x in b) / len(b), 4) if b else None,
                    "z_clustered": _clustered_z(a, b),
                    "clv_with": round(sum(clv_a) / len(clv_a), 4) if clv_a else None,
                    "clv_without": round(sum(clv_b) / len(clv_b), 4) if clv_b else None,
                    "enough": matches_a >= min_matches and len({f for f, _ in b}) >= min_matches})
    return out


def run(dsn: str, *, since: datetime, limit: int) -> dict[str, Any]:
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    with psycopg.connect(dsn) as conn:
        conn.execute("SET default_transaction_read_only = on")
        builder = PacketBuilder(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(PICKS_SQL, {"since": since, "limit": limit})
            picks = [dict(r) for r in cur.fetchall()]
        for p in picks:
            at: datetime = p["odds_captured_at"]
            line = Decimal(p["line"])
            packet = builder.build(int(p["fixture_id"]), at=at, extra_keys=[(p["market_key"], p["selection"], line)])
            if packet is None:
                skipped["no_packet"] += 1
                continue
            entry = next((s for s in packet.content["market"]["selections"] if s["market"] == p["market_key"]
                          and s["selection"] == p["selection"] and Decimal(s["line"]) == line), None)
            c = Candidate(fixture_id=int(p["fixture_id"]), market_key=p["market_key"], selection=p["selection"],
                          line=line, p_model=Decimal(p["p_calibrated"]), kickoff_at=p["kickoff_at"], pick_id=int(p["id"]),
                          odds=Decimal(p["market_odds"]), bookmaker_id=p["bookmaker_id"],
                          p_low=p["p_calibrated_lo"], p_high=p["p_calibrated_hi"], p_push=p["p_push"],
                          p_market=Decimal(p["p_market_fair"]), ev=Decimal(p["ev"]), model=p["model"],
                          n_bookmakers=None if entry is None else entry.get("n_bookmakers"), price_at=at,
                          selected_at=p["created_at"])
            out, signals = rules_review(c, packet, at=at)
            try:
                st = market_outcome(p["market_key"], p["selection"], line, int(p["reg_goals_home"]),
                                    int(p["reg_goals_away"]))
            except ValueError:
                skipped["unknown_market"] += 1
                continue
            if st == Status.PENDING:
                skipped["pending"] += 1
                continue
            prof = float(profit(st, Decimal(p["market_odds"]), Decimal(1)))
            close = float(p["close_odds"]) if p["close_odds"] else None
            rows.append({"pick": int(p["id"]), "fixture": int(p["fixture_id"]), "kickoff": p["kickoff_at"],
                         "market": p["market_key"], "decision": out["decision"],
                         "decision_ex_unavailable": decide_without(out, signals, UNAVAILABLE),
                         "signals": [s.code for s in signals], "status": st.value, "profit": prof,
                         "odds": float(p["market_odds"]), "p_model": float(p["p_calibrated"]),
                         "p_market": float(p["p_market_fair"]),
                         "clv": None if not close else float(p["market_odds"]) / close - 1,
                         "close": close, "tokens": packet.approx_tokens, "missing": packet.missing})
    report: dict[str, Any] = {"rules_version": RULES_VERSION, "since": since.isoformat(), "picks": len(rows),
                              "skipped": dict(skipped), "seconds": round(time.monotonic() - started, 1)}
    for key in ("decision", "decision_ex_unavailable"):
        settled = [Settled(r["fixture"], r["kickoff"], r[key], r["odds"], r["p_model"], r["p_market"], r["status"],
                           r["profit"], r["close"]) for r in rows]
        arms, gate = evaluate(settled)
        report[key] = {"arms": arms, "gate": gate,
                       "counts": {d: sum(1 for r in rows if r[key] == d)
                                  for d in ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN")}}
    report["by_market"] = {m: metrics([Settled(r["fixture"], r["kickoff"], r["decision_ex_unavailable"], r["odds"],
                                               r["p_model"], r["p_market"], r["status"], r["profit"], r["close"])
                                       for r in rows if r["market"] == m])
                           for m in sorted({r["market"] for r in rows})}
    report["signals"] = signal_effects(rows)
    report["signal_frequency"] = {code: sum(1 for r in rows if code in r["signals"])
                                  for code in sorted({c for r in rows for c in r["signals"]})}
    report["missing_blocks"] = {b: sum(1 for r in rows if b in r["missing"])
                                for b in sorted({b for r in rows for b in r["missing"]})}
    report["packet_tokens"] = {"avg": round(sum(r["tokens"] for r in rows) / len(rows), 1) if rows else None,
                               "max": max((r["tokens"] for r in rows), default=None)}
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--since", default="2000-01-01")
    ap.add_argument("--limit", type=int, default=1_000_000)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        from datetime import UTC

        since = since.replace(tzinfo=UTC)
    report = run(args.dsn, since=since, limit=args.limit)
    text = json.dumps(report, indent=1, default=str, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
