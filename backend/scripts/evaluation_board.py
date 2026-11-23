"""PM-12-01: the weekly private evaluation board (``fbi.coverage.weekly_board``) - the owner's command.

    python -m scripts.evaluation_board show [--week 2026-11-09] [--json]   # the board of a week (its Monday; the last whole one by default)
    python -m scripts.evaluation_board run                                 # compute and append the last whole week's board

Inside the worker's container (``docker exec predigol-worker python -m scripts.evaluation_board ...``). ``show`` reads only (a READ
ONLY connection, 120 s per statement); ``run`` appends one row to ``analytics.evaluation_reports`` and nothing else. 0 provider requests;
no pick, model or forecast changes. Not a proof of an edge.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any


def _iv(x: dict[str, Any]) -> str:
    if x["value"] is None:
        return "-"
    return f"{x['value']:.4f}" + ("" if x["low"] is None else f" [{x['low']:.4f}; {x['high']:.4f}]")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show")
    show.add_argument("--week", type=date.fromisoformat, help="the Monday of the week (Bogotá)")
    show.add_argument("--json", action="store_true")
    for p in (show, sub.add_parser("run")):
        p.add_argument("--at", type=datetime.fromisoformat)
    args = parser.parse_args(argv)

    import psycopg

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.core.version import code_version
    from fbi.coverage import weekly_board as wb

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name=wb.JOB) as conn:
        if args.cmd == "show":
            conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '120s'")
        at = args.at or now()
        week = None
        if getattr(args, "week", None):
            week = (args.week, args.week + timedelta(days=6))
        rep = wb.report(conn, at=at, week=week)
        if args.cmd == "run":
            report_id = wb.store(conn, rep, code_version=code_version())
            conn.commit()
            print({"report_id": report_id, "week": [rep["period_from"], rep["period_to"]]})
            return 0
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, default=str))
            return 0
        print(rep["notice_es"])
        for m in rep["markets"]:
            for label in ("week", "cumulative"):
                w = m[label]
                print(f"== {m['market']} {label} {w['from']}..{w['to']}: partidos {w['matches']}, con cada fuente {w['with_each']}, "
                      f"comunes {w['common']}")
                for s in w["sources"]:
                    print(f"   {s['source']:9} n {s['n']:>5}  log loss {_iv(s['log_loss'])}  Brier {_iv(s['brier'])}  "
                          f"fiabilidad {_iv(s['reliability'])}  resolución {_iv(s['resolution'])}  incertidumbre {s['uncertainty']:.4f}")
                for d in w["pairs"]:
                    print(f"   {d['a']} - {d['b']} {d['metric']:8} n {d['n']:>5}  {_iv(d)}  {d['verdict']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
