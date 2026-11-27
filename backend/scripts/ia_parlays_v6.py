"""The tracking of loose selections (IA-109, AD-E05) and ``parlay-v6`` (IA-110, AD-E06): the owner's command, read-only by default.

    python -m scripts.ia_parlays_v6 settle [--dry-run]                       # one pass of the tracking (needs FBI_SELECTION_SETTLE=shadow)
    python -m scripts.ia_parlays_v6 build [--dry-run]                        # one pass of parlay-v6 (needs FBI_PARLAY_V6=shadow)
    python -m scripts.ia_parlays_v6 preview --kind daily                     # what parlay-v6 would build now (read-only)
    python -m scripts.ia_parlays_v6 read --from 2026-11-20 --to 2026-11-30   # the parlays kept, their results and the calibration
    python -m scripts.ia_parlays_v6 acceptance [--from 2026-11-27]            # the owner's criterion for the joint (``fbi.parlays.acceptance``) on the parlays of the window, per estimator
    python -m scripts.ia_parlays_v6 parity --days 14                         # AD-E05: the tracking against settle-v4 (read-only)
    python -m scripts.ia_parlays_v6 selection --fixture 123 --market OU --selection Over --line 2.5   # one selection, in plain words

Every command but ``settle`` and ``build`` without ``--dry-run`` opens a read-only connection. Exit status: 0 done, 2 it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.parlays import acceptance
from fbi.tracking import parlay_v6 as v6
from fbi.tracking import parlay_v6_shadow as v6_shadow
from fbi.tracking import selections as tracking

READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_parlays_v6", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dsn", help="the database (default: the platform's)")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("settle", "build"):
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    p = sub.add_parser("preview")
    p.add_argument("--kind", choices=tuple(v6.SPECS), default="daily")
    r = sub.add_parser("read")
    r.add_argument("--from", dest="date_from", required=True)
    r.add_argument("--to", dest="date_to", required=True)
    a = sub.add_parser("acceptance")
    a.add_argument("--from", dest="date_from", default=acceptance.FROZEN_ON.isoformat(), help="the first day of the window (never before the signature of the criterion)")
    q = sub.add_parser("parity")
    q.add_argument("--days", type=int, default=14)
    s = sub.add_parser("selection")
    s.add_argument("--writer", default=tracking.WRITERS[0])
    s.add_argument("--fixture", type=int, required=True)
    s.add_argument("--market", required=True)
    s.add_argument("--selection", required=True)
    s.add_argument("--line", default="0")
    return ap


def _preview(res: v6.Built | v6.NoParlay) -> dict[str, Any]:
    if isinstance(res, v6.NoParlay):
        return {"outcome": "none", "reason": res.reason, "candidates": res.n_candidates, "refused": dict(res.refused)}
    j = res.joint
    return {"outcome": "built", "legs": [{"chain_key": c.chain_key, "market": c.market_key, "selection": c.selection, "line": str(c.line),
                                          "odds": c.odds, "p": c.p, "p_low": c.p_low} for c in res.legs],
            "combined_odds": res.combined_odds, "p_joint": j.p, "p_joint_se": j.se, "p_joint_low": j.p_low, "p_product": j.product,
            "fair_odds": res.fair_odds, "accumulated_margin": res.accumulated_margin, "expected_value": res.expected_value,
            "dependence": list(res.dependence)}


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    dsn = args.dsn or platform.database.psycopg_url
    out: Any
    at = now()
    if args.command in ("settle", "build"):
        switch, mode = (tracking.SWITCH, tracking.mode()) if args.command == "settle" else (v6_shadow.SWITCH, v6_shadow.mode())
        if not args.dry_run and mode != "shadow":
            sys.stderr.write(f"{switch} is not shadow: nothing is written (use --dry-run to see what a pass would do)\n")
            return 2
        with psycopg.connect(dsn, options=READ_ONLY if args.dry_run else "-c TimeZone=UTC") as conn:
            if args.command == "settle":
                out = tracking.run_pass(conn, now=at, dry_run=args.dry_run).as_json()
            else:
                out = v6_shadow.run_pass(conn, now=at, dry_run=args.dry_run).as_json()
    else:
        with psycopg.connect(dsn, options=READ_ONLY) as conn:
            if args.command == "preview":
                out = _preview(v6_shadow.build(conn, kind=args.kind, at=at))
            elif args.command == "read":
                start, end = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
                if end < start or (end - start).days > 92:
                    ap.error("a period is 1 to 93 days")
                parlays = v6_shadow.read(conn, start=start, end=end)
                out = {"parlays": parlays, "calibration": v6_shadow.calibration(parlays)}
            elif args.command == "acceptance":
                start = max(date.fromisoformat(args.date_from), acceptance.FROZEN_ON)
                today = at.date()
                parlays = []
                for first in range((today - start).days // 90 + 1):
                    block_start = start + timedelta(days=90 * first)
                    parlays += v6_shadow.read(conn, start=block_start, end=min(today, block_start + timedelta(days=89)))
                readings = acceptance.judge_all(parlays, since=start)
                out = {"version": acceptance.VERSION, "protocol": acceptance.PROTOCOL.key, "since": start.isoformat(), "stated": acceptance.SAID,
                       "estimators": {k: r.as_json() for k, r in readings.items()}, "opens_the_door": readings[acceptance.SAID].verdict == "cumple"}
            elif args.command == "parity":
                out = tracking.parity(conn, start=at - timedelta(days=max(1, min(args.days, 62))), end=at)
            else:
                out = tracking.tracking(conn, writer=args.writer, fixture_id=args.fixture, market_key=args.market,
                                        selection=args.selection, line=args.line)
    sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
