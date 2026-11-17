"""The ingestion of signals (IA-085) and the selector of sources (IA-086), by hand. See ``fbi.news.signals`` and ``fbi.ai.source_select``.

    python -m scripts.ia_signals select 31688 alineaciones          # the sources of one match for one claim type, and why (Spanish)
    python -m scripts.ia_signals select 31688 lesiones --side away --json
    python -m scripts.ia_signals day 2026-11-17                      # the matches of a day: sources chosen, readable today, if signed
    python -m scripts.ia_signals plan                                # what a pass would do now, without a single request
    python -m scripts.ia_signals run                                 # ONE pass in shadow (needs FBI_SIGNALS=shadow): reads and writes

``select``, ``day`` and ``plan`` connect read-only and write nothing; ``run`` is the worker's pass. None calls a model or Exa.
Exit 0; 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fbi.ai import source_policy
from fbi.ai import source_select as ss
from fbi.news import signals

LOCAL = ZoneInfo("America/Bogota")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_signals", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dsn")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("select", help="the sources of one match for one claim type")
    s.add_argument("fixture_id", type=int)
    s.add_argument("claim_type")
    s.add_argument("--side", choices=("home", "away"))
    s.add_argument("--market")
    s.add_argument("--json", action="store_true")
    d = sub.add_parser("day", help="the matches of a local day (America/Bogota)")
    d.add_argument("day", type=date.fromisoformat)
    d.add_argument("--json", action="store_true")
    sub.add_parser("plan", help="what a pass would do now, without requests")
    sub.add_parser("run", help="one pass in shadow")
    return ap


def _connect(dsn: str | None, *, read_only: bool) -> Any:
    import psycopg

    from fbi.core.config import settings as platform

    options = "-c default_transaction_read_only=on -c statement_timeout=60000" if read_only else "-c statement_timeout=120000"
    return psycopg.connect(dsn or platform.database.psycopg_url, options=options)


def day_contexts(conn: Any, day: date) -> list[ss.MatchContext]:
    start = datetime.combine(day, time(0), LOCAL).astimezone(UTC)
    end = start + timedelta(days=1)
    return [c for c in signals.upcoming_contexts(conn, start + timedelta(hours=3), lookahead=timedelta(days=1)) if start <= c.kickoff_at < end]


def plan(conn: Any, at: datetime) -> dict[str, Any]:
    pol = source_policy.load(conn)
    if pol is None:
        return {"error": "no registry could be read"}
    cat = ss.catalog_for(conn, pol)
    ctxs = signals.upcoming_contexts(conn, at)
    nearest = signals.nearest_kickoffs(cat, ctxs, at)
    states = signals.latest_states(conn)
    out: dict[str, Any] = {"at": at.isoformat(), "registry": pol.version, "targets": 0, "never": {}, "would_read": 0, "readable": 0,
                           "due": 0, "bands": {}, "readable_feeds": []}
    for t in signals.targets(cat):
        out["targets"] += 1
        st = pol.standing(t.url)
        why = signals.never_read(st, t)
        if why:
            key = why.split(":", 1)[0]
            out["never"][key] = out["never"].get(key, 0) + 1
            continue
        band = ss.band(nearest.get(t.source_id), at)
        out["bands"][band] = out["bands"].get(band, 0) + 1
        out["due"] += int(signals.is_due(states.get(t.key), at))
        if source_policy.can_fetch(st).allowed:
            out["readable"] += 1
            out["readable_feeds"].append({"source_id": t.source_id, "url": t.url, "band": band})
        else:
            out["would_read"] += 1
    out["exa"] = signals.plan_exa(ctxs, cat, pol, at=at).as_json()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    at = datetime.now(UTC)
    try:
        conn = _connect(args.dsn, read_only=args.command != "run")
    except Exception as exc:  # the database is the one thing this script needs
        print(json.dumps({"error": f"database: {type(exc).__name__}"}))
        return 2
    with conn:
        if args.command == "select":
            sel = ss.select_sources(conn, args.fixture_id, args.claim_type, at=at, entity_side=args.side, market=args.market)
            if sel is None:
                print(json.dumps({"error": f"no fixture {args.fixture_id}"}))
                return 2
            if args.json:
                print(json.dumps(sel.as_json(), ensure_ascii=False, indent=2))
            else:
                print("\n".join(ss.explain(sel, ss.context_for(conn, args.fixture_id))))
            return 0
        if args.command == "day":
            pol = source_policy.load(conn)
            summary = ss.summarize(day_contexts(conn, args.day), at=at, policy=pol, catalog=ss.catalog_for(conn, pol))
            if not args.json:
                summary = {k: v for k, v in summary.items() if k != "per_match"}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        if args.command == "plan":
            print(json.dumps(plan(conn, at), ensure_ascii=False, indent=2))
            return 0
        if signals.mode() != "shadow":
            print(json.dumps({"error": f"{signals.SWITCH} is not shadow: nothing is read"}))
            return 2
        import httpx

        with httpx.Client() as client:
            report = signals.run_pass(conn, at=at, fetch=signals.http_fetcher(client))
        print(json.dumps(report.as_json(), ensure_ascii=False, indent=2, default=str))
        return 0


if __name__ == "__main__":
    sys.exit(main())
